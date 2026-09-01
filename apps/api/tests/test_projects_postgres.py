"""PostgreSQL-backed project API integration evidence for ``db-check`` only."""

from __future__ import annotations

import os
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from ai_qa_copilot_api.analysis_runs import (
    AnalysisRunService,
    SqlAlchemyAnalysisRunRepository,
)
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.indexing import (
    EmbeddingConfiguration,
    LexicalRetrievalFilters,
    LexicalRetrievalService,
    SqlAlchemyLexicalRetrievalStore,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.model_gateway import (
    B1_MODEL_ID,
    ModelGateway,
    ModelUsage,
    StructuredModelRequest,
    StructuredModelResponse,
)
from ai_qa_copilot_api.lexical_retrieval import (
    LexicalRetrievalFilters,
    LexicalRetrievalService,
    SqlAlchemyLexicalRetrievalStore,
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
                    "TRUNCATE TABLE parser_jobs, document_intakes, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, source_locations, "
                    "document_versions, documents, "
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
                    "TRUNCATE TABLE parser_jobs, document_intakes, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, source_locations, "
                    "document_versions, documents, "
                    "parser_versions, analysis_runs, projects"
                )
            )
        engine.dispose()


@pytest.mark.postgres_integration
def test_project_scoped_lexical_retrieval_returns_only_owned_chunks() -> None:
    """Exercise PostgreSQL FTS, ranking, and mandatory project scoping."""

    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    project_id = uuid4()
    foreign_project_id = uuid4()
    parser_version_id = uuid4()
    document_id = uuid4()
    foreign_document_id = uuid4()
    version_id = uuid4()
    foreign_version_id = uuid4()
    location_id = uuid4()
    foreign_location_id = uuid4()
    section_id = uuid4()
    foreign_section_id = uuid4()
    matching_chunk_id = uuid4()
    foreign_chunk_id = uuid4()
    target_text = "FR-AUTH-001 requires an exact bearer token and status 401 response."
    foreign_text = "FR-AUTH-001 belongs to another project and must never leak."
    target_hash = sha256(target_text.encode("utf-8")).hexdigest()
    foreign_hash = sha256(foreign_text.encode("utf-8")).hexdigest()

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE parser_jobs, document_intakes, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, source_locations, "
                    "document_versions, documents, parser_versions, analysis_runs, projects"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO projects (id, name, description, created_at, archived_at) "
                    "VALUES (:id, 'Lexical project', NULL, CURRENT_TIMESTAMP, NULL), "
                    "(:foreign_id, 'Foreign project', NULL, CURRENT_TIMESTAMP, NULL)"
                ),
                {"id": project_id, "foreign_id": foreign_project_id},
            )
            connection.execute(
                text(
                    "INSERT INTO parser_versions "
                    "(id, parser_name, parser_version, normalization_version, created_at) "
                    "VALUES (:id, 'markdown', 'test-v1', 'norm-v1', CURRENT_TIMESTAMP)"
                ),
                {"id": parser_version_id},
            )
            connection.execute(
                text(
                    "INSERT INTO documents "
                    "(id, project_id, document_type, display_name, created_at) "
                    "VALUES (:id, :project_id, 'markdown', 'requirements.md', CURRENT_TIMESTAMP), "
                    "(:foreign_id, :foreign_project_id, 'markdown', 'foreign.md', CURRENT_TIMESTAMP)"
                ),
                {
                    "id": document_id,
                    "project_id": project_id,
                    "foreign_id": foreign_document_id,
                    "foreign_project_id": foreign_project_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO document_versions "
                    "(id, document_id, parser_version_id, version_number, content_sha256, "
                    "byte_size, content_type, created_at) "
                    "VALUES (:id, :document_id, :parser_id, 1, :hash, 100, 'text/markdown', CURRENT_TIMESTAMP), "
                    "(:foreign_id, :foreign_document_id, :parser_id, 1, :foreign_hash, 100, 'text/markdown', CURRENT_TIMESTAMP)"
                ),
                {
                    "id": version_id,
                    "document_id": document_id,
                    "parser_id": parser_version_id,
                    "hash": target_hash,
                    "foreign_id": foreign_version_id,
                    "foreign_document_id": foreign_document_id,
                    "foreign_hash": foreign_hash,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO source_locations "
                    "(id, document_version_id, location_kind, heading, line_start, line_end) "
                    "VALUES (:id, :version_id, 'markdown', 'Authentication', 10, 10), "
                    "(:foreign_id, :foreign_version_id, 'markdown', 'Foreign', 10, 10)"
                ),
                {
                    "id": location_id,
                    "version_id": version_id,
                    "foreign_id": foreign_location_id,
                    "foreign_version_id": foreign_version_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO document_sections "
                    "(id, document_version_id, source_location_id, ordinal, section_key, "
                    "normalized_text, content_sha256) "
                    "VALUES (:id, :version_id, :location_id, 0, 'FR-AUTH-001', :text, :hash), "
                    "(:foreign_id, :foreign_version_id, :foreign_location_id, 0, 'FR-AUTH-001', :foreign_text, :foreign_hash)"
                ),
                {
                    "id": section_id,
                    "version_id": version_id,
                    "location_id": location_id,
                    "text": target_text,
                    "hash": target_hash,
                    "foreign_id": foreign_section_id,
                    "foreign_version_id": foreign_version_id,
                    "foreign_location_id": foreign_location_id,
                    "foreign_text": foreign_text,
                    "foreign_hash": foreign_hash,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO document_chunks "
                    "(id, document_version_id, document_section_id, source_location_id, ordinal, "
                    "normalized_text, content_sha256, chunking_version) "
                    "VALUES (:id, :version_id, :section_id, :location_id, 0, :text, :hash, 'chunking-v1'), "
                    "(:foreign_id, :foreign_version_id, :foreign_section_id, :foreign_location_id, 0, "
                    ":foreign_text, :foreign_hash, 'chunking-v1')"
                ),
                {
                    "id": matching_chunk_id,
                    "version_id": version_id,
                    "section_id": section_id,
                    "location_id": location_id,
                    "text": target_text,
                    "hash": target_hash,
                    "foreign_id": foreign_chunk_id,
                    "foreign_version_id": foreign_version_id,
                    "foreign_section_id": foreign_section_id,
                    "foreign_location_id": foreign_location_id,
                    "foreign_text": foreign_text,
                    "foreign_hash": foreign_hash,
                },
            )

        service = LexicalRetrievalService(
            SqlAlchemyLexicalRetrievalStore.from_database_url(database_url)
        )
        response = service.search(
            project_id=project_id,
            query="FR-AUTH-001",
            filters=LexicalRetrievalFilters(
                document_version_ids=(version_id,),
                document_types=("markdown",),
                chunking_version="chunking-v1",
            ),
            limit=10,
        )

        assert response.retrieval_version == "lexical-v1"
        assert response.query == "FR-AUTH-001"
        assert len(response.candidates) == 1
        candidate = response.candidates[0]
        assert candidate.chunk_id == matching_chunk_id
        assert candidate.project_id == project_id
        assert candidate.document_version_id == version_id
        assert candidate.source_location_id == location_id
        assert candidate.rank == 1
        assert candidate.score > 0
        assert "another project" not in candidate.normalized_text
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE parser_jobs, document_intakes, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, source_locations, "
                    "document_versions, documents, parser_versions, analysis_runs, projects"
                )
            )
        engine.dispose()
