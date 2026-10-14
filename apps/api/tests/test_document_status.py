from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api import s3_quarantine
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
from ai_qa_copilot_api.document_status import (
    DOCUMENT_STATUS_LIST_LIMIT,
    DocumentStatus,
    DocumentStatusUnavailable,
    DocumentStatusView,
    IndexingStatus,
    SqlAlchemyDocumentStatusRepository,
    UnavailableDocumentStatusRepository,
    derive_document_status,
)
from ai_qa_copilot_api.documents import (
    DocumentIntakeRecord,
    DocumentIntakeState,
    ParserJobRecord,
    ParserJobState,
)
from ai_qa_copilot_api.ingestion import (
    DOCUMENT_INTAKE_UNAVAILABLE_DETAIL,
    DOCUMENT_UPLOAD_MAX_BYTES_ENVIRONMENT_VARIABLE,
    MAX_RAW_UPLOAD_BYTES,
    InMemoryQuarantineStorage,
    SqlAlchemyDocumentIntakeRepository,
    UploadPolicy,
    UploadPolicyConfigurationError,
    upload_policy_from_environment,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.parser_queue import SqlAlchemyParserJobQueue
from ai_qa_copilot_api.projects import Base, SqlAlchemyProjectRepository
from ai_qa_copilot_api.s3_quarantine import (
    DATA_BUCKET_ENVIRONMENT_VARIABLE,
    S3QuarantineStorage,
)


ISSUER = "https://cognito-idp.example.com/us-east-1_example"
CLIENT_ID = "example-client"
OWNER_SUBJECT = "owner-subject"
MARKDOWN = b"# Requirements\n\nThe API must reject unauthenticated requests.\n"
EXPECTED_FIELDS = {
    "id",
    "project_id",
    "document_id",
    "filename",
    "content_type",
    "byte_size",
    "outcome",
    "rejection_code",
    "status",
    "parser_stage",
    "indexing",
    "created_at",
}
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


class RecordingAuditSink(AuthorizationAuditSink):
    def __init__(self) -> None:
        self.events: list[AuthorizationAuditEvent] = []

    def record(self, event: AuthorizationAuditEvent) -> None:
        self.events.append(event)


class StaticTokenValidator:
    def __init__(self, identity: CognitoIdentity) -> None:
        self._identity = identity

    def validate(self, token: str) -> CognitoIdentity:
        del token
        return self._identity


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


def cognito_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=False,
        cognito=CognitoSettings(
            issuer=ISSUER, client_id=CLIENT_ID, owner_subject=OWNER_SUBJECT
        ),
    )


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        DATA_BUCKET_ENVIRONMENT_VARIABLE,
        DOCUMENT_UPLOAD_MAX_BYTES_ENVIRONMENT_VARIABLE,
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sessions(tmp_path: Path) -> Generator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'status.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    engine.dispose()


def status_app(
    sessions: sessionmaker[Session],
    *,
    audit_sink: RecordingAuditSink | None = None,
    auth_settings: AuthSettings | None = None,
    token_validator: StaticTokenValidator | None = None,
    status_repository: Any = None,
    policy: UploadPolicy | None = None,
) -> Any:
    return create_app(
        auth_settings or local_bypass_settings(),
        token_validator=token_validator,
        project_repository=SqlAlchemyProjectRepository(sessions),
        document_intake_repository=SqlAlchemyDocumentIntakeRepository(sessions),
        quarantine_storage=InMemoryQuarantineStorage(),
        parser_job_queue=SqlAlchemyParserJobQueue(sessions),
        document_intake_policy=policy,
        document_status_repository=(
            status_repository
            if status_repository is not None
            else SqlAlchemyDocumentStatusRepository(sessions)
        ),
        authorization_audit_sink=audit_sink or RecordingAuditSink(),
    )


def create_project(sessions: sessionmaker[Session], name: str = "Demo") -> UUID:
    return SqlAlchemyProjectRepository(sessions).create(name=name, description=None).id


