from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import botocore.session
import pytest
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber
from fastapi.testclient import TestClient

from ai_qa_copilot_api import general_wakeup as wakeup_module
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.document_status import (
    DocumentStatus,
    DocumentStatusView,
    IndexingStatus,
)
from ai_qa_copilot_api.documents import DocumentIntakeState, ParserJobState
from ai_qa_copilot_api.general_wakeup import (
    GENERAL_QUEUE_URL_ENVIRONMENT_VARIABLE,
    GENERAL_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE,
    WAKEUP_DELAY_SECONDS,
    WAKEUP_MESSAGE_BODY,
    GeneralWakeup,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import Project


QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/example-general"
PROJECT_ID = UUID("00000000-0000-0000-0000-00000000a001")
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_aws_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        GENERAL_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE,
        GENERAL_QUEUE_URL_ENVIRONMENT_VARIABLE,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "missing-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "missing-creds"))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def unsigned_sqs_client() -> Any:
    return botocore.session.get_session().create_client(
        "sqs", region_name="us-east-1", config=Config(signature_version=UNSIGNED)
    )


@pytest.fixture
def stubbed() -> Iterator[tuple[Any, Stubber]]:
    client = unsigned_sqs_client()
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def expected_send() -> dict[str, Any]:
    return {
        "QueueUrl": QUEUE_URL,
        "MessageBody": WAKEUP_MESSAGE_BODY,
        "DelaySeconds": WAKEUP_DELAY_SECONDS,
    }


def view(status: DocumentStatus) -> DocumentStatusView:
    parsed = status is DocumentStatus.PARSED
    return DocumentStatusView(
        id=uuid4(),
        project_id=PROJECT_ID,
        document_id=uuid4(),
        filename="requirements.md",
        content_type="text/markdown",
        byte_size=10,
        outcome=DocumentIntakeState.QUARANTINED,
        rejection_code=None,
        status=status,
        parser_stage=ParserJobState.ACCEPTED if parsed else ParserJobState.QUEUED,
        indexing=IndexingStatus.INDEXING_NOT_ENABLED if parsed else None,
        created_at=NOW,
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- Flag and configuration ---------------------------------------------------


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {GENERAL_QUEUE_URL_ENVIRONMENT_VARIABLE: QUEUE_URL},
        {
            GENERAL_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE: "TRUE",
            GENERAL_QUEUE_URL_ENVIRONMENT_VARIABLE: QUEUE_URL,
        },
        {GENERAL_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE: "true"},
    ],
)
def test_wakeup_is_off_unless_flag_and_queue_are_set(environ: dict[str, str]) -> None:
    def forbidden() -> Any:
        raise AssertionError("a disabled wake-up must not create a client")

    wakeup = GeneralWakeup.from_environment(environ)
    wakeup._client_factory = forbidden  # noqa: SLF001 - prove nothing is created

    assert not wakeup.enabled
    assert wakeup.send() is False
    assert wakeup.notify_if_parsed_unindexed([view(DocumentStatus.PARSED)]) is False


def test_enabled_from_environment() -> None:
    wakeup = GeneralWakeup.from_environment(
        {
            GENERAL_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE: "true",
            GENERAL_QUEUE_URL_ENVIRONMENT_VARIABLE: QUEUE_URL,
        }
    )

    assert wakeup.enabled


def test_delay_must_fit_the_sqs_maximum() -> None:
    with pytest.raises(ValueError):
        GeneralWakeup(enabled=True, queue_url=QUEUE_URL, delay_seconds=901)
    assert WAKEUP_DELAY_SECONDS <= 900


# --- Sending ------------------------------------------------------------------


def test_flag_on_sends_exactly_one_delayed_fixed_message(
    stubbed: tuple[Any, Stubber],
) -> None:
    client, stubber = stubbed
    stubber.add_response("send_message", {"MessageId": "m-1"}, expected_send())
    wakeup = GeneralWakeup(enabled=True, queue_url=QUEUE_URL, client=client)

    assert wakeup.send() is True
    assert WAKEUP_MESSAGE_BODY == "wake-up"


def test_repeat_within_the_window_sends_nothing_then_resends_after(
    stubbed: tuple[Any, Stubber],
) -> None:
    client, stubber = stubbed
    stubber.add_response("send_message", {"MessageId": "m-1"}, expected_send())
    stubber.add_response("send_message", {"MessageId": "m-2"}, expected_send())
    clock = FakeClock()
    wakeup = GeneralWakeup(
        enabled=True, queue_url=QUEUE_URL, client=client, clock=clock
    )

    assert wakeup.send() is True
    clock.now += WAKEUP_DELAY_SECONDS - 1
    assert wakeup.send() is False
    clock.now += 2
    assert wakeup.send() is True


def test_hook_sends_only_for_parsed_unindexed_documents(
    stubbed: tuple[Any, Stubber],
) -> None:
    client, stubber = stubbed
    stubber.add_response("send_message", {"MessageId": "m-1"}, expected_send())
    wakeup = GeneralWakeup(enabled=True, queue_url=QUEUE_URL, client=client)

    assert wakeup.notify_if_parsed_unindexed([]) is False
    assert (
        wakeup.notify_if_parsed_unindexed(
            [view(DocumentStatus.PARSER_QUEUED), view(DocumentStatus.PARSING)]
        )
        is False
    )
    assert (
        wakeup.notify_if_parsed_unindexed(
            [view(DocumentStatus.QUARANTINED), view(DocumentStatus.PARSED)]
        )
        is True
    )


