from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
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
from ai_qa_copilot_api import parser_promotion_worker
from ai_qa_copilot_api.parser_promotion_worker import (
    PARSER_OUTCOME_LOGGER_NAME,
    ParserOutcomeReason,
    ParserPromotionRunState,
    ParserPromotionWorker,
)
from ai_qa_copilot_api.parser_queue import ParserJobQueueUnavailable
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
        uuid4(), uuid4(), (uuid4(),), uuid4()
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


# --- Sanitized outcome line ---------------------------------------------------


def outcome_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records if record.name == PARSER_OUTCOME_LOGGER_NAME
    ]


def outcome_line(
    outcome: str,
    reason: str,
    *,
    sections: int = 0,
    requirements: str = "none",
    exc_type: str = "none",
) -> str:
    return (
        f"event=parser.outcome outcome={outcome} reason={reason} "
        f"sections={sections} requirements={requirements} exc_type={exc_type}"
    )


def test_accepted_job_logs_one_info_outcome_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_worker, _, _, _ = worker()

    run_worker.run_once()

    records = outcome_records(caplog)
    assert [record.getMessage() for record in records] == [
        outcome_line("accepted", "none", sections=1, requirements="1")
    ]
    assert records[0].levelno == logging.INFO


def test_zero_requirement_rejection_logs_the_reason_and_a_zero_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_worker, claims, _, _ = worker(
        reader=FakeReader(document=ClaimedDocument("markdown", b"# Heading\nProse.\n")),
        promoter=FakePromoter(error=DocumentParseRejected("PARSER_EVIDENCE_INVALID")),
    )

    run = run_worker.run_once()

    assert run.state == ParserPromotionRunState.REJECTED
    assert claims.rejected == [CLAIM]
    assert [record.getMessage() for record in outcome_records(caplog)] == [
        outcome_line("rejected", "PARSER_EVIDENCE_INVALID", requirements="0")
    ]


def test_integrity_rejection_before_parsing_logs_no_requirement_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_worker, _, _, _ = worker(
        reader=FakeReader(
            error=DocumentParseRejected("PARSER_SOURCE_INTEGRITY_INVALID")
        )
    )

    run_worker.run_once()

    assert [record.getMessage() for record in outcome_records(caplog)] == [
        outcome_line("rejected", "PARSER_SOURCE_INTEGRITY_INVALID")
    ]


def test_parser_encoding_rejection_uses_the_parser_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_worker, _, _, _ = worker(
        reader=FakeReader(document=ClaimedDocument("markdown", b"\xff"))
    )

    run_worker.run_once()

    assert [record.getMessage() for record in outcome_records(caplog)] == [
        outcome_line("rejected", "PARSER_TEXT_ENCODING_INVALID")
    ]


def test_an_unknown_rejection_text_is_never_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_worker, _, _, _ = worker(
        promoter=FakePromoter(error=DocumentParseRejected("free-text-marker-31"))
    )

    run_worker.run_once()

    assert [record.getMessage() for record in outcome_records(caplog)] == [
        outcome_line("rejected", "PARSER_REJECTED_UNCLASSIFIED", requirements="1")
    ]
    assert "free-text-marker-31" not in caplog.text


@pytest.mark.parametrize(
    ("reader_error", "promoter_error", "reason", "exc_type", "requirements"),
    [
        (
            DocumentIntakeUnavailable("storage-message-marker"),
            None,
            "PARSER_SOURCE_UNAVAILABLE",
            "DocumentIntakeUnavailable",
            "none",
        ),
        (
            None,
            ParserEvidenceUnavailable("database-message-marker"),
            "PARSER_DATABASE_UNAVAILABLE",
            "ParserEvidenceUnavailable",
            "1",
        ),
    ],
)
def test_dependency_failure_logs_a_warning_with_the_class_only(
    caplog: pytest.LogCaptureFixture,
    reader_error: Exception | None,
    promoter_error: Exception | None,
    reason: str,
    exc_type: str,
    requirements: str,
) -> None:
    run_worker, _, _, _ = worker(
        reader=FakeReader(error=reader_error),
        promoter=FakePromoter(error=promoter_error),
    )

    run_worker.run_once()

    records = outcome_records(caplog)
    assert [record.getMessage() for record in records] == [
        outcome_line("failed", reason, requirements=requirements, exc_type=exc_type)
    ]
    assert records[0].levelno == logging.WARNING
    assert "message-marker" not in caplog.text


def test_post_claim_exception_logs_its_class_but_not_its_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class CrashingReader(FakeReader):
        def read(self, claim: ClaimedParserJob) -> ClaimedDocument:
            raise KeyError("exception-message-marker-77")

    run_worker, claims, _, _ = worker(reader=CrashingReader())

    with pytest.raises(KeyError):
        run_worker.run_once()

    assert claims.failed == [CLAIM]
    assert [record.getMessage() for record in outcome_records(caplog)] == [
        outcome_line("failed", "PARSER_WORKER_EXCEPTION", exc_type="KeyError")
    ]
    assert "exception-message-marker-77" not in caplog.text