def upload(http: TestClient, project_id: UUID, content: bytes, name: str) -> Any:
    return http.post(
        f"/projects/{project_id}/documents",
        content=content,
        headers={"X-Upload-Filename": name, "Content-Type": "text/markdown"},
    )


def set_parser_state(
    sessions: sessionmaker[Session], intake_id: UUID, state: ParserJobState | None
) -> None:
    with sessions.begin() as session:
        job = session.scalar(
            select(ParserJobRecord).where(
                ParserJobRecord.document_intake_id == intake_id
            )
        )
        assert job is not None
        if state is None:
            session.delete(job)
            return
        if state is ParserJobState.QUEUED:
            return
        job.state = state.value
        job.claim_token = uuid4()
        job.claimed_at = job.created_at + timedelta(seconds=1)
        job.claim_expires_at = job.created_at + timedelta(seconds=120)
        if state is not ParserJobState.CLAIMED:
            job.completed_at = job.created_at + timedelta(seconds=2)
        if state is ParserJobState.REJECTED:
            job.failure_code = "PARSER_DOCUMENT_REJECTED"
        if state is ParserJobState.FAILED:
            job.failure_code = "PARSER_WORKER_FAILED"


def insert_rejection(
    sessions: sessionmaker[Session], project_id: UUID, created_at: datetime
) -> UUID:
    intake_id = uuid4()
    with sessions.begin() as session:
        session.add(
            DocumentIntakeRecord(
                id=intake_id,
                project_id=project_id,
                document_id=None,
                document_version_id=None,
                state=DocumentIntakeState.REJECTED.value,
                quarantine_key=None,
                original_filename="notes.exe",
                declared_content_type="application/octet-stream",
                byte_size=0,
                content_sha256=None,
                rejection_code="UPLOAD_TYPE_UNSUPPORTED",
                created_at=created_at,
            )
        )
    return intake_id


# --- Upload cap configuration -------------------------------------------------


def test_unset_cap_keeps_the_product_default() -> None:
    assert upload_policy_from_environment({}) == UploadPolicy()
    assert UploadPolicy().max_raw_bytes == MAX_RAW_UPLOAD_BYTES


@pytest.mark.parametrize("value", ["1", "3145728", str(MAX_RAW_UPLOAD_BYTES), " 2048 "])
def test_valid_cap_is_applied(value: str) -> None:
    policy = upload_policy_from_environment(
        {DOCUMENT_UPLOAD_MAX_BYTES_ENVIRONMENT_VARIABLE: value}
    )

    assert policy.max_raw_bytes == int(value)
    assert policy.max_files_per_project == UploadPolicy().max_files_per_project
    assert (
        policy.max_total_bytes_per_project == UploadPolicy().max_total_bytes_per_project
    )


@pytest.mark.parametrize(
    "value", ["", "  ", "abc", "1.5", "-1", "0", "+5", "1e6", "0x10", "1_000", "٣"]
)
def test_invalid_cap_is_rejected_with_a_fixed_message(value: str) -> None:
    with pytest.raises(UploadPolicyConfigurationError) as raised:
        upload_policy_from_environment(
            {DOCUMENT_UPLOAD_MAX_BYTES_ENVIRONMENT_VARIABLE: value}
        )

    assert str(raised.value) == (
        "DOCUMENT_UPLOAD_MAX_BYTES must be a positive integer number of bytes"
    )


def test_cap_above_the_hard_maximum_is_rejected() -> None:
    with pytest.raises(UploadPolicyConfigurationError) as raised:
        upload_policy_from_environment(
            {
                DOCUMENT_UPLOAD_MAX_BYTES_ENVIRONMENT_VARIABLE: str(
                    MAX_RAW_UPLOAD_BYTES + 1
                )
            }
        )

    assert str(raised.value) == (
        "DOCUMENT_UPLOAD_MAX_BYTES must not exceed the hard maximum upload size"
    )
    assert str(MAX_RAW_UPLOAD_BYTES + 1) not in str(raised.value)


