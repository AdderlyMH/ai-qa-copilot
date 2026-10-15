from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
import logging
from pathlib import Path
import re
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_qa_copilot_api import claim_durations, general_wakeup, lambda_workers
from ai_qa_copilot_api.claim_durations import (
    DEFAULT_CLAIM_DURATION,
    INDEXING_CLAIM_DURATION_ENVIRONMENT_VARIABLE,
    PARSER_CLAIM_DURATION_ENVIRONMENT_VARIABLE,
    ClaimDurationConfigurationError,
    claim_duration_from_environment,
)
from ai_qa_copilot_api.database_engine import create_shared_engine
from ai_qa_copilot_api.documents import IndexingJobRecord, ParserJobRecord
from ai_qa_copilot_api.execution_jobs import ExecutionJobQueueUnavailable
from ai_qa_copilot_api.indexing import EmbeddingConfiguration
from ai_qa_copilot_api.indexing_job_claims import IndexingJobUnavailable
from ai_qa_copilot_api.ingestion import (
    DocumentIntakeUnavailable,
    InMemoryQuarantineStorage,
    SqlAlchemyDocumentIntakeRepository,
    UploadMetadata,
)
from ai_qa_copilot_api.lambda_workers import (
    SqsWorkerHandler,
    WorkerComposition,
    _ClaimFlag,
    build_executor_composition,
    build_general_composition,
    build_parser_composition,
)
from ai_qa_copilot_api.parser_queue import (
    ParserJob,
    ParserJobQueueUnavailable,
    SqlAlchemyParserJobQueue,
)
from ai_qa_copilot_api.parser_worker import ParserWorkerConfigurationError
from ai_qa_copilot_api.projects import Base, SqlAlchemyProjectRepository


RAW = b"# Checkout\nREQ-001: Quantity must be positive.\nREQ-002: Return status 201.\n"
HOSTILE_BODY = (
    '{"job_id": "00000000-0000-0000-0000-000000000000", '
    '"sql": "DROP TABLE parser_jobs", "secret": "hostile-body-marker-55"}'
)


def sqs_event(*message_ids: str, body: str = "wake-up") -> dict[str, Any]:
    return {
        "Records": [
            {
                "messageId": message_id,
                "receiptHandle": f"receipt-handle-marker-{message_id}",
                "body": body,
                "attributes": {"ApproximateReceiveCount": "1"},
                "messageAttributes": {},
                "md5OfBody": "0" * 32,
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:example",
                "awsRegion": "us-east-1",
            }
            for message_id in message_ids
        ]
    }


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "DATA_BUCKET_NAME",
        PARSER_CLAIM_DURATION_ENVIRONMENT_VARIABLE,
        INDEXING_CLAIM_DURATION_ENVIRONMENT_VARIABLE,
        "AI_QA_COPILOT_EXECUTION_WORKER_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


class Database:
    def __init__(self, path: Path) -> None:
        self.url = f"sqlite+pysqlite:///{path}"
        self.engine = create_engine(self.url)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.storage = InMemoryQuarantineStorage()
        self.project_id = (
            SqlAlchemyProjectRepository(self.sessions)
            .create(name="Workers", description=None)
            .id
        )

    def queue_parser_job(self, content: bytes = RAW) -> UUID:
        key = f"quarantine/{self.project_id}/{uuid4()}/raw"
        self.storage.put(
            key=key, content=BytesIO(content), content_type="text/markdown"
        )
        intake = SqlAlchemyDocumentIntakeRepository(self.sessions).create_quarantined(
            project_id=self.project_id,
            metadata=UploadMetadata("requirements.md", "text/markdown", "identity"),
            document_type="markdown",
            byte_size=len(content),
            content_sha256=sha256(content).hexdigest(),
            quarantine_key=key,
        )
        SqlAlchemyParserJobQueue(self.sessions).enqueue(
            ParserJob(document_intake_id=intake.id)
        )
        return intake.id

    def parser_states(self) -> dict[UUID, str]:
        with self.sessions() as session:
            return {
                row.document_intake_id: row.state
                for row in session.scalars(select(ParserJobRecord))
            }

    def indexing_states(self) -> list[str]:
        with self.sessions() as session:
            return [row.state for row in session.scalars(select(IndexingJobRecord))]


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(tmp_path / "workers.db")
    yield db
    db.engine.dispose()


