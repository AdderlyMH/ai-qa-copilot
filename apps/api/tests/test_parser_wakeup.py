from __future__ import annotations

from collections.abc import Generator, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import botocore.session
import pytest
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ReadTimeoutError
from botocore.stub import Stubber
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.document_status import (
    DocumentStatus,
    DocumentStatusView,
    SqlAlchemyDocumentStatusRepository,
)
from ai_qa_copilot_api.documents import DocumentIntakeState, ParserJobRecord
from ai_qa_copilot_api.general_wakeup import WAKEUP_MESSAGE_BODY
from ai_qa_copilot_api.ingestion import (
    InMemoryQuarantineStorage,
    SqlAlchemyDocumentIntakeRepository,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.parser_queue import SqlAlchemyParserJobQueue
from ai_qa_copilot_api.parser_wakeup import (
    PARSER_QUEUE_URL_ENVIRONMENT_VARIABLE,
    PARSER_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE,
    PARSER_WAKEUP_RESEND_INTERVAL_SECONDS,
    ParserWakeup,
)
from ai_qa_copilot_api.projects import Base, SqlAlchemyProjectRepository


QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/example-parser"
CONTENT = b"# Checkout\nREQ-001: Quantity must be positive.\nFILE-DATA-MARKER-77\n"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
EXPECTED_SEND = {"QueueUrl": QUEUE_URL, "MessageBody": "wake-up", "DelaySeconds": 0}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        PARSER_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE,
        PARSER_QUEUE_URL_ENVIRONMENT_VARIABLE,
        "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "missing-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "missing-creds"))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def stubbed() -> Iterator[tuple[Any, Stubber]]:
    client = botocore.session.get_session().create_client(
        "sqs", region_name="us-east-1", config=Config(signature_version=UNSIGNED)
    )
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


class RecordingClient:
    def __init__(self, on_send: Any = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self._on_send = on_send

    def send_message(self, **kwargs: Any) -> Mapping[str, Any]:
        if self._on_send is not None:
            self._on_send()
        self.sent.append(kwargs)
        return {"MessageId": "m"}


class RaisingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def send_message(self, **kwargs: Any) -> Mapping[str, Any]:
        raise self.error


def view(status: DocumentStatus) -> DocumentStatusView:
    return DocumentStatusView(
        id=uuid4(),
        project_id=uuid4(),
        document_id=uuid4(),
        filename="requirements.md",
        content_type="text/markdown",
        byte_size=10,
        outcome=DocumentIntakeState.QUARANTINED,
        rejection_code=None,
        status=status,
        parser_stage=None,
        indexing=None,
        created_at=NOW,
    )


# --- Sender -------------------------------------------------------------------


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {PARSER_QUEUE_URL_ENVIRONMENT_VARIABLE: QUEUE_URL},
        {
            PARSER_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE: "True",
            PARSER_QUEUE_URL_ENVIRONMENT_VARIABLE: QUEUE_URL,
        },
        {PARSER_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE: "true"},
        {
            PARSER_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE: "true",
            PARSER_QUEUE_URL_ENVIRONMENT_VARIABLE: "   ",
        },
    ],
)
def test_flag_off_or_missing_queue_sends_nothing(environ: dict[str, str]) -> None:
    def forbidden() -> Any:
        raise AssertionError("a disabled wake-up must not create a client")

    wakeup = ParserWakeup.from_environment(environ)
    wakeup._client_factory = forbidden  # noqa: SLF001 - prove nothing is created

    assert not wakeup.enabled
    assert wakeup.notify_upload_accepted() is False
    assert wakeup.notify_if_parser_queued([view(DocumentStatus.PARSER_QUEUED)]) is False


def test_flag_on_from_environment() -> None:
    wakeup = ParserWakeup.from_environment(
        {
            PARSER_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE: "true",
            PARSER_QUEUE_URL_ENVIRONMENT_VARIABLE: QUEUE_URL,
        }
    )

    assert wakeup.enabled


def test_upload_sends_exactly_one_immediate_fixed_message(
    stubbed: tuple[Any, Stubber],
) -> None:
    client, stubber = stubbed
    stubber.add_response("send_message", {"MessageId": "m-1"}, EXPECTED_SEND)

    assert ParserWakeup(
        enabled=True, queue_url=QUEUE_URL, client=client
    ).notify_upload_accepted()
    assert WAKEUP_MESSAGE_BODY == "wake-up"


def test_each_accepted_upload_gets_its_own_wakeup() -> None:
    client = RecordingClient()
    clock = FakeClock()
    wakeup = ParserWakeup(enabled=True, queue_url=QUEUE_URL, client=client, clock=clock)

    assert wakeup.notify_upload_accepted()
    assert wakeup.notify_upload_accepted()

    assert client.sent == [EXPECTED_SEND, EXPECTED_SEND]


def test_status_recovery_is_throttled_and_only_for_parser_queued() -> None:
    client = RecordingClient()
    clock = FakeClock()
    wakeup = ParserWakeup(enabled=True, queue_url=QUEUE_URL, client=client, clock=clock)

    assert not wakeup.notify_if_parser_queued(
        [view(DocumentStatus.PARSED), view(DocumentStatus.PARSING)]
    )
    assert wakeup.notify_if_parser_queued([view(DocumentStatus.PARSER_QUEUED)])
    clock.now += PARSER_WAKEUP_RESEND_INTERVAL_SECONDS - 1
    assert not wakeup.notify_if_parser_queued([view(DocumentStatus.PARSER_QUEUED)])
    clock.now += 2
    assert wakeup.notify_if_parser_queued([view(DocumentStatus.PARSER_QUEUED)])

    assert client.sent == [EXPECTED_SEND, EXPECTED_SEND]