@pytest.mark.parametrize(
    "code", ["QueueDoesNotExist", "RequestThrottled", "AccessDenied", "KmsThrottled"]
)
def test_service_errors_never_raise(stubbed: tuple[Any, Stubber], code: str) -> None:
    client, stubber = stubbed
    stubber.add_client_error("send_message", service_error_code=code)
    wakeup = GeneralWakeup(enabled=True, queue_url=QUEUE_URL, client=client)

    assert wakeup.send() is False


class _RaisingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def send_message(self, **kwargs: Any) -> Mapping[str, Any]:
        raise self.error


@pytest.mark.parametrize(
    "error",
    [EndpointConnectionError(endpoint_url=QUEUE_URL), RuntimeError("unexpected")],
)
def test_transport_and_unexpected_errors_never_raise(error: Exception) -> None:
    wakeup = GeneralWakeup(
        enabled=True, queue_url=QUEUE_URL, client=_RaisingClient(error)
    )

    assert wakeup.send() is False


def test_client_creation_failure_never_raises() -> None:
    def broken_factory() -> Any:
        raise RuntimeError("no region")

    wakeup = GeneralWakeup(
        enabled=True, queue_url=QUEUE_URL, client_factory=broken_factory
    )

    assert wakeup.send() is False


def test_client_is_created_lazily_once(stubbed: tuple[Any, Stubber]) -> None:
    client, stubber = stubbed
    stubber.add_response("send_message", {"MessageId": "m-1"}, expected_send())
    created: list[Any] = []

    def factory() -> Any:
        created.append(client)
        return client

    wakeup = GeneralWakeup(enabled=True, queue_url=QUEUE_URL, client_factory=factory)
    assert created == []
    wakeup.send()
    wakeup.send()

    assert len(created) == 1


def test_default_client_uses_bounded_timeouts() -> None:
    client: Any = wakeup_module.default_sqs_client()

    assert client.meta.config.connect_timeout == 2
    assert client.meta.config.read_timeout == 3
    assert client.meta.region_name == "us-east-1"


# --- Status routes ------------------------------------------------------------


class FakeProjects:
    def get(self, project_id: UUID) -> Project | None:
        if project_id != PROJECT_ID:
            return None
        return Project(
            id=PROJECT_ID,
            name="Docs",
            description=None,
            created_at=NOW,
            archived_at=None,
        )


class FakeStatus:
    def __init__(self, documents: list[DocumentStatusView]) -> None:
        self.documents = documents

    def list_for_project(
        self, *, project_id: UUID, limit: int = 100
    ) -> tuple[DocumentStatusView, ...]:
        del project_id, limit
        return tuple(self.documents)

    def get_for_project(
        self, *, project_id: UUID, document_id: UUID
    ) -> DocumentStatusView | None:
        del project_id
        return next((item for item in self.documents if item.id == document_id), None)


class RecordingClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> Mapping[str, Any]:
        self.sent.append(kwargs)
        return {"MessageId": "m"}


def status_client(
    wakeup: GeneralWakeup | None, documents: list[DocumentStatusView]
) -> Any:
    application = create_app(
        AuthSettings(
            app_env=AppEnvironment.LOCAL, local_auth_bypass_enabled=True, cognito=None
        ),
        project_repository=FakeProjects(),  # type: ignore[arg-type]
        document_status_repository=FakeStatus(documents),
        general_wakeup=wakeup,
    )
    return TestClient(application), application


def test_status_read_with_parsed_document_sends_one_wakeup() -> None:
    client = RecordingClient()
    parsed = view(DocumentStatus.PARSED)
    http_client, _ = status_client(
        GeneralWakeup(enabled=True, queue_url=QUEUE_URL, client=client), [parsed]
    )

    with http_client as http:
        listed = http.get(f"/projects/{PROJECT_ID}/documents")
        detail = http.get(f"/projects/{PROJECT_ID}/documents/{parsed.id}")

    assert listed.status_code == detail.status_code == 200
    assert client.sent == [expected_send()]


def test_status_read_without_parsed_document_sends_nothing() -> None:
    client = RecordingClient()
    http_client, _ = status_client(
        GeneralWakeup(enabled=True, queue_url=QUEUE_URL, client=client),
        [view(DocumentStatus.PARSER_QUEUED)],
    )

    with http_client as http:
        response = http.get(f"/projects/{PROJECT_ID}/documents")

    assert response.status_code == 200
    assert client.sent == []


def test_send_failure_never_breaks_the_status_response() -> None:
    parsed = view(DocumentStatus.PARSED)
    http_client, _ = status_client(
        GeneralWakeup(
            enabled=True,
            queue_url=QUEUE_URL,
            client=_RaisingClient(RuntimeError("queue down")),
        ),
        [parsed],
    )

    with http_client as http:
        response = http.get(f"/projects/{PROJECT_ID}/documents/{parsed.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "parsed"


def test_default_composition_has_the_wakeup_off() -> None:
    http_client, application = status_client(None, [view(DocumentStatus.PARSED)])

    with http_client as http:
        response = http.get(f"/projects/{PROJECT_ID}/documents")

    assert response.status_code == 200
    assert isinstance(application.state.general_wakeup, GeneralWakeup)
    assert not application.state.general_wakeup.enabled
