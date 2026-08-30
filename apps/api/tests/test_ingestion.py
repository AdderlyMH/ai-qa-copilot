from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response as HttpxResponse
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.audit import StructuredLoggingAuditSink
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.documents import DocumentIntakeRecord, DocumentIntakeState
from ai_qa_copilot_api.ingestion import (
    InMemoryQuarantineStorage,
    SqlAlchemyDocumentIntakeRepository,
    UploadPolicy,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import (
    Base,
    ProjectRepository,
    SqlAlchemyProjectRepository,
)


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


@pytest.fixture
def sessions(tmp_path: Path) -> Generator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ingestion.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    engine.dispose()


@pytest.fixture
def project_repository(sessions: sessionmaker[Session]) -> ProjectRepository:
    return SqlAlchemyProjectRepository(sessions)


def intake_client(
    *,
    project_repository: ProjectRepository,
    sessions: sessionmaker[Session],
    storage: InMemoryQuarantineStorage,
    policy: UploadPolicy = UploadPolicy(),
    auth_settings: AuthSettings | None = None,
) -> TestClient:
    app = create_app(
        auth_settings or local_bypass_settings(),
        project_repository=project_repository,
        document_intake_repository=SqlAlchemyDocumentIntakeRepository(sessions),
        quarantine_storage=storage,
        document_intake_policy=policy,
        authorization_audit_sink=StructuredLoggingAuditSink(),
    )
    return TestClient(app)


def upload(
    client: TestClient,
    project_id: UUID,
    *,
    filename: str,
    content_type: str,
    content: bytes,
    extra_headers: dict[str, str] | None = None,
) -> HttpxResponse:
    headers = {
        "X-Upload-Filename": filename,
        "Content-Type": content_type,
    }
    if extra_headers is not None:
        headers.update(extra_headers)
    return cast(
        HttpxResponse,
        client.post(
            f"/projects/{project_id}/documents", content=content, headers=headers
        ),
    )


def records(sessions: sessionmaker[Session]) -> list[DocumentIntakeRecord]:
    with sessions() as session:
        return list(
            session.scalars(
                select(DocumentIntakeRecord).order_by(DocumentIntakeRecord.created_at)
            )
        )


def test_owner_uploads_markdown_to_private_generated_quarantine_key(
    sessions: sessionmaker[Session], project_repository: ProjectRepository
) -> None:
    project = project_repository.create(name="Ingestion", description=None)
    storage = InMemoryQuarantineStorage()
    with intake_client(
        project_repository=project_repository, sessions=sessions, storage=storage
    ) as client:
        response = upload(
            client,
            project.id,
            filename="requirements.md",
            content_type="text/markdown; charset=utf-8",
            content=b"# Checkout\nCart IDs are required.\n",
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["state"] == "quarantined"
    assert payload["deduplicated"] is False
    assert UUID(payload["document_id"])
    assert UUID(payload["document_version_id"])
    assert UUID(response.headers["X-Correlation-ID"])
    assert len(storage.objects) == 1
    key, (stored, stored_type) = next(iter(storage.objects.items()))
    assert key.startswith(f"quarantine/{project.id}/")
    assert key.endswith("/raw")
    assert "requirements.md" not in key
    assert stored == b"# Checkout\nCart IDs are required.\n"
    assert stored_type == "text/markdown"
    saved = records(sessions)
    assert len(saved) == 1
    assert saved[0].state == DocumentIntakeState.QUARANTINED.value
    assert saved[0].quarantine_key == key
    assert saved[0].rejection_code is None


def test_rejections_persist_only_sanitized_outcomes_and_no_raw_object(
    sessions: sessionmaker[Session], project_repository: ProjectRepository
) -> None:
    project = project_repository.create(name="Ingestion", description=None)
    storage = InMemoryQuarantineStorage()
    with intake_client(
        project_repository=project_repository, sessions=sessions, storage=storage
    ) as client:
        response = upload(
            client,
            project.id,
            filename="payload.pdf",
            content_type="text/plain",
            content=b"not a pdf",
            extra_headers={"Content-Encoding": "gzip"},
        )

    assert response.status_code == 415
    assert response.json()["detail"] == {
        "code": "UPLOAD_CONTENT_ENCODING_UNSUPPORTED",
        "message": "Document upload was rejected",
        "retryable": False,
    }
    assert storage.objects == {}
    saved = records(sessions)
    assert len(saved) == 1
    assert saved[0].state == DocumentIntakeState.REJECTED.value
    assert saved[0].document_id is None
    assert saved[0].document_version_id is None
    assert saved[0].quarantine_key is None
    assert saved[0].content_sha256 is None
    assert saved[0].rejection_code == "UPLOAD_CONTENT_ENCODING_UNSUPPORTED"


def test_oversized_or_invalid_utf8_text_is_rejected_before_storage(
    sessions: sessionmaker[Session], project_repository: ProjectRepository
) -> None:
    project = project_repository.create(name="Ingestion", description=None)
    storage = InMemoryQuarantineStorage()
    with intake_client(
        project_repository=project_repository, sessions=sessions, storage=storage
    ) as client:
        oversized = upload(
            client,
            project.id,
            filename="large.txt",
            content_type="text/plain",
            content=b"x" * (2 * 1024 * 1024 + 1),
        )
        invalid_encoding = upload(
            client,
            project.id,
            filename="invalid.txt",
            content_type="text/plain",
            content=b"\xff\xfe",
        )

    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "UPLOAD_SIZE_LIMIT"
    assert invalid_encoding.status_code == 400
    assert invalid_encoding.json()["detail"]["code"] == "UPLOAD_TEXT_ENCODING_INVALID"
    assert storage.objects == {}
    assert [record.rejection_code for record in records(sessions)] == [
        "UPLOAD_SIZE_LIMIT",
        "UPLOAD_TEXT_ENCODING_INVALID",
    ]


def test_identical_content_is_deduplicated_without_a_second_raw_object(
    sessions: sessionmaker[Session], project_repository: ProjectRepository
) -> None:
    project = project_repository.create(name="Ingestion", description=None)
    storage = InMemoryQuarantineStorage()
    with intake_client(
        project_repository=project_repository, sessions=sessions, storage=storage
    ) as client:
        first = upload(
            client,
            project.id,
            filename="requirements.md",
            content_type="text/markdown",
            content=b"# One\n",
        )
        duplicate = upload(
            client,
            project.id,
            filename="same-content-different-name.md",
            content_type="text/markdown",
            content=b"# One\n",
        )

    assert first.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == first.json()["id"]
    assert duplicate.json()["deduplicated"] is True
    assert len(storage.objects) == 1
    assert len(records(sessions)) == 1


def test_project_quota_rejects_before_a_second_raw_object_is_stored(
    sessions: sessionmaker[Session], project_repository: ProjectRepository
) -> None:
    project = project_repository.create(name="Ingestion", description=None)
    storage = InMemoryQuarantineStorage()
    with intake_client(
        project_repository=project_repository,
        sessions=sessions,
        storage=storage,
        policy=UploadPolicy(
            max_raw_bytes=10,
            max_files_per_project=1,
            max_total_bytes_per_project=10,
        ),
    ) as client:
        first = upload(
            client,
            project.id,
            filename="first.txt",
            content_type="text/plain",
            content=b"one",
        )
        second = upload(
            client,
            project.id,
            filename="second.txt",
            content_type="text/plain",
            content=b"two",
        )

    assert first.status_code == 202
    assert second.status_code == 400
    assert second.json()["detail"]["code"] == "UPLOAD_FILE_COUNT_LIMIT"
    assert len(storage.objects) == 1
    assert [record.state for record in records(sessions)] == [
        DocumentIntakeState.QUARANTINED.value,
        DocumentIntakeState.REJECTED.value,
    ]


def test_owner_authorization_precedes_upload_stream_and_persistence(
    sessions: sessionmaker[Session], project_repository: ProjectRepository
) -> None:
    project = project_repository.create(name="Ingestion", description=None)
    storage = InMemoryQuarantineStorage()
    settings = AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=False,
        cognito=None,
    )
    with intake_client(
        project_repository=project_repository,
        sessions=sessions,
        storage=storage,
        auth_settings=settings,
    ) as client:
        response = upload(
            client,
            project.id,
            filename="requirements.md",
            content_type="text/markdown",
            content=b"# One\n",
        )

    assert response.status_code == 401
    assert storage.objects == {}
    assert records(sessions) == []


def test_upload_fails_closed_when_private_storage_is_not_configured(
    project_repository: ProjectRepository,
) -> None:
    project = project_repository.create(name="Ingestion", description=None)
    with TestClient(
        create_app(local_bypass_settings(), project_repository=project_repository)
    ) as client:
        response = upload(
            client,
            project.id,
            filename="requirements.md",
            content_type="text/markdown",
            content=b"# One\n",
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Document intake service is temporarily unavailable"
    }
    assert UUID(response.headers["X-Correlation-ID"])