class AnyTextEmbeddingAdapter:
    """No-network test adapter returning one fixed vector per text."""

    def embed(
        self, texts: Sequence[str], configuration: EmbeddingConfiguration
    ) -> Sequence[Sequence[float]]:
        configuration.validate()
        return tuple((0.1, 0.2, 0.3) for _ in texts)


def parser_environment(database: Database) -> dict[str, str]:
    return {"DATABASE_URL": database.url, "DATA_BUCKET_NAME": "example-bucket"}


def parser_handler(
    environ: dict[str, str],
    reader: Any,
    *,
    verifier: Callable[[], object] = lambda: None,
) -> SqsWorkerHandler:
    return SqsWorkerHandler(
        "parser",
        lambda: build_parser_composition(
            environ,
            runtime_verifier=verifier,
            reader_factory=lambda bucket: reader,
        ),
    )


# --- Claim duration configuration ---------------------------------------------


def test_unset_claim_duration_keeps_the_default() -> None:
    assert claim_duration_from_environment("X", {}) == DEFAULT_CLAIM_DURATION
    assert DEFAULT_CLAIM_DURATION == timedelta(seconds=60)


@pytest.mark.parametrize(("value", "seconds"), [("1", 1), ("360", 360), (" 90 ", 90)])
def test_valid_claim_duration(value: str, seconds: int) -> None:
    assert claim_duration_from_environment("X", {"X": value}) == timedelta(
        seconds=seconds
    )


@pytest.mark.parametrize("value", ["", "abc", "0", "-5", "1.5", "+9", "1e3", "٣"])
def test_invalid_claim_duration_is_rejected(value: str) -> None:
    with pytest.raises(ClaimDurationConfigurationError) as raised:
        claim_duration_from_environment("X", {"X": value})

    assert str(raised.value) == (
        "Claim duration must be a positive integer number of seconds"
    )


def test_absurd_claim_duration_is_rejected() -> None:
    with pytest.raises(ClaimDurationConfigurationError, match="3600") as raised:
        claim_duration_from_environment("X", {"X": "86400"})

    assert "86400" not in str(raised.value)


def test_builders_apply_the_configured_durations(database: Database) -> None:
    parser = build_parser_composition(
        {
            **parser_environment(database),
            PARSER_CLAIM_DURATION_ENVIRONMENT_VARIABLE: "75",
        },
        runtime_verifier=lambda: None,
        reader_factory=lambda bucket: database.storage,
    )
    general = build_general_composition(
        {
            "DATABASE_URL": database.url,
            INDEXING_CLAIM_DURATION_ENVIRONMENT_VARIABLE: "360",
        },
        embedding_adapter=AnyTextEmbeddingAdapter(),
        runtime_verifier=lambda: None,
    )

    assert parser.reap is not None and general.reap is not None
    assert parser.reap.__self__._duration == timedelta(seconds=75)  # type: ignore[attr-defined]
    assert general.reap.__self__._duration == timedelta(seconds=360)  # type: ignore[attr-defined]


def test_invalid_duration_fails_the_invocation_and_retries_the_build(
    database: Database,
) -> None:
    environ = {
        **parser_environment(database),
        PARSER_CLAIM_DURATION_ENVIRONMENT_VARIABLE: "never",
    }
    handler = parser_handler(environ, database.storage)

    with pytest.raises(ClaimDurationConfigurationError):
        handler(sqs_event("m1"), None)
    assert handler.composition is None

    del environ[PARSER_CLAIM_DURATION_ENVIRONMENT_VARIABLE]
    assert handler(sqs_event("m2"), None) == {"batchItemFailures": []}


# --- Parser handler -----------------------------------------------------------


def test_parser_empty_queue_is_a_no_op_success(database: Database) -> None:
    handler = parser_handler(parser_environment(database), database.storage)

    assert handler(sqs_event("m1"), None) == {"batchItemFailures": []}
    assert database.parser_states() == {}


def test_parser_successful_claim_reports_no_failure(database: Database) -> None:
    intake_id = database.queue_parser_job()
    handler = parser_handler(parser_environment(database), database.storage)

    response = handler(sqs_event("m1"), None)

    assert response == {"batchItemFailures": []}
    assert database.parser_states() == {intake_id: "accepted"}
    assert database.indexing_states() == ["queued"]


