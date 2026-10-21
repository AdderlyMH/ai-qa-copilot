"""One restricted, injected worker turn for Markdown/text parser promotion.

This module neither opens a network connection nor configures a storage backend.
Deployment composition remains responsible for providing private worker-side
database and quarantine access after the existing runtime preflight succeeds.

Every claimed job ends with one sanitized ``event=parser.outcome`` log line
built only from a fixed vocabulary: the outcome, a reason from
``ParserOutcomeReason``, two counts and an exception class name. It never
carries content, filenames, identifiers, storage keys or exception messages.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import logging
import re
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
from ai_qa_copilot_api.parser_queue import ParserJobQueueUnavailable, utc_now


MARKDOWN_TEXT_DOCUMENT_TYPES = frozenset({"markdown", "text"})

PARSER_OUTCOME_LOGGER_NAME = "ai_qa_copilot_api.parser_outcome"
PARSER_OUTCOME_EVENT = "parser.outcome"

# With the Text log format and no application log level, the Lambda Python
# runtime attaches its handler to the root logger and leaves the root at
# Python's default WARNING, so INFO records from loggers without their own
# level are dropped. This logger's own level lets its INFO lines through to
# the runtime's handler without changing the root logger.
_outcome_logger = logging.getLogger(PARSER_OUTCOME_LOGGER_NAME)
_outcome_logger.setLevel(logging.INFO)

_EXCEPTION_CLASS_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


class ParserOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    NOT_PUBLISHED = "not_published"


class ParserOutcomeReason(StrEnum):
    """Closed reason vocabulary for the outcome line; never free text."""

    NONE = "none"
    # DocumentParseRejected codes raised by the parser, reader and promotion.
    DOCUMENT_TYPE_UNSUPPORTED = "PARSER_DOCUMENT_TYPE_UNSUPPORTED"
    TEXT_ENCODING_INVALID = "PARSER_TEXT_ENCODING_INVALID"
    TEXT_CODEPOINT_LIMIT = "PARSER_TEXT_CODEPOINT_LIMIT"
    LINE_COUNT_LIMIT = "PARSER_LINE_COUNT_LIMIT"
    LINE_SIZE_LIMIT = "PARSER_LINE_SIZE_LIMIT"
    SOURCE_PROVENANCE_INVALID = "PARSER_SOURCE_PROVENANCE_INVALID"
    SOURCE_INTEGRITY_INVALID = "PARSER_SOURCE_INTEGRITY_INVALID"
    EVIDENCE_INVALID = "PARSER_EVIDENCE_INVALID"
    VERSION_NOT_PENDING = "PARSER_VERSION_NOT_PENDING"
    EVIDENCE_ALREADY_EXISTS = "PARSER_EVIDENCE_ALREADY_EXISTS"
    REJECTED_UNCLASSIFIED = "PARSER_REJECTED_UNCLASSIFIED"
    # Failures and unstored outcomes.
    SOURCE_UNAVAILABLE = "PARSER_SOURCE_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "PARSER_DATABASE_UNAVAILABLE"
    WORKER_EXCEPTION = "PARSER_WORKER_EXCEPTION"
    OUTCOME_NOT_STORED = "PARSER_OUTCOME_NOT_STORED"
    CLAIM_NOT_ACTIVE = "PARSER_CLAIM_NOT_ACTIVE"


_REJECTION_REASONS = {
    reason.value: reason
    for reason in ParserOutcomeReason
    if reason
    not in {
        ParserOutcomeReason.NONE,
        ParserOutcomeReason.REJECTED_UNCLASSIFIED,
        ParserOutcomeReason.SOURCE_UNAVAILABLE,
        ParserOutcomeReason.DATABASE_UNAVAILABLE,
        ParserOutcomeReason.WORKER_EXCEPTION,
        ParserOutcomeReason.OUTCOME_NOT_STORED,
        ParserOutcomeReason.CLAIM_NOT_ACTIVE,
    }
}


def _rejection_reason(error: DocumentParseRejected) -> ParserOutcomeReason:
    """Map a rejection to the closed set; its text is compared, never logged."""

    code = error.args[0] if error.args else None
    if isinstance(code, str) and code in _REJECTION_REASONS:
        return _REJECTION_REASONS[code]
    return ParserOutcomeReason.REJECTED_UNCLASSIFIED


def _exception_class_name(error: BaseException) -> str:
    name = type(error).__name__
    return name if _EXCEPTION_CLASS_NAME.fullmatch(name) else "unknown"


def log_parser_outcome(
    outcome: ParserOutcome,
    reason: ParserOutcomeReason,
    *,
    sections: int = 0,
    requirements: int | None = None,
    exc_type: str = "none",
) -> None:
    """Emit the sanitized outcome line; a logging error never affects the job."""

    try:
        _outcome_logger.log(
            logging.WARNING if outcome is ParserOutcome.FAILED else logging.INFO,
            "event=%s outcome=%s reason=%s sections=%d requirements=%s exc_type=%s",
            PARSER_OUTCOME_EVENT,
            outcome.value,
            reason.value,
            sections,
            "none" if requirements is None else str(requirements),
            exc_type,
        )
    except Exception:  # noqa: BLE001 - logging must never fail or retry a job
        pass


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
        # Counted only once parsing ran; None means the parser never saw input.
        requirement_count: int | None = None
        try:
            document = self._reader.read(claim)
            requirements = parse_markdown_or_text(
                document_type=document.document_type, raw=document.raw
            )
            requirement_count = len(requirements)
            evidence = self._promoter.promote(
                claim, document=document, requirements=requirements
            )
            log_parser_outcome(
                ParserOutcome.ACCEPTED,
                ParserOutcomeReason.NONE,
                sections=len(evidence.section_ids),
                requirements=requirement_count,
            )
            return ParserPromotionRun(
                ParserPromotionRunState.ACCEPTED,
                claim.job_id,
                evidence.document_version_id,
                len(evidence.section_ids),
            )
        except DocumentParseRejected as error:
            return self._terminalize(
                claim,
                rejected=True,
                reason=_rejection_reason(error),
                requirements=requirement_count,
            )
        except DocumentIntakeUnavailable as error:
            return self._terminalize(
                claim,
                rejected=False,
                reason=ParserOutcomeReason.SOURCE_UNAVAILABLE,
                requirements=requirement_count,
                exc_type=_exception_class_name(error),
            )
        except ParserEvidenceUnavailable as error:
            return self._terminalize(
                claim,
                rejected=False,
                reason=ParserOutcomeReason.DATABASE_UNAVAILABLE,
                requirements=requirement_count,
                exc_type=_exception_class_name(error),
            )
        except ParserJobClaimRejected:
            log_parser_outcome(
                ParserOutcome.NOT_PUBLISHED,
                ParserOutcomeReason.CLAIM_NOT_ACTIVE,
                requirements=requirement_count,
            )
            return ParserPromotionRun(
                ParserPromotionRunState.NOT_PUBLISHED, claim.job_id
            )
        except Exception as error:
            self._terminalize(
                claim,
                rejected=False,
                reason=ParserOutcomeReason.WORKER_EXCEPTION,
                requirements=requirement_count,
                exc_type=_exception_class_name(error),
            )
            raise

    def _terminalize(
        self,
        claim: ClaimedParserJob,
        *,
        rejected: bool,
        reason: ParserOutcomeReason,
        requirements: int | None,
        exc_type: str = "none",
    ) -> ParserPromotionRun:
        try:
            if rejected:
                self._claims.reject(claim)
                state = ParserPromotionRunState.REJECTED
            else:
                self._claims.fail(claim)
                state = ParserPromotionRunState.FAILED
        except ParserJobClaimRejected:
            log_parser_outcome(
                ParserOutcome.NOT_PUBLISHED,
                ParserOutcomeReason.CLAIM_NOT_ACTIVE,
                requirements=requirements,
            )
            return ParserPromotionRun(
                ParserPromotionRunState.NOT_PUBLISHED, claim.job_id
            )
        except ParserJobQueueUnavailable:
            # The terminal state could not be stored; the reaper later records
            # PARSER_CLAIM_EXPIRED. The error still propagates unchanged.
            log_parser_outcome(
                ParserOutcome.FAILED,
                ParserOutcomeReason.OUTCOME_NOT_STORED,
                requirements=requirements,
                exc_type=ParserJobQueueUnavailable.__name__,
            )
            raise
        log_parser_outcome(
            ParserOutcome.REJECTED if rejected else ParserOutcome.FAILED,
            reason,
            requirements=requirements,
            exc_type=exc_type,
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
