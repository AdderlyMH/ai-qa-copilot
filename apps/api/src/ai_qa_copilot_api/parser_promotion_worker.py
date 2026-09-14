"""One restricted, injected worker turn for Markdown/text parser promotion.

This module neither opens a network connection nor configures a storage backend.
Deployment composition remains responsible for providing private worker-side
database and quarantine access after the existing runtime preflight succeeds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.ingestion import DocumentIntakeUnavailable
from ai_qa_copilot_api.markdown_parser import (
    DocumentParseRejected,
    ParsedRequirement,
    parse_markdown_or_text,
)
from ai_qa_copilot_api.parser_evidence_promotion import (
    ClaimedDocument,
    ParserEvidenceUnavailable,
    PromotedParserEvidence,
    QuarantineReader,
    SqlAlchemyClaimedDocumentReader,
    SqlAlchemyParserEvidencePromotion,
)
from ai_qa_copilot_api.parser_job_claims import (
    ClaimedParserJob,
    ParserJobClaimRejected,
    SqlAlchemyParserJobClaims,
)
from ai_qa_copilot_api.parser_worker import verify_runtime
from ai_qa_copilot_api.parser_queue import utc_now


MARKDOWN_TEXT_DOCUMENT_TYPES = frozenset({"markdown", "text"})


class ParserPromotionRunState(StrEnum):
    """One worker turn never leaves a claim silently retryable."""

    IDLE = "idle"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    NOT_PUBLISHED = "not_published"


@dataclass(frozen=True)
class ParserPromotionRun:
    """Sanitized worker outcome; raw document content is never retained here."""

    state: ParserPromotionRunState
    job_id: UUID | None
    document_version_id: UUID | None = None
    section_count: int = 0


class ParserJobClaims(Protocol):
    def claim_next(self) -> ClaimedParserJob | None: ...

    def reject(self, claim: ClaimedParserJob) -> None: ...

    def fail(self, claim: ClaimedParserJob) -> None: ...


class ClaimedDocumentReader(Protocol):
    def read(self, claim: ClaimedParserJob) -> ClaimedDocument: ...


class ParserEvidencePromoter(Protocol):
    def promote(
        self,
        claim: ClaimedParserJob,
        *,
        document: ClaimedDocument,
        requirements: tuple[ParsedRequirement, ...],
    ) -> PromotedParserEvidence: ...


class ParserPromotionWorker:
    """Consume at most one valid Markdown/text claim after runtime verification."""

    def __init__(
        self,
        *,
        claims: ParserJobClaims,
        reader: ClaimedDocumentReader,
        promoter: ParserEvidencePromoter,
        runtime_verifier: Callable[[], object] = verify_runtime,
    ) -> None:
        self._claims = claims
        self._reader = reader
        self._promoter = promoter
        self._runtime_verifier = runtime_verifier

    def run_once(self) -> ParserPromotionRun:
        """Perform one no-network worker turn, terminalizing known failures."""

        self._runtime_verifier()
        claim = self._claims.claim_next()
        if claim is None:
            return ParserPromotionRun(ParserPromotionRunState.IDLE, None)
        try:
            document = self._reader.read(claim)
            requirements = parse_markdown_or_text(
                document_type=document.document_type, raw=document.raw
            )
            evidence = self._promoter.promote(
                claim, document=document, requirements=requirements
            )
            return ParserPromotionRun(
                ParserPromotionRunState.ACCEPTED,
                claim.job_id,
                evidence.document_version_id,
                len(evidence.section_ids),
            )
        except DocumentParseRejected:
            return self._terminalize(claim, rejected=True)
        except (DocumentIntakeUnavailable, ParserEvidenceUnavailable):
            return self._terminalize(claim, rejected=False)
        except ParserJobClaimRejected:
            return ParserPromotionRun(
                ParserPromotionRunState.NOT_PUBLISHED, claim.job_id
            )
        except Exception:
            self._terminalize(claim, rejected=False)
            raise

    def _terminalize(
        self, claim: ClaimedParserJob, *, rejected: bool
    ) -> ParserPromotionRun:
        try:
            if rejected:
                self._claims.reject(claim)
                state = ParserPromotionRunState.REJECTED
            else:
                self._claims.fail(claim)
                state = ParserPromotionRunState.FAILED
        except ParserJobClaimRejected:
            return ParserPromotionRun(
                ParserPromotionRunState.NOT_PUBLISHED, claim.job_id
            )
        return ParserPromotionRun(state, claim.job_id)


def create_markdown_text_promotion_worker(
    sessions: sessionmaker[Session],
    storage: QuarantineReader,
    *,
    runtime_verifier: Callable[[], object] = verify_runtime,
    clock: Callable[[], datetime] = utc_now,
) -> ParserPromotionWorker:
    """Build the private worker turn; this is not an application-route factory."""

    return ParserPromotionWorker(
        claims=SqlAlchemyParserJobClaims(
            sessions,
            clock=clock,
            document_types=MARKDOWN_TEXT_DOCUMENT_TYPES,
        ),
        reader=SqlAlchemyClaimedDocumentReader(sessions, storage, clock=clock),
        promoter=SqlAlchemyParserEvidencePromotion(sessions, clock=clock),
        runtime_verifier=runtime_verifier,
    )
