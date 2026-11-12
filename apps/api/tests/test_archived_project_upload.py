"""Uploads to an archived project are refused before any byte is read."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.audit import (
    AuditResult,
    AuthorizationAuditEvent,
    AuthorizationAuditSink,
)
from ai_qa_copilot_api.auth import (
    AppEnvironment,
    AuthSettings,
    CognitoIdentity,
    CognitoSettings,
)
from ai_qa_copilot_api.document_status import SqlAlchemyDocumentStatusRepository
from ai_qa_copilot_api.documents import (
    DocumentIntakeRecord,
    DocumentRecord,
    ParserJobRecord,
)
from ai_qa_copilot_api.ingestion import (
    DocumentIntakeService,
    InMemoryQuarantineStorage,
    SqlAlchemyDocumentIntakeRepository,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.parser_queue import SqlAlchemyParserJobQueue
from ai_qa_copilot_api.parser_wakeup import ParserWakeup
from ai_qa_copilot_api.projects import Base, SqlAlchemyProjectRepository


ISSUER = "https://cognito-idp.example.com/us-east-1_example"
CLIENT_ID = "example-client"
OWNER_SUBJECT = "owner-subject"
QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/parser.invalid"
MARKDOWN = b"# Requirements\n\nThe API must reject unauthenticated requests.\n"
BEARER = {"Authorization": "Bearer valid-token"}
ARCHIVED_BODY = {
    "detail": {
        "code": "PROJECT_ARCHIVED",
        "message": "Project is archived",
        "retryable": False,
    }
}


class RecordingAuditSink(AuthorizationAuditSink):
    def __init__(self) -> None:
        self.events: list[AuthorizationAuditEvent] = []

    def record(self, event: AuthorizationAuditEvent) -> None:
        self.events.append(event)


class StaticTokenValidator:
    def __init__(self, subject: str) -> None:
        self._identity = CognitoIdentity(issuer=ISSUER, subject=subject)

    def validate(self, token: str) -> CognitoIdentity:
        del token
        return self._identity


class RecordingStorage(InMemoryQuarantineStorage):
    def __init__(self) -> None:
        super().__init__()
        self.puts = 0

    def put(self, *, key: str, content: BinaryIO, content_type: str) -> None:
        self.puts += 1
        super().put(key=key, content=content, content_type=content_type)


class RecordingSqsClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> Mapping[str, Any]:
        self.sent.append(kwargs)
        return {"MessageId": "m"}


@dataclass
class Harness:
    http: TestClient
    sessions: sessionmaker[Session]
    audit: RecordingAuditSink
    storage: RecordingStorage
    sqs: RecordingSqsClient

    def count(self, record: type[Base]) -> int:
        with self.sessions() as session:
            return session.scalar(select(func.count()).select_from(record)) or 0

    def upload(self, project_id: UUID, *, filename: str = "requirements.md") -> Any:
        return self.http.post(
            f"/projects/{project_id}/documents",
            content=MARKDOWN,
            headers={
                **BEARER,
                "X-Upload-Filename": filename,
                "Content-Type": "text/markdown",
            },
        )


@pytest.fixture
def sessions(tmp_path: Path) -> Generator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'archived.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    engine.dispose()


def build(sessions: sessionmaker[Session], subject: str) -> Generator[Harness]:
    audit = RecordingAuditSink()
    storage = RecordingStorage()
    sqs = RecordingSqsClient()
    application = create_app(
        AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=CognitoSettings(
                issuer=ISSUER, client_id=CLIENT_ID, owner_subject=OWNER_SUBJECT
            ),
        ),
        token_validator=StaticTokenValidator(subject),
        project_repository=SqlAlchemyProjectRepository(sessions),
        document_intake_repository=SqlAlchemyDocumentIntakeRepository(sessions),
        quarantine_storage=storage,
        parser_job_queue=SqlAlchemyParserJobQueue(sessions),
        document_status_repository=SqlAlchemyDocumentStatusRepository(sessions),
        parser_wakeup=ParserWakeup(enabled=True, queue_url=QUEUE_URL, client=sqs),
        authorization_audit_sink=audit,
    )
    with TestClient(application) as http:
        yield Harness(http, sessions, audit, storage, sqs)


@pytest.fixture
def owner(sessions: sessionmaker[Session]) -> Generator[Harness]:
    yield from build(sessions, OWNER_SUBJECT)


@pytest.fixture
def stranger(sessions: sessionmaker[Session]) -> Generator[Harness]:
    yield from build(sessions, "non-owner-subject")


def create_project(sessions: sessionmaker[Session], *, archived: bool) -> UUID:
    repository = SqlAlchemyProjectRepository(sessions)
    project = repository.create(name="Docs", description=None)
    if archived:
        assert repository.archive(project.id) is not None
    return project.id


def assert_nothing_stored(harness: Harness) -> None:
    for record in (DocumentIntakeRecord, DocumentRecord, ParserJobRecord):
        assert harness.count(record) == 0, record.__name__
    assert harness.storage.puts == 0
    assert harness.storage.objects == {}
    assert harness.sqs.sent == []


# Archived


def test_archived_project_upload_is_refused_with_the_structured_409(
    owner: Harness, sessions: sessionmaker[Session]
) -> None:
    project_id = create_project(sessions, archived=True)

    response = owner.upload(project_id)

    assert response.status_code == 409
    assert response.json() == ARCHIVED_BODY
    assert UUID(response.headers["X-Correlation-ID"])
    assert_nothing_stored(owner)


def test_archived_project_upload_never_reaches_the_intake_service(
    owner: Harness, sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = create_project(sessions, archived=True)

    async def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the request stream must not be read")

    monkeypatch.setattr(DocumentIntakeService, "receive", refuse)

    assert owner.upload(project_id).status_code == 409


def test_archived_refusal_audits_like_any_other_rejected_upload(
    owner: Harness, sessions: sessionmaker[Session]
) -> None:
    archived = owner.upload(create_project(sessions, archived=True))
    archived_events = list(owner.audit.events)
    owner.audit.events.clear()
    rejected = owner.upload(
        create_project(sessions, archived=False), filename="requirements.exe"
    )

    assert archived.status_code == 409
    assert rejected.status_code == 415
    assert [(event.action, event.result) for event in archived_events] == [
        (event.action, event.result) for event in owner.audit.events
    ]
    assert [event.result for event in archived_events] == [AuditResult.ALLOWED]
    assert (
        str(archived_events[0].correlation_id) == archived.headers["X-Correlation-ID"]
    )


# Active and unknown


def test_active_project_upload_is_unaffected(
    owner: Harness, sessions: sessionmaker[Session]
) -> None:
    project_id = create_project(sessions, archived=False)

    response = owner.upload(project_id)

    assert response.status_code == 202
    assert response.json()["state"] == "quarantined"
    assert owner.count(DocumentIntakeRecord) == 1
    assert owner.count(ParserJobRecord) == 1
    assert owner.storage.puts == 1
    assert len(owner.sqs.sent) == 1


def test_unknown_project_is_still_404(owner: Harness) -> None:
    response = owner.upload(uuid4())

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}
    assert_nothing_stored(owner)


# Authorization first


@pytest.mark.parametrize("archived", [True, False])
def test_non_owner_is_denied_without_learning_the_archive_state(
    stranger: Harness, sessions: sessionmaker[Session], archived: bool
) -> None:
    response = stranger.upload(create_project(sessions, archived=archived))

    assert response.status_code == 403
    assert response.json() == {"detail": "Owner access required"}
    assert "archived" not in response.text.lower()
    assert [event.result for event in stranger.audit.events] == [AuditResult.DENIED]
    assert_nothing_stored(stranger)


@pytest.mark.parametrize("archived", [True, False])
def test_unauthenticated_upload_is_401_whatever_the_archive_state(
    owner: Harness, sessions: sessionmaker[Session], archived: bool
) -> None:
    response = owner.http.post(
        f"/projects/{create_project(sessions, archived=archived)}/documents",
        content=MARKDOWN,
        headers={"X-Upload-Filename": "a.md", "Content-Type": "text/markdown"},
    )

    assert response.status_code == 401
    assert "archived" not in response.text.lower()
    assert_nothing_stored(owner)


# Read routes


def test_document_list_and_status_still_work_after_archiving(
    owner: Harness, sessions: sessionmaker[Session]
) -> None:
    project_id = create_project(sessions, archived=False)
    accepted = owner.upload(project_id)
    assert accepted.status_code == 202
    assert SqlAlchemyProjectRepository(sessions).archive(project_id) is not None
    intake_id = accepted.json()["id"]

    listed = owner.http.get(f"/projects/{project_id}/documents", headers=BEARER)
    single = owner.http.get(
        f"/projects/{project_id}/documents/{intake_id}", headers=BEARER
    )

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [intake_id]
    assert single.status_code == 200
    assert single.json()["id"] == intake_id
    assert owner.upload(project_id).status_code == 409
    assert owner.count(DocumentIntakeRecord) == 1