def test_parser_duplicate_message_is_a_no_op(database: Database) -> None:
    intake_id = database.queue_parser_job()
    handler = parser_handler(parser_environment(database), database.storage)

    first = handler(sqs_event("m1"), None)
    duplicate = handler(sqs_event("m1"), None)

    assert first == duplicate == {"batchItemFailures": []}
    assert database.parser_states() == {intake_id: "accepted"}


@pytest.mark.parametrize(
    "error", [DocumentIntakeUnavailable("storage"), RuntimeError("unexpected")]
)
def test_parser_error_after_claim_succeeds_with_terminal_state(
    database: Database, error: Exception
) -> None:
    intake_id = database.queue_parser_job()

    class FailingReader:
        def read(self, *, key: str) -> tuple[bytes, str]:
            del key
            raise error

    handler = parser_handler(parser_environment(database), FailingReader())

    response = handler(sqs_event("m1"), None)

    assert response == {"batchItemFailures": []}
    assert database.parser_states() == {intake_id: "failed"}


def test_parser_database_unavailable_before_claim_is_reported(
    tmp_path: Path,
) -> None:
    empty_url = f"sqlite+pysqlite:///{tmp_path / 'no-tables.db'}"
    handler = parser_handler(
        {"DATABASE_URL": empty_url, "DATA_BUCKET_NAME": "example-bucket"},
        InMemoryQuarantineStorage(),
    )

    response = handler(sqs_event("m1", "m2"), None)

    assert response == {
        "batchItemFailures": [{"itemIdentifier": "m1"}, {"itemIdentifier": "m2"}]
    }


@pytest.mark.parametrize(
    "environ",
    [{}, {"DATABASE_URL": "sqlite://"}, {"DATA_BUCKET_NAME": "example-bucket"}],
)
def test_parser_missing_configuration_fails_closed_without_claiming(
    database: Database, environ: dict[str, str]
) -> None:
    intake_id = database.queue_parser_job()
    handler = parser_handler(environ, database.storage)

    response = handler(sqs_event("m1"), None)

    assert response == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert database.parser_states() == {intake_id: "queued"}


def test_parser_runtime_check_failure_fails_the_invocation_without_claiming(
    database: Database,
) -> None:
    intake_id = database.queue_parser_job()

    def reject_runtime() -> None:
        raise ParserWorkerConfigurationError("Parser worker role is not restricted")

    handler = parser_handler(
        parser_environment(database), database.storage, verifier=reject_runtime
    )

    with pytest.raises(ParserWorkerConfigurationError):
        handler(sqs_event("m1"), None)
    assert database.parser_states() == {intake_id: "queued"}


def test_hostile_message_body_does_not_select_the_job(database: Database) -> None:
    oldest = database.queue_parser_job(RAW)
    newest = database.queue_parser_job(RAW + b"\n- Second requirement.\n")
    handler = parser_handler(parser_environment(database), database.storage)
    body = HOSTILE_BODY.replace("00000000-0000-0000-0000-000000000000", str(newest))

    response = handler(sqs_event("m1", body=body), None)

    assert response == {"batchItemFailures": []}
    assert database.parser_states() == {oldest: "accepted", newest: "queued"}


def test_expired_claims_are_terminalized_before_the_next_turn(
    database: Database,
) -> None:
    intake_id = database.queue_parser_job()
    with database.sessions.begin() as session:
        job = session.scalar(select(ParserJobRecord))
        assert job is not None
        job.created_at = job.created_at - timedelta(seconds=120)
        job.state = "claimed"
        job.claim_token = uuid4()
        job.claimed_at = job.created_at
        job.claim_expires_at = job.created_at + timedelta(seconds=1)
    handler = parser_handler(parser_environment(database), database.storage)

    response = handler(sqs_event("m1"), None)

    assert response == {"batchItemFailures": []}
    assert database.parser_states() == {intake_id: "failed"}


def test_handler_builds_dependencies_once_per_process(
    monkeypatch: pytest.MonkeyPatch, database: Database
) -> None:
    engines: list[Any] = []

    def counting_engine(url: str) -> Any:
        engine = create_shared_engine(url)
        engines.append(engine)
        return engine

    monkeypatch.setattr(lambda_workers, "create_shared_engine", counting_engine)
    database.queue_parser_job()
    handler = parser_handler(parser_environment(database), database.storage)

    handler(sqs_event("m1"), None)
    composition = handler.composition
    handler(sqs_event("m2"), None)

    assert len(engines) == 1
    assert handler.composition is composition


