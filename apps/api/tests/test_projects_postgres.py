"""PostgreSQL-backed project API integration evidence for ``db-check`` only."""

from __future__ import annotations

import os
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.main import create_app


POSTGRES_INTEGRATION_DATABASE_URL = "AI_QA_COPILOT_POSTGRES_INTEGRATION_DATABASE_URL"


def isolated_postgres_database_url() -> str:
    """Return only the database URL explicitly opted into for this destructive test."""

    database_url = os.environ.get(POSTGRES_INTEGRATION_DATABASE_URL, "").strip()
    if not database_url:
        pytest.skip("requires the isolated PostgreSQL database from db-check")

    application_database_url = os.environ.get("DATABASE_URL", "").strip()
    if application_database_url != database_url:
        pytest.fail(
            "DATABASE_URL must match "
            f"{POSTGRES_INTEGRATION_DATABASE_URL} for PostgreSQL CRUD validation"
        )
    return database_url


def local_bypass_settings() -> AuthSettings:
    """Use the existing local-only owner boundary for isolated API validation."""

    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


@pytest.mark.postgres_integration
def test_migrated_postgres_supports_project_crud() -> None:
    """Exercise API CRUD against the Alembic-created PostgreSQL project table."""

    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE projects"))

        with TestClient(create_app(local_bypass_settings())) as client:
            created = client.post(
                "/projects",
                json={
                    "name": "PostgreSQL CRUD evidence",
                    "description": "Created through the FastAPI project route.",
                },
            )
            assert created.status_code == 201
            project_id = UUID(created.json()["id"])

            listed_before_archive = client.get("/projects")
            viewed = client.get(f"/projects/{project_id}")
            archived = client.post(f"/projects/{project_id}/archive")
            listed_after_archive = client.get("/projects")
            viewed_after_archive = client.get(f"/projects/{project_id}")

        assert [project["id"] for project in listed_before_archive.json()] == [
            str(project_id)
        ]
        assert listed_before_archive.status_code == 200
        assert viewed.status_code == 200
        assert viewed.json()["archived_at"] is None
        assert archived.status_code == 200
        assert archived.json()["archived_at"] is not None
        assert listed_after_archive.status_code == 200
        assert listed_after_archive.json() == []
        assert viewed_after_archive.status_code == 200
        assert viewed_after_archive.json()["archived_at"] == archived.json()["archived_at"]

        with engine.connect() as connection:
            record = connection.execute(
                text(
                    "SELECT name, description, archived_at "
                    "FROM projects WHERE id = :project_id"
                ),
                {"project_id": project_id},
            ).one()
        assert record.name == "PostgreSQL CRUD evidence"
        assert record.description == "Created through the FastAPI project route."
        assert record.archived_at is not None
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE projects"))
        engine.dispose()
