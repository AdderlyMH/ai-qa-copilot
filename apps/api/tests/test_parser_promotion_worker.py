from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ai_qa_copilot_api.ingestion import DocumentIntakeUnavailable
from ai_qa_copilot_api.markdown_parser import DocumentParseRejected, ParsedRequirement
from ai_qa_copilot_api.parser_evidence_promotion import (
    ClaimedDocument,
    ParserEvidenceUnavailable,
    PromotedParserEvidence,
)
from ai_qa_copilot_api.parser_job_claims import (
    ClaimedParserJob,
    ParserJobClaimRejected,
)
from ai_qa_copilot_api.parser_promotion_worker import (
    ParserPromotionRunState,
    ParserPromotionWorker,
)
from ai_qa_copilot_api.parser_worker import ParserWorkerConfigurationError


NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
CLAIM = ClaimedParserJob(
    job_id=uuid4(),
    document_intake_id=uuid4(),
    claim_token=uuid4(),
    claimed_at=NOW,
    claim_expires_at=NOW + timedelta(seconds=60),
)
DOCUMENT = ClaimedDocument(
    document_type="markdown", raw=b"REQ-001: Quantity must be positive.\n"
)


@dataclass
class FakeClaims:
    claim: ClaimedParserJob | None = CLAIM
    rejected: list[ClaimedParserJob] = field(default_factory=list)
    failed: list[ClaimedParserJob] = field(default_factory=list)

    def claim_next(self) -> ClaimedParserJob | None:
        claim, self.claim = self.claim, None
        return claim

    def reject(self, claim: ClaimedParserJob) -> None:
        self.rejected.append(claim)

    def fail(self, claim: ClaimedParserJob) -> None:
        self.failed.append(claim)


@dataclass
class FakeReader:
    document: ClaimedDocument = DOCUMENT
    error: Exception | None = None
    claims: list[ClaimedParserJob] = field(default_factory=list)

    def read(self, claim: ClaimedParserJob) -> ClaimedDocument:
        self.claims.append(claim)
        if self.error is not None:
            raise self.error
        return self.document


@dataclass
class FakePromoter:
    result: PromotedParserEvidence = PromotedParserEvidence(
        uuid4(), uuid4(), (uuid4(),)
    )
    error: Exception | None = None
    calls: list[
        tuple[ClaimedParserJob, ClaimedDocument, tuple[ParsedRequirement, ...]]
    ] = field(default_factory=list)

    def promote(
        self,
        claim: ClaimedParserJob,
        *,
        document: ClaimedDocument,
        requirements: tuple[ParsedRequirement, ...],
    ) -> PromotedParserEvidence:
        self.calls.append((claim, document, requirements))
        if self.error is not None:
            raise self.error
        return self.result


def worker(
    claims: FakeClaims | None = None,
    reader: FakeReader | None = None,
    promoter: FakePromoter | None = None,
    runtime_verifier: Callable[[], object] | None = None,
) -> tuple[ParserPromotionWorker, FakeClaims, FakeReader, FakePromoter]:
    actual_claims = claims or FakeClaims()
    actual_reader = reader or FakeReader()
    actual_promoter = promoter or FakePromoter()
    return (
        ParserPromotionWorker(
            claims=actual_claims,
            reader=actual_reader,
            promoter=actual_promoter,
            runtime_verifier=runtime_verifier or (lambda: None),
        ),
        actual_claims,
        actual_reader,
        actual_promoter,
    )


def test_successful_turn_verifies_runtime_then_promotes_once() -> None:
    order: list[str] = []

    def verify() -> None:
        order.append("runtime")

    class OrderedClaims(FakeClaims):
        def claim_next(self) -> ClaimedParserJob | None:
            order.append("claim")
            return super().claim_next()

    run_worker, claims, reader, promoter = worker(
        claims=OrderedClaims(), runtime_verifier=verify
    )
    run = run_worker.run_once()
    assert order == ["runtime", "claim"]
    assert run.state == ParserPromotionRunState.ACCEPTED
    assert run.job_id == CLAIM.job_id
    assert run.document_version_id == promoter.result.document_version_id
    assert run.section_count == 1
    assert reader.claims == [CLAIM]
    assert len(promoter.calls) == 1
    assert promoter.calls[0][0] == CLAIM
    assert claims.rejected == []
    assert claims.failed == []


def test_idle_turn_does_not_read_or_promote() -> None:
    run_worker, claims, reader, promoter = worker(claims=FakeClaims(claim=None))
    run = run_worker.run_once()
    assert run.state == ParserPromotionRunState.IDLE
    assert run.job_id is None
    assert reader.claims == []
    assert promoter.calls == []
    assert claims.rejected == []
    assert claims.failed == []


def test_runtime_failure_claims_nothing() -> None:
    def fail_runtime() -> None:
        raise ParserWorkerConfigurationError("network is not denied")

    run_worker, claims, reader, promoter = worker(runtime_verifier=fail_runtime)
    with pytest.raises(ParserWorkerConfigurationError, match="network"):
        run_worker.run_once()
    assert claims.claim == CLAIM
    assert reader.claims == []
    assert promoter.calls == []


@pytest.mark.parametrize(
    ("reader", "promoter"),
    [
        (FakeReader(document=ClaimedDocument("markdown", b"\xff")), FakePromoter()),
        (FakeReader(), FakePromoter(error=DocumentParseRejected("invalid output"))),
    ],
)
def test_parse_rejection_terminalizes_the_claim_as_rejected(
    reader: FakeReader, promoter: FakePromoter
) -> None:
    run_worker, claims, _, _ = worker(reader=reader, promoter=promoter)
    run = run_worker.run_once()
    assert run.state == ParserPromotionRunState.REJECTED
    assert claims.rejected == [CLAIM]
    assert claims.failed == []


@pytest.mark.parametrize(
    ("reader_error", "promoter_error"),
    [
        (DocumentIntakeUnavailable(), None),
        (None, ParserEvidenceUnavailable("database unavailable")),
    ],
)
def test_private_dependency_failure_terminalizes_the_claim_as_failed(
    reader_error: Exception | None, promoter_error: Exception | None
) -> None:
    run_worker, claims, _, _ = worker(
        reader=FakeReader(error=reader_error),
        promoter=FakePromoter(error=promoter_error),
    )
    run = run_worker.run_once()
    assert run.state == ParserPromotionRunState.FAILED
    assert claims.rejected == []
    assert claims.failed == [CLAIM]


def test_stale_claim_is_never_terminalized_or_published() -> None:
    run_worker, claims, _, _ = worker(
        promoter=FakePromoter(error=ParserJobClaimRejected("claim expired"))
    )
    run = run_worker.run_once()
    assert run.state == ParserPromotionRunState.NOT_PUBLISHED
    assert claims.rejected == []
    assert claims.failed == []


def test_unexpected_failure_is_terminalized_then_propagated() -> None:
    class CrashingReader(FakeReader):
        def read(self, claim: ClaimedParserJob) -> ClaimedDocument:
            raise RuntimeError("injected worker failure")

    run_worker, claims, _, _ = worker(reader=CrashingReader())
    with pytest.raises(RuntimeError, match="injected"):
        run_worker.run_once()
    assert claims.failed == [CLAIM]