# --- Handler classification with scripted turns --------------------------------


def scripted_handler(outcomes: list[str]) -> tuple[SqsWorkerHandler, list[str]]:
    calls: list[str] = []
    flag = _ClaimFlag()

    def turn() -> object:
        outcome = outcomes[len(calls)]
        calls.append(outcome)
        if outcome == "pre_claim_unavailable":
            raise ParserJobQueueUnavailable("down")
        if outcome == "post_claim_unavailable":
            flag.claimed = True
            raise ParserJobQueueUnavailable("down after claim")
        if outcome == "post_claim_error":
            flag.claimed = True
            raise RuntimeError("worker bug after claim")
        return None

    composition = WorkerComposition(
        turn=turn, flag=flag, unavailable=ParserJobQueueUnavailable
    )
    return SqsWorkerHandler("scripted", lambda: composition), calls


def test_only_pre_claim_infrastructure_failures_are_reported() -> None:
    handler, calls = scripted_handler(
        [
            "ok",
            "pre_claim_unavailable",
            "post_claim_unavailable",
            "post_claim_error",
            "ok",
        ]
    )

    response = handler(sqs_event("a", "b", "c", "d", "e"), None)

    assert response == {"batchItemFailures": [{"itemIdentifier": "b"}]}
    assert len(calls) == 5


def test_unexpected_pre_claim_error_fails_the_whole_invocation() -> None:
    flag = _ClaimFlag()

    def turn() -> object:
        raise ValueError("misconfigured before any claim")

    handler = SqsWorkerHandler(
        "scripted",
        lambda: WorkerComposition(
            turn=turn, flag=flag, unavailable=ParserJobQueueUnavailable
        ),
    )

    with pytest.raises(ValueError):
        handler(sqs_event("a"), None)


@pytest.mark.parametrize(
    "event",
    [
        None,
        "Records",
        {},
        {"Records": "not-a-list"},
        {"Records": [None, 7, {"messageId": ""}, {"messageId": 5}, {"body": "x"}]},
    ],
)
def test_malformed_events_run_no_work_and_succeed(event: Any) -> None:
    handler, calls = scripted_handler(["ok"] * 5)

    assert handler(event, None) == {"batchItemFailures": []}
    assert calls == []


def test_malformed_records_are_skipped_and_valid_ones_run() -> None:
    handler, calls = scripted_handler(["pre_claim_unavailable"])
    event = {"Records": [{"body": "no id"}, {"messageId": "good", "body": "x"}]}

    assert handler(event, None) == {"batchItemFailures": [{"itemIdentifier": "good"}]}
    assert calls == ["pre_claim_unavailable"]


def test_logs_never_contain_bodies_or_receipt_handles(
    caplog: pytest.LogCaptureFixture, database: Database
) -> None:
    database.queue_parser_job()
    handler = parser_handler(parser_environment(database), database.storage)

    with caplog.at_level(logging.DEBUG, logger="ai_qa_copilot_api"):
        handler(sqs_event("m1", body=HOSTILE_BODY), None)

    assert "hostile-body-marker-55" not in caplog.text
    assert "receipt-handle-marker" not in caplog.text
    assert "parser.batch records=1 failures=0" in caplog.text


# --- General handler ----------------------------------------------------------


def test_general_without_an_embedding_adapter_claims_nothing(
    database: Database,
) -> None:
    database.queue_parser_job()
    parser_handler(parser_environment(database), database.storage)(
        sqs_event("p1"), None
    )
    handler = SqsWorkerHandler(
        "general",
        lambda: build_general_composition({"DATABASE_URL": database.url}),
    )

    assert handler(sqs_event("g1"), None) == {"batchItemFailures": []}
    assert handler.composition is not None and handler.composition.turn is None
    assert database.indexing_states() == ["queued"]


def test_general_indexes_a_parsed_document_with_an_adapter(
    database: Database,
) -> None:
    database.queue_parser_job()
    parser_handler(parser_environment(database), database.storage)(
        sqs_event("p1"), None
    )
    handler = SqsWorkerHandler(
        "general",
        lambda: build_general_composition(
            {"DATABASE_URL": database.url},
            embedding_adapter=AnyTextEmbeddingAdapter(),
            runtime_verifier=lambda: None,
        ),
    )

    first = handler(sqs_event("g1"), None)
    duplicate = handler(sqs_event("g2"), None)

    assert first == duplicate == {"batchItemFailures": []}
    assert database.indexing_states() == ["accepted"]