@pytest.mark.parametrize(
    "code", ["QueueDoesNotExist", "RequestThrottled", "AccessDenied"]
)
def test_client_errors_never_raise(stubbed: tuple[Any, Stubber], code: str) -> None:
    client, stubber = stubbed
    stubber.add_client_error("send_message", service_error_code=code)

    assert (
        ParserWakeup(
            enabled=True, queue_url=QUEUE_URL, client=client
        ).notify_upload_accepted()
        is False
    )


def test_timeout_never_raises() -> None:
    wakeup = ParserWakeup(
        enabled=True,
        queue_url=QUEUE_URL,
        client=RaisingClient(ReadTimeoutError(endpoint_url=QUEUE_URL)),
    )

    assert wakeup.notify_upload_accepted() is False


def test_bad_client_factory_never_raises() -> None:
    def broken() -> Any:
        raise RuntimeError("no region")

    wakeup = ParserWakeup(enabled=True, queue_url=QUEUE_URL, client_factory=broken)

    assert wakeup.notify_upload_accepted() is False


# --- Through the upload route -------------------------------------------------


@pytest.fixture
def sessions(tmp_path: Path) -> Generator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'wakeup.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    engine.dispose()


def upload_app(sessions: sessionmaker[Session], wakeup: ParserWakeup | None) -> Any:
    return create_app(
        AuthSettings(
            app_env=AppEnvironment.LOCAL, local_auth_bypass_enabled=True, cognito=None
        ),
        project_repository=SqlAlchemyProjectRepository(sessions),
        document_intake_repository=SqlAlchemyDocumentIntakeRepository(sessions),
        quarantine_storage=InMemoryQuarantineStorage(),
        parser_job_queue=SqlAlchemyParserJobQueue(sessions),
        document_status_repository=SqlAlchemyDocumentStatusRepository(sessions),
        parser_wakeup=wakeup,
    )


def parser_job_count(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(ParserJobRecord)) or 0


def project(sessions: sessionmaker[Session]) -> UUID:
    return (
        SqlAlchemyProjectRepository(sessions).create(name="Docs", description=None).id
    )


def upload(
    http: TestClient, project_id: UUID, *, filename: str = "requirements.md"
) -> Any:
    return http.post(
        f"/projects/{project_id}/documents",
        content=CONTENT,
        headers={"X-Upload-Filename": filename, "Content-Type": "text/markdown"},
    )


def test_accepted_upload_sends_one_wakeup_after_the_job_is_committed(
    sessions: sessionmaker[Session],
) -> None:
    project_id = project(sessions)
    jobs_at_send: list[int] = []
    client = RecordingClient(
        on_send=lambda: jobs_at_send.append(parser_job_count(sessions))
    )

    with TestClient(
        upload_app(
            sessions, ParserWakeup(enabled=True, queue_url=QUEUE_URL, client=client)
        )
    ) as http:
        response = upload(http, project_id)

    assert response.status_code == 202
    assert client.sent == [EXPECTED_SEND]
    assert jobs_at_send == [1]
    serialized = repr(client.sent)
    for value in (
        str(project_id),
        response.json()["id"],
        "FILE-DATA-MARKER-77",
        "requirements.md",
    ):
        assert value not in serialized


def test_rejected_upload_sends_nothing(sessions: sessionmaker[Session]) -> None:
    project_id = project(sessions)
    client = RecordingClient()

    with TestClient(
        upload_app(
            sessions, ParserWakeup(enabled=True, queue_url=QUEUE_URL, client=client)
        )
    ) as http:
        response = upload(http, project_id, filename="tool.exe")

    assert response.status_code == 415
    assert client.sent == []


def test_send_failure_never_breaks_the_upload(sessions: sessionmaker[Session]) -> None:
    project_id = project(sessions)
    wakeup = ParserWakeup(
        enabled=True,
        queue_url=QUEUE_URL,
        client=RaisingClient(ReadTimeoutError(endpoint_url=QUEUE_URL)),
    )

    with TestClient(upload_app(sessions, wakeup)) as http:
        response = upload(http, project_id)

    assert response.status_code == 202
    assert parser_job_count(sessions) == 1


def test_status_read_re_sends_for_a_parser_queued_document(
    sessions: sessionmaker[Session],
) -> None:
    project_id = project(sessions)
    client = RecordingClient()
    clock = FakeClock()
    wakeup = ParserWakeup(enabled=True, queue_url=QUEUE_URL, client=client, clock=clock)

    with TestClient(upload_app(sessions, wakeup)) as http:
        upload(http, project_id)
        clock.now += PARSER_WAKEUP_RESEND_INTERVAL_SECONDS
        listed = http.get(f"/projects/{project_id}/documents")

    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "parser_queued"
    assert client.sent == [EXPECTED_SEND, EXPECTED_SEND]


def test_default_composition_has_the_parser_wakeup_off(
    sessions: sessionmaker[Session],
) -> None:
    project_id = project(sessions)
    application = upload_app(sessions, None)

    with TestClient(application) as http:
        response = upload(http, project_id)

    assert response.status_code == 202
    assert isinstance(application.state.parser_wakeup, ParserWakeup)
    assert not application.state.parser_wakeup.enabled
