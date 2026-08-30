"""PostgreSQL-backed project API integration evidence for ``db-check`` only."""

from __future__ import annotations

import os
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from ai_qa_copilot_api.analysis_runs import (
    AnalysisRunService,
    SqlAlchemyAnalysisRunRepository,
)
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.model_gateway import (
    B1_MODEL_ID,
    ModelGateway,
    ModelUsage,
    StructuredModelRequest,
    StructuredModelResponse,
)


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


class PostgresFakeModelAdapter:
    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        return StructuredModelResponse(
            correlation_id=request.correlation_id,
            response_id="postgres-fake-response",
            model_id=B1_MODEL_ID,
            output_json={"summary": "PostgreSQL synthetic analysis"},
            usage=ModelUsage(input_tokens=3, output_tokens=2, total_tokens=5),
        )


@pytest.mark.postgres_integration
def test_migrated_postgres_supports_project_crud_and_analysis_runs() -> None:
    """Exercise the SKEL-003/005 FastAPI path against migrated PostgreSQL."""

    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE document_intakes, document_chunks, document_sections, "
                    "source_locations, document_versions, documents, "
                    "parser_versions, analysis_runs, projects"
                )
            )

        analysis_run_service = AnalysisRunService(
            SqlAlchemyAnalysisRunRepository.from_database_url(database_url),
            ModelGateway(PostgresFakeModelAdapter()),
        )
        with TestClient(
            create_app(
                local_bypass_settings(),
                analysis_run_service=analysis_run_service,
            )
        ) as client:
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
            analysis_run = client.post(
                f"/projects/{project_id}/analysis-runs",
                json={"synthetic_text": "PostgreSQL-backed synthetic input."},
            )
            listed_analysis_runs = client.get(f"/projects/{project_id}/analysis-runs")
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
        assert (
            viewed_after_archive.json()["archived_at"] == archived.json()["archived_at"]
        )
        assert analysis_run.status_code == 201
        assert analysis_run.json()["output_json"] == {
            "summary": "PostgreSQL synthetic analysis"
        }
        assert listed_analysis_runs.status_code == 200
        assert listed_analysis_runs.json() == [analysis_run.json()]

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
            connection.execute(
                text(
                    "TRUNCATE TABLE document_intakes, document_chunks, document_sections, "
                    "source_locations, document_versions, documents, "
                    "parser_versions, analysis_runs, projects"
                )
            )
        engine.dispose()