def test_invalid_cap_stops_application_startup(
    monkeypatch: pytest.MonkeyPatch, sessions: sessionmaker[Session]
) -> None:
    monkeypatch.setenv(DOCUMENT_UPLOAD_MAX_BYTES_ENVIRONMENT_VARIABLE, "lots")

    with pytest.raises(UploadPolicyConfigurationError):
        with TestClient(status_app(sessions)):
            pass


def test_environment_cap_is_enforced_just_under_and_just_over(
    monkeypatch: pytest.MonkeyPatch, sessions: sessionmaker[Session]
) -> None:
    monkeypatch.setenv(DOCUMENT_UPLOAD_MAX_BYTES_ENVIRONMENT_VARIABLE, "16")
    project_id = create_project(sessions)

    with TestClient(status_app(sessions)) as http:
        at_cap = upload(http, project_id, b"a" * 16, "at-cap.md")
        over_declared = upload(http, project_id, b"b" * 17, "over.md")
        over_streamed = http.post(
            f"/projects/{project_id}/documents",
            content=iter([b"c" * 10, b"c" * 7]),
            headers={"X-Upload-Filename": "stream.md", "Content-Type": "text/markdown"},
        )

    assert at_cap.status_code == 202
    for response in (over_declared, over_streamed):
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "UPLOAD_SIZE_LIMIT"
    assert "content-length" not in {
        name.lower() for name in over_streamed.request.headers
    }


def test_injected_policy_still_wins_over_the_environment(
    monkeypatch: pytest.MonkeyPatch, sessions: sessionmaker[Session]
) -> None:
    monkeypatch.setenv(DOCUMENT_UPLOAD_MAX_BYTES_ENVIRONMENT_VARIABLE, "4")
    project_id = create_project(sessions)

    with TestClient(status_app(sessions, policy=UploadPolicy())) as http:
        response = upload(http, project_id, MARKDOWN, "requirements.md")

    assert response.status_code == 202


def test_production_s3_storage_uses_the_configured_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden() -> Any:
        raise AssertionError("composition must not create an S3 client")

    monkeypatch.setattr(s3_quarantine, "default_s3_client", forbidden)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv(DATA_BUCKET_ENVIRONMENT_VARIABLE, "example-bucket")
    monkeypatch.setenv(DOCUMENT_UPLOAD_MAX_BYTES_ENVIRONMENT_VARIABLE, "3145728")
    application = create_app(local_bypass_settings())

    with TestClient(application):
        service = application.state.document_intake_service
        storage = service._storage  # noqa: SLF001 - composition assertion
        status_repository = application.state.document_status_repository

        assert isinstance(storage, S3QuarantineStorage)
        assert storage._max_object_bytes == 3145728  # noqa: SLF001
        assert service._policy.max_raw_bytes == 3145728  # noqa: SLF001
        assert isinstance(status_repository, SqlAlchemyDocumentStatusRepository)
        assert (
            status_repository._session_factory.kw["bind"]  # noqa: SLF001
            is application.state.database_engine
        )


def test_status_defaults_fail_closed_without_a_database(
    sessions: sessionmaker[Session],
) -> None:
    project_id = create_project(sessions)
    application = create_app(
        local_bypass_settings(),
        project_repository=SqlAlchemyProjectRepository(sessions),
    )

    with TestClient(application) as http:
        response = http.get(f"/projects/{project_id}/documents")

    assert isinstance(
        application.state.document_status_repository,
        UnavailableDocumentStatusRepository,
    )
    assert response.status_code == 503
    assert response.json() == {"detail": DOCUMENT_INTAKE_UNAVAILABLE_DETAIL}