def test_general_unavailable_database_is_reported() -> None:
    handler = SqsWorkerHandler(
        "general",
        lambda: build_general_composition(
            {},
            embedding_adapter=AnyTextEmbeddingAdapter(),
            runtime_verifier=lambda: None,
        ),
    )

    assert handler(sqs_event("g1"), None) == {
        "batchItemFailures": [{"itemIdentifier": "g1"}]
    }
    assert handler.composition is not None
    assert handler.composition.unavailable is IndexingJobUnavailable


# --- Executor handler ---------------------------------------------------------


@pytest.mark.parametrize("flag_value", [None, "", "false", "TRUE", "1", "yes"])
def test_executor_disabled_claims_nothing(flag_value: str | None) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a disabled executor must not compose a worker")

    environ = {"DATABASE_URL": "sqlite://"}
    if flag_value is not None:
        environ["AI_QA_COPILOT_EXECUTION_WORKER_ENABLED"] = flag_value
    handler = SqsWorkerHandler(
        "executor", lambda: build_executor_composition(environ, compose=forbidden)
    )

    assert handler(sqs_event("x1"), None) == {"batchItemFailures": []}


def test_executor_enabled_without_database_is_reported() -> None:
    handler = SqsWorkerHandler(
        "executor",
        lambda: build_executor_composition(
            {"AI_QA_COPILOT_EXECUTION_WORKER_ENABLED": "true"}
        ),
    )

    assert handler(sqs_event("x1"), None) == {
        "batchItemFailures": [{"itemIdentifier": "x1"}]
    }
    assert handler.composition is not None
    assert handler.composition.unavailable is ExecutionJobQueueUnavailable


def test_executor_enabled_with_empty_queue_is_idle(database: Database) -> None:
    handler = SqsWorkerHandler(
        "executor",
        lambda: build_executor_composition(
            {
                "AI_QA_COPILOT_EXECUTION_WORKER_ENABLED": "true",
                "DATABASE_URL": database.url,
            }
        ),
    )

    assert handler(sqs_event("x1"), None) == {"batchItemFailures": []}


def test_executor_error_after_claim_is_not_retried(database: Database) -> None:
    class ClaimThenFail:
        def __init__(self, jobs: Any) -> None:
            self._jobs = jobs

        def run_once(self) -> object:
            self._jobs._flag.claimed = True
            raise RuntimeError("executor failed after consuming the approval")

    handler = SqsWorkerHandler(
        "executor",
        lambda: build_executor_composition(
            {
                "AI_QA_COPILOT_EXECUTION_WORKER_ENABLED": "true",
                "DATABASE_URL": database.url,
            },
            compose=lambda sessions, *, jobs: ClaimThenFail(jobs),
        ),
    )

    assert handler(sqs_event("x1"), None) == {"batchItemFailures": []}


# --- Module hygiene -----------------------------------------------------------


def test_module_level_handlers_build_nothing_at_import() -> None:
    for handler in (
        lambda_workers.parser_handler,
        lambda_workers.general_handler,
        lambda_workers.executor_handler,
    ):
        assert isinstance(handler, SqsWorkerHandler)


@pytest.mark.parametrize("module", [lambda_workers, general_wakeup, claim_durations])
def test_modules_contain_no_secret_like_strings(module: Any) -> None:
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert re.search(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b", source) is None
    for forbidden in (
        "aws_access_key_id",
        "aws_secret_access_key",
        "endpoint_url",
        "password",
        "print(",
        '["body"]',
        '.get("body")',
        "receiptHandle",
    ):
        assert forbidden not in source


def test_parser_reader_sees_only_the_claimed_key(database: Database) -> None:
    database.queue_parser_job()
    seen: list[str] = []

    class RecordingReader:
        def read(self, *, key: str) -> tuple[bytes, str]:
            seen.append(key)
            return database.storage.read(key=key)

    handler = parser_handler(parser_environment(database), RecordingReader())
    handler(sqs_event("m1", body="quarantine/other-project/raw"), None)

    assert len(seen) == 1
    assert seen[0].startswith(f"quarantine/{database.project_id}/")
