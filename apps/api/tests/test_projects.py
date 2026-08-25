from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.audit import AuthorizationAuditEvent, AuthorizationAuditSink
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import Base, ProjectRepository, SqlAlchemyProjectRepository


class RecordingAuditSink(AuthorizationAuditSink):
    def __init__(self) -> None:
        self.events: list[AuthorizationAuditEvent] = []

    def record(self, event: AuthorizationAuditEvent) -> None:
        self.events.append(event)


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


@pytest.fixture
def project_repository(tmp_path: Path) -> ProjectRepository:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'projects.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    repository = SqlAlchemyProjectRepository(sessions)
    yield repository
    engine.dispose()


def project_client(
    project_repository: ProjectRepository,
    audit_sink: RecordingAuditSink,
) -> TestClient:
    return TestClient(
        create_app(
            local_bypass_settings(),
            project_repository=project_repository,
            authorization_audit_sink=audit_sink,
        )
    )


def test_owner_can_create_list_view_and_archive_a_project(
    project_repository: ProjectRepository,
) -> None:
    audit_sink = RecordingAuditSink()
    with project_client(project_repository, audit_sink) as client:
        created = client.post(
            "/projects",
            json={
                "name": "  Checkout API quality review  ",
                "description": "  Synthetic acceptance coverage  ",
            },
        )
        listed_before_archive = client.get("/projects")
        project_id = UUID(created.json()["id"])
        viewed = client.get(f"/projects/{project_id}")
        archived = client.post(f"/projects/{project_id}/archive")
        listed_after_archive = client.get("/projects")
        viewed_after_archive = client.get(f"/projects/{project_id}")

    assert created.status_code == 201
    assert created.json()["name"] == "Checkout API quality review"
    assert created.json()["description"] == "Synthetic acceptance coverage"
    assert datetime.fromisoformat(created.json()["created_at"]).tzinfo is not None
    assert UUID(created.headers["X-Correlation-ID"])
    assert listed_before_archive.status_code == 200
    assert [item["id"] for item in listed_before_archive.json()] == [str(project_id)]
    assert viewed.status_code == 200
    assert viewed.json()["archived_at"] is None
    assert archived.status_code == 200
    assert datetime.fromisoformat(archived.json()["archived_at"]).tzinfo is not None
    assert listed_after_archive.status_code == 200
    assert listed_after_archive.json() == []
    assert viewed_after_archive.status_code == 200
    assert viewed_after_archive.json()["archived_at"] == archived.json()["archived_at"]
    assert [(event.action, event.result.value, event.resource_type) for event in audit_sink.events] == [
        ("project.mutate", "allowed", "project_collection"),
        ("project.list", "allowed", "project_collection"),
        ("project.read", "allowed", "project"),
        ("project.mutate", "allowed", "project"),
        ("project.list", "allowed", "project_collection"),
        ("project.read", "allowed", "project"),
    ]


def test_project_collection_rejects_missing_credentials_before_repository_work(
    project_repository: ProjectRepository,
) -> None:
    audit_sink = RecordingAuditSink()
    app = create_app(
        AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=None,
        ),
        project_repository=project_repository,
        authorization_audit_sink=audit_sink,
    )

    with TestClient(app) as client:
        response = client.get("/projects")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid or missing credentials"}
    assert project_repository.list_active() == []
    assert len(audit_sink.events) == 1
    assert audit_sink.events[0].reason == "invalid_or_missing_credentials"
    assert audit_sink.events[0].resource_type == "project_collection"


def test_project_routes_fail_closed_when_durable_storage_is_not_configured() -> None:
    audit_sink = RecordingAuditSink()
    app = create_app(
        local_bypass_settings(),
        authorization_audit_sink=audit_sink,
    )

    with TestClient(app) as client:
        response = client.get("/projects")

    assert response.status_code == 503
    assert response.json() == {"detail": "Project service is temporarily unavailable"}
    assert UUID(response.headers["X-Correlation-ID"])
    assert len(audit_sink.events) == 1
    assert audit_sink.events[0].result.value == "allowed"


def test_project_requests_reject_invalid_input_and_do_not_create_records(
    project_repository: ProjectRepository,
) -> None:
    audit_sink = RecordingAuditSink()
    with project_client(project_repository, audit_sink) as client:
        response = client.post("/projects", json={"name": "   ", "unexpected": True})
        listed = client.get("/projects")

    assert response.status_code == 422
    assert listed.json() == []
    assert len(audit_sink.events) == 1
    assert audit_sink.events[0].action == "project.list"