# --- Derived status -----------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "stage", "expected"),
    [
        (DocumentIntakeState.REJECTED, None, DocumentStatus.REJECTED),
        (DocumentIntakeState.QUARANTINED, None, DocumentStatus.QUARANTINED),
        (
            DocumentIntakeState.QUARANTINED,
            ParserJobState.QUEUED,
            DocumentStatus.PARSER_QUEUED,
        ),
        (
            DocumentIntakeState.QUARANTINED,
            ParserJobState.CLAIMED,
            DocumentStatus.PARSING,
        ),
        (
            DocumentIntakeState.QUARANTINED,
            ParserJobState.ACCEPTED,
            DocumentStatus.PARSED,
        ),
        (
            DocumentIntakeState.QUARANTINED,
            ParserJobState.REJECTED,
            DocumentStatus.PARSE_FAILED,
        ),
        (
            DocumentIntakeState.QUARANTINED,
            ParserJobState.FAILED,
            DocumentStatus.PARSE_FAILED,
        ),
    ],
)
def test_every_status_derivation(
    outcome: DocumentIntakeState,
    stage: ParserJobState | None,
    expected: DocumentStatus,
) -> None:
    assert derive_document_status(outcome, stage) is expected


def test_status_enum_is_closed() -> None:
    assert {item.value for item in DocumentStatus} == {
        "rejected",
        "quarantined",
        "parser_queued",
        "parsing",
        "parsed",
        "parse_failed",
    }
    assert {item.value for item in IndexingStatus} == {"indexing_not_enabled"}


def test_rejected_upload_with_a_parser_job_is_inconsistent() -> None:
    with pytest.raises(ValueError):
        derive_document_status(DocumentIntakeState.REJECTED, ParserJobState.QUEUED)