def test_lost_claim_logs_not_published(caplog: pytest.LogCaptureFixture) -> None:
    run_worker, _, _, _ = worker(
        promoter=FakePromoter(error=ParserJobClaimRejected("claim expired"))
    )

    run_worker.run_once()

    assert [record.getMessage() for record in outcome_records(caplog)] == [
        outcome_line("not_published", "PARSER_CLAIM_NOT_ACTIVE", requirements="1")
    ]


def test_unstored_outcome_is_logged_and_the_error_still_propagates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class UnavailableClaims(FakeClaims):
        def reject(self, claim: ClaimedParserJob) -> None:
            raise ParserJobQueueUnavailable("store-message-marker")

    run_worker, _, _, _ = worker(
        claims=UnavailableClaims(),
        reader=FakeReader(document=ClaimedDocument("markdown", b"\xff")),
    )

    with pytest.raises(ParserJobQueueUnavailable):
        run_worker.run_once()

    assert [record.getMessage() for record in outcome_records(caplog)] == [
        outcome_line(
            "failed",
            "PARSER_OUTCOME_NOT_STORED",
            exc_type="ParserJobQueueUnavailable",
        )
    ]
    assert "store-message-marker" not in caplog.text


def test_idle_turn_logs_no_outcome(caplog: pytest.LogCaptureFixture) -> None:
    run_worker, _, _, _ = worker(claims=FakeClaims(claim=None))

    run_worker.run_once()

    assert outcome_records(caplog) == []


def test_a_logging_failure_never_changes_the_job_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_log(*args: object, **kwargs: object) -> None:
        raise RuntimeError("handler broken")

    monkeypatch.setattr(parser_promotion_worker._outcome_logger, "log", broken_log)
    run_worker, claims, _, _ = worker(
        reader=FakeReader(document=ClaimedDocument("markdown", b"\xff"))
    )

    assert run_worker.run_once().state == ParserPromotionRunState.REJECTED
    assert claims.rejected == [CLAIM]
    accepted, _, _, _ = worker()
    assert accepted.run_once().state == ParserPromotionRunState.ACCEPTED


def test_every_known_rejection_code_maps_to_itself() -> None:
    for code in (
        "PARSER_DOCUMENT_TYPE_UNSUPPORTED",
        "PARSER_TEXT_ENCODING_INVALID",
        "PARSER_TEXT_CODEPOINT_LIMIT",
        "PARSER_LINE_COUNT_LIMIT",
        "PARSER_LINE_SIZE_LIMIT",
        "PARSER_SOURCE_PROVENANCE_INVALID",
        "PARSER_SOURCE_INTEGRITY_INVALID",
        "PARSER_EVIDENCE_INVALID",
        "PARSER_VERSION_NOT_PENDING",
        "PARSER_EVIDENCE_ALREADY_EXISTS",
    ):
        reason = parser_promotion_worker._rejection_reason(DocumentParseRejected(code))
        assert reason == ParserOutcomeReason(code)


def test_every_rejection_code_raised_in_the_source_is_in_the_closed_set() -> None:
    package = Path(parser_promotion_worker.__file__).parent
    raised: set[str] = set()
    for module in (
        "markdown_parser.py",
        "parser_evidence_promotion.py",
        "parser_promotion_worker.py",
    ):
        raised |= set(
            re.findall(
                r'DocumentParseRejected\("([A-Z_]+)"\)',
                (package / module).read_text(encoding="utf-8"),
            )
        )
    assert raised
    assert raised <= set(parser_promotion_worker._REJECTION_REASONS)


def test_the_line_is_visible_under_the_lambda_text_logging_setup() -> None:
    """Text format, no application log level: root at WARNING, one handler."""

    class Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()  # level NOTSET, like the runtime's handler
            self.messages: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.messages.append(record.getMessage())

    root = logging.getLogger()
    capture = Capture()
    previous_level = root.level
    package = logging.getLogger("ai_qa_copilot_api")
    previous_package_level = package.level
    root.setLevel(logging.WARNING)
    package.setLevel(logging.NOTSET)
    root.addHandler(capture)
    try:
        run_worker, _, _, _ = worker()
        run_worker.run_once()
        # A logger without its own level is dropped at INFO, as parser.batch is.
        logging.getLogger("ai_qa_copilot_api.lambda_workers").info("probe-info")
    finally:
        root.removeHandler(capture)
        root.setLevel(previous_level)
        package.setLevel(previous_package_level)

    assert outcome_line("accepted", "none", sections=1, requirements="1") in (
        capture.messages
    )
    assert "probe-info" not in capture.messages