@pytest.mark.parametrize(
    ("parser_state", "expected_status", "expected_indexing"),
    [
        (None, "quarantined", None),
        (ParserJobState.QUEUED, "parser_queued", None),
        (ParserJobState.CLAIMED, "parsing", None),
        (ParserJobState.ACCEPTED, "parsed", "indexing_not_enabled"),
        (ParserJobState.REJECTED, "parse_failed", None),
        (ParserJobState.FAILED, "parse_failed", None),
    ],
)
def test_detail_route_reports_each_parser_derived_status(
    sessions: sessionmaker[Session],
    parser_state: ParserJobState | None,
    expected_status: str,
    expected_indexing: str | None,
) -> None:
    project_id = create_project(sessions)

    with TestClient(status_app(sessions)) as http:
        uploaded = upload(http, project_id, MARKDOWN, "requirements.md")
        intake_id = UUID(uploaded.json()["id"])
        set_parser_state(sessions, intake_id, parser_state)
        response = http.get(f"/projects/{project_id}/documents/{intake_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == expected_status
    assert body["parser_stage"] == (
        parser_state.value if parser_state is not None else None
    )
    assert body["indexing"] == expected_indexing
    assert body["outcome"] == "quarantined"
    assert body["filename"] == "requirements.md"
    assert body["content_type"] == "text/markdown"
    assert body["byte_size"] == len(MARKDOWN)
    assert body["document_id"] == uploaded.json()["document_id"]


def test_rejected_upload_is_listed_with_its_rejection_code(
    sessions: sessionmaker[Session],
) -> None:
    project_id = create_project(sessions)

    with TestClient(status_app(sessions)) as http:
        rejected = http.post(
            f"/projects/{project_id}/documents",
            content=b"MZ",
            headers={"X-Upload-Filename": "tool.exe", "Content-Type": "text/plain"},
        )
        listed = http.get(f"/projects/{project_id}/documents")

    assert rejected.status_code == 415
    [item] = listed.json()
    assert item["status"] == "rejected"
    assert item["outcome"] == "rejected"
    assert item["rejection_code"] == "UPLOAD_TYPE_UNSUPPORTED"
    assert item["document_id"] is None
    assert item["parser_stage"] is None


# --- Response safety ----------------------------------------------------------


def test_responses_never_expose_storage_keys_buckets_or_hashes(
    sessions: sessionmaker[Session],
) -> None:
    project_id = create_project(sessions)

    with TestClient(status_app(sessions)) as http:
        uploaded = upload(http, project_id, MARKDOWN, "requirements.md")
        intake_id = uploaded.json()["id"]
        listed = http.get(f"/projects/{project_id}/documents")
        detail = http.get(f"/projects/{project_id}/documents/{intake_id}")

    with sessions() as session:
        record = session.get(DocumentIntakeRecord, UUID(intake_id))
        assert record is not None and record.quarantine_key is not None
        secrets = (record.quarantine_key, record.content_sha256)
    for response in (listed, detail):
        assert response.status_code == 200
        for secret in secrets:
            assert secret is not None and secret not in response.text
        for forbidden in ("quarantine/", "sha256", "bucket", "storage", "key"):
            assert forbidden not in response.text.lower()
    assert set(listed.json()[0]) == EXPECTED_FIELDS
    assert set(detail.json()) == EXPECTED_FIELDS


def test_view_type_carries_no_storage_or_hash_field() -> None:
    fields = set(DocumentStatusView.__dataclass_fields__)

    assert fields == EXPECTED_FIELDS


# --- Ordering and bounds ------------------------------------------------------


def test_list_is_newest_first_and_bounded(sessions: sessionmaker[Session]) -> None:
    project_id = create_project(sessions)
    inserted = [
        insert_rejection(sessions, project_id, NOW + timedelta(seconds=index))
        for index in range(DOCUMENT_STATUS_LIST_LIMIT + 5)
    ]

    with TestClient(status_app(sessions)) as http:
        response = http.get(f"/projects/{project_id}/documents")

    ids = [UUID(item["id"]) for item in response.json()]
    assert len(ids) == DOCUMENT_STATUS_LIST_LIMIT
    assert ids == list(reversed(inserted))[:DOCUMENT_STATUS_LIST_LIMIT]


def test_repository_limit_cannot_exceed_the_hard_bound(
    sessions: sessionmaker[Session],
) -> None:
    project_id = create_project(sessions)
    for index in range(DOCUMENT_STATUS_LIST_LIMIT + 1):
        insert_rejection(sessions, project_id, NOW + timedelta(seconds=index))
    repository = SqlAlchemyDocumentStatusRepository(sessions)

    assert (
        len(repository.list_for_project(project_id=project_id, limit=10_000))
        == DOCUMENT_STATUS_LIST_LIMIT
    )
    assert len(repository.list_for_project(project_id=project_id, limit=0)) == 1


def test_list_is_scoped_to_one_project(sessions: sessionmaker[Session]) -> None:
    project_id = create_project(sessions, "One")
    other_project_id = create_project(sessions, "Two")
    insert_rejection(sessions, other_project_id, NOW)

    with TestClient(status_app(sessions)) as http:
        response = http.get(f"/projects/{project_id}/documents")

    assert response.status_code == 200
    assert response.json() == []


# --- Not found, authorization and audit ---------------------------------------


def test_foreign_and_missing_documents_get_the_identical_404(
    sessions: sessionmaker[Session],
) -> None:
    project_id = create_project(sessions, "One")
    other_project_id = create_project(sessions, "Two")
    foreign_id = insert_rejection(sessions, other_project_id, NOW)

    with TestClient(status_app(sessions)) as http:
        foreign = http.get(f"/projects/{project_id}/documents/{foreign_id}")
        missing = http.get(f"/projects/{project_id}/documents/{uuid4()}")

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Document not found"}


def test_missing_project_is_hidden_for_list_and_detail(
    sessions: sessionmaker[Session],
) -> None:
    unknown_project = uuid4()

    with TestClient(status_app(sessions)) as http:
        listed = http.get(f"/projects/{unknown_project}/documents")
        detail = http.get(f"/projects/{unknown_project}/documents/{uuid4()}")

    for response in (listed, detail):
        assert response.status_code == 404
        assert response.json() == {"detail": "Project not found"}


def test_owner_reads_are_audited_with_the_response_correlation_id(
    sessions: sessionmaker[Session],
) -> None:
    project_id = create_project(sessions)
    sink = RecordingAuditSink()
    owner = StaticTokenValidator(CognitoIdentity(issuer=ISSUER, subject=OWNER_SUBJECT))

    with TestClient(
        status_app(
            sessions,
            audit_sink=sink,
            auth_settings=cognito_settings(),
            token_validator=owner,
        )
    ) as http:
        response = http.get(
            f"/projects/{project_id}/documents",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    [event] = sink.events
    assert event.result is AuditResult.ALLOWED
    assert event.action == "project.read"
    assert str(event.correlation_id) == response.headers["X-Correlation-ID"]


def test_non_owner_is_denied_and_audited(sessions: sessionmaker[Session]) -> None:
    project_id = create_project(sessions)
    sink = RecordingAuditSink()
    stranger = StaticTokenValidator(
        CognitoIdentity(issuer=ISSUER, subject="non-owner-subject")
    )

    with TestClient(
        status_app(
            sessions,
            audit_sink=sink,
            auth_settings=cognito_settings(),
            token_validator=stranger,
        )
    ) as http:
        responses = [
            http.get(path, headers={"Authorization": "Bearer valid-token"})
            for path in (
                f"/projects/{project_id}/documents",
                f"/projects/{project_id}/documents/{uuid4()}",
            )
        ]

    for response in responses:
        assert response.status_code == 403
        assert response.json() == {"detail": "Owner access required"}
    assert [event.result for event in sink.events] == [AuditResult.DENIED] * 2


def test_guest_without_credentials_is_denied_and_audited(
    sessions: sessionmaker[Session],
) -> None:
    project_id = create_project(sessions)
    sink = RecordingAuditSink()

    with TestClient(
        status_app(sessions, audit_sink=sink, auth_settings=cognito_settings())
    ) as http:
        responses = [
            http.get(f"/projects/{project_id}/documents"),
            http.get(f"/projects/{project_id}/documents/{uuid4()}"),
        ]

    for response in responses:
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert "filename" not in response.text
    assert [event.result for event in sink.events] == [AuditResult.DENIED] * 2


# --- Database unavailable -----------------------------------------------------


class _UnavailableStatus:
    def list_for_project(self, *, project_id: UUID, limit: int = 100) -> Any:
        del project_id, limit
        raise DocumentStatusUnavailable

    def get_for_project(self, *, project_id: UUID, document_id: UUID) -> Any:
        del project_id, document_id
        raise DocumentStatusUnavailable


def test_status_unavailable_returns_the_existing_503(
    sessions: sessionmaker[Session],
) -> None:
    project_id = create_project(sessions)

    with TestClient(
        status_app(sessions, status_repository=_UnavailableStatus())
    ) as http:
        responses = [
            http.get(f"/projects/{project_id}/documents"),
            http.get(f"/projects/{project_id}/documents/{uuid4()}"),
        ]

    for response in responses:
        assert response.status_code == 503
        assert response.json() == {"detail": DOCUMENT_INTAKE_UNAVAILABLE_DETAIL}
        assert UUID(response.headers["X-Correlation-ID"])


def test_database_errors_become_status_unavailable(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'empty.db'}")
    repository = SqlAlchemyDocumentStatusRepository(
        sessionmaker(engine, expire_on_commit=False)
    )

    with pytest.raises(DocumentStatusUnavailable):
        repository.list_for_project(project_id=uuid4())
    with pytest.raises(DocumentStatusUnavailable):
        repository.get_for_project(project_id=uuid4(), document_id=uuid4())
    engine.dispose()
