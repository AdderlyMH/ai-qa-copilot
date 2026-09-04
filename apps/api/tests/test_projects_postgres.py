"""PostgreSQL-backed project API integration evidence for ``db-check`` only."""

from __future__ import annotations

import json
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
from ai_qa_copilot_api.citations import (
    CitationValidationError,
    SqlAlchemyCitationRepository,
)
from ai_qa_copilot_api.lexical_retrieval import (
    LexicalRetrievalFilters,
    LexicalRetrievalService,
    SqlAlchemyLexicalRetrievalStore,
)
from ai_qa_copilot_api.hybrid_retrieval import (
    HybridRetrievalFilters,
    HybridRetrievalService,
    SqlAlchemyHybridRetrievalStore,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.model_gateway import (
    B1_MODEL_ID,
    ModelGateway,
    ModelUsage,
    StructuredModelRequest,
    StructuredModelResponse,
)
from ai_qa_copilot_api.requirements_analysis import (
    RequirementAnalysisService,
    SqlAlchemyRequirementAnalysisRepository,
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
                    "TRUNCATE TABLE requirement_findings, requirement_analysis_runs, "
                    "citations, parser_jobs, document_intakes, retrieval_trace_candidates, "
                    "retrieval_traces, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, "
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
                    "TRUNCATE TABLE requirement_findings, requirement_analysis_runs, "
                    "citations, parser_jobs, document_intakes, retrieval_trace_candidates, "
                    "retrieval_traces, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, "
                    "source_locations, document_versions, documents, "
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
    cache_id = uuid4()
    foreign_cache_id = uuid4()
    chunk_embedding_id = uuid4()
    foreign_chunk_embedding_id = uuid4()
    target_text = "FR-AUTH-001 requires an exact bearer token and status 401 response."
    foreign_text = "FR-AUTH-001 belongs to another project and must never leak."
    target_hash = sha256(target_text.encode("utf-8")).hexdigest()
    foreign_hash = sha256(foreign_text.encode("utf-8")).hexdigest()

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE requirement_findings, requirement_analysis_runs, "
                    "citations, parser_jobs, document_intakes, retrieval_trace_candidates, "
                    "retrieval_traces, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, "
                    "source_locations, document_versions, documents, "
                    "parser_versions, analysis_runs, projects"
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
            connection.execute(
                text(
                    "INSERT INTO embedding_cache_entries "
                    "(id, project_id, content_sha256, embedding_model, embedding_version, dimensions, values, created_at) "
                    "VALUES (:id, :project_id, :hash, 'embedding-test-v1', 'embedding-v1', 2, CAST(:values AS json), CURRENT_TIMESTAMP), "
                    "(:foreign_id, :foreign_project_id, :foreign_hash, 'embedding-test-v1', 'embedding-v1', 2, CAST(:foreign_values AS json), CURRENT_TIMESTAMP)"
                ),
                {
                    "id": cache_id,
                    "project_id": project_id,
                    "hash": target_hash,
                    "values": json.dumps([0.9, 0.1]),
                    "foreign_id": foreign_cache_id,
                    "foreign_project_id": foreign_project_id,
                    "foreign_hash": foreign_hash,
                    "foreign_values": json.dumps([1.0, 0.0]),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO document_chunk_embeddings "
                    "(id, document_chunk_id, embedding_cache_id, embedding_model, embedding_version, created_at) "
                    "VALUES (:id, :chunk_id, :cache_id, 'embedding-test-v1', 'embedding-v1', CURRENT_TIMESTAMP), "
                    "(:foreign_id, :foreign_chunk_id, :foreign_cache_id, 'embedding-test-v1', 'embedding-v1', CURRENT_TIMESTAMP)"
                ),
                {
                    "id": chunk_embedding_id,
                    "chunk_id": matching_chunk_id,
                    "cache_id": cache_id,
                    "foreign_id": foreign_chunk_embedding_id,
                    "foreign_chunk_id": foreign_chunk_id,
                    "foreign_cache_id": foreign_cache_id,
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

        hybrid_response = HybridRetrievalService(
            SqlAlchemyHybridRetrievalStore.from_database_url(database_url)
        ).retrieve(
            project_id=project_id,
            query="FR-AUTH-001",
            query_embedding=(0.9, 0.1),
            filters=HybridRetrievalFilters(
                embedding_model="embedding-test-v1",
                embedding_version="embedding-v1",
                document_version_ids=(version_id,),
                document_types=("markdown",),
                chunking_version="chunking-v1",
            ),
            candidate_limit=10,
            result_limit=10,
        )

        assert hybrid_response.retrieval_version == "hybrid-v1"
        assert len(hybrid_response.candidates) == 1
        hybrid_candidate = hybrid_response.candidates[0]
        assert hybrid_candidate.chunk_id == matching_chunk_id
        assert hybrid_candidate.project_id == project_id
        assert hybrid_candidate.lexical_rank == 1
        assert hybrid_candidate.semantic_rank == 1
        assert hybrid_candidate.fusion_score > 0
        with engine.connect() as connection:
            trace = connection.execute(
                text(
                    "SELECT project_id, query, query_embedding, embedding_model, embedding_version, "
                    "candidate_limit, result_limit FROM retrieval_traces WHERE id = :trace_id"
                ),
                {"trace_id": hybrid_response.trace_id},
            ).one()
            trace_candidate = connection.execute(
                text(
                    "SELECT document_chunk_id, lexical_score, lexical_rank, semantic_distance, semantic_rank, "
                    "fusion_score, final_rank FROM retrieval_trace_candidates WHERE retrieval_trace_id = :trace_id"
                ),
                {"trace_id": hybrid_response.trace_id},
            ).one()
        assert trace.project_id == project_id
        assert trace.query == "FR-AUTH-001"
        assert trace.query_embedding == [0.9, 0.1]
        assert trace.embedding_model == "embedding-test-v1"
        assert trace.embedding_version == "embedding-v1"
        assert (trace.candidate_limit, trace.result_limit) == (10, 10)
        assert trace_candidate.document_chunk_id == matching_chunk_id
        assert trace_candidate.lexical_rank == 1
        assert trace_candidate.semantic_rank == 1
        assert trace_candidate.final_rank == 1
        assert trace_candidate.lexical_score > 0
        assert trace_candidate.semantic_distance >= 0
        assert trace_candidate.fusion_score > 0

        citation_repository = SqlAlchemyCitationRepository.from_database_url(
            database_url
        )
        citation = citation_repository.create_from_selected_candidate(
            project_id=project_id,
            retrieval_trace_id=hybrid_response.trace_id,
            document_chunk_id=matching_chunk_id,
        )
        assert citation.project_id == project_id
        assert citation.document_version_id == version_id
        assert citation.source_location.id == location_id
        assert citation.passage == target_text
        assert (
            citation_repository.get_for_project(
                project_id=project_id, citation_id=citation.id
            )
            == citation
        )
        assert (
            citation_repository.get_for_project(
                project_id=foreign_project_id, citation_id=citation.id
            )
            is None
        )
        with pytest.raises(CitationValidationError):
            citation_repository.create_from_selected_candidate(
                project_id=foreign_project_id,
                retrieval_trace_id=hybrid_response.trace_id,
                document_chunk_id=matching_chunk_id,
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE requirement_findings, requirement_analysis_runs, "
                    "citations, parser_jobs, document_intakes, retrieval_trace_candidates, "
                    "retrieval_traces, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, "
                    "source_locations, document_versions, documents, "
                    "parser_versions, analysis_runs, projects"
                )
            )
        engine.dispose()


@pytest.mark.postgres_integration
def test_requirement_analysis_run_persists_and_is_project_scoped() -> None:
    """Persist deterministic requirement analysis and enforce project scoping."""

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
    cache_id = uuid4()
    foreign_cache_id = uuid4()
    chunk_embedding_id = uuid4()
    foreign_chunk_embedding_id = uuid4()
    target_text = "FR-AUTH-001 must provide fast bearer authentication updates."
    foreign_text = "FR-AUTH-001 belongs to another project and must never leak."
    target_hash = sha256(target_text.encode("utf-8")).hexdigest()
    foreign_hash = sha256(foreign_text.encode("utf-8")).hexdigest()

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE requirement_findings, requirement_analysis_runs, "
                    "citations, parser_jobs, document_intakes, retrieval_trace_candidates, "
                    "retrieval_traces, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, "
                    "source_locations, document_versions, documents, "
                    "parser_versions, analysis_runs, projects"
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
            connection.execute(
                text(
                    "INSERT INTO embedding_cache_entries "
                    "(id, project_id, content_sha256, embedding_model, embedding_version, dimensions, values, created_at) "
                    "VALUES (:id, :project_id, :hash, 'embedding-test-v1', 'embedding-v1', 2, CAST(:values AS json), CURRENT_TIMESTAMP), "
                    "(:foreign_id, :foreign_project_id, :foreign_hash, 'embedding-test-v1', 'embedding-v1', 2, CAST(:foreign_values AS json), CURRENT_TIMESTAMP)"
                ),
                {
                    "id": cache_id,
                    "project_id": project_id,
                    "hash": target_hash,
                    "values": json.dumps([0.9, 0.1]),
                    "foreign_id": foreign_cache_id,
                    "foreign_project_id": foreign_project_id,
                    "foreign_hash": foreign_hash,
                    "foreign_values": json.dumps([1.0, 0.0]),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO document_chunk_embeddings "
                    "(id, document_chunk_id, embedding_cache_id, embedding_model, embedding_version, created_at) "
                    "VALUES (:id, :chunk_id, :cache_id, 'embedding-test-v1', 'embedding-v1', CURRENT_TIMESTAMP), "
                    "(:foreign_id, :foreign_chunk_id, :foreign_cache_id, 'embedding-test-v1', 'embedding-v1', CURRENT_TIMESTAMP)"
                ),
                {
                    "id": chunk_embedding_id,
                    "chunk_id": matching_chunk_id,
                    "cache_id": cache_id,
                    "foreign_id": foreign_chunk_embedding_id,
                    "foreign_chunk_id": foreign_chunk_id,
                    "foreign_cache_id": foreign_cache_id,
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

        hybrid_response = HybridRetrievalService(
            SqlAlchemyHybridRetrievalStore.from_database_url(database_url)
        ).retrieve(
            project_id=project_id,
            query="FR-AUTH-001",
            query_embedding=(0.9, 0.1),
            filters=HybridRetrievalFilters(
                embedding_model="embedding-test-v1",
                embedding_version="embedding-v1",
                document_version_ids=(version_id,),
                document_types=("markdown",),
                chunking_version="chunking-v1",
            ),
            candidate_limit=10,
            result_limit=10,
        )

        assert hybrid_response.retrieval_version == "hybrid-v1"
        assert len(hybrid_response.candidates) == 1
        hybrid_candidate = hybrid_response.candidates[0]
        assert hybrid_candidate.chunk_id == matching_chunk_id
        assert hybrid_candidate.project_id == project_id
        assert hybrid_candidate.lexical_rank == 1
        assert hybrid_candidate.semantic_rank == 1
        assert hybrid_candidate.fusion_score > 0
        with engine.connect() as connection:
            trace = connection.execute(
                text(
                    "SELECT project_id, query, query_embedding, embedding_model, embedding_version, "
                    "candidate_limit, result_limit FROM retrieval_traces WHERE id = :trace_id"
                ),
                {"trace_id": hybrid_response.trace_id},
            ).one()
            trace_candidate = connection.execute(
                text(
                    "SELECT document_chunk_id, lexical_score, lexical_rank, semantic_distance, semantic_rank, "
                    "fusion_score, final_rank FROM retrieval_trace_candidates WHERE retrieval_trace_id = :trace_id"
                ),
                {"trace_id": hybrid_response.trace_id},
            ).one()
        assert trace.project_id == project_id
        assert trace.query == "FR-AUTH-001"
        assert trace.query_embedding == [0.9, 0.1]
        assert trace.embedding_model == "embedding-test-v1"
        assert trace.embedding_version == "embedding-v1"
        assert (trace.candidate_limit, trace.result_limit) == (10, 10)
        assert trace_candidate.document_chunk_id == matching_chunk_id
        assert trace_candidate.lexical_rank == 1
        assert trace_candidate.semantic_rank == 1
        assert trace_candidate.final_rank == 1
        assert trace_candidate.lexical_score > 0
        assert trace_candidate.semantic_distance >= 0
        assert trace_candidate.fusion_score > 0

        citation_repository = SqlAlchemyCitationRepository.from_database_url(
            database_url
        )
        citation = citation_repository.create_from_selected_candidate(
            project_id=project_id,
            retrieval_trace_id=hybrid_response.trace_id,
            document_chunk_id=matching_chunk_id,
        )
        assert citation.project_id == project_id
        assert citation.document_version_id == version_id
        assert citation.source_location.id == location_id
        assert citation.passage == target_text
        assert (
            citation_repository.get_for_project(
                project_id=project_id, citation_id=citation.id
            )
            == citation
        )
        assert (
            citation_repository.get_for_project(
                project_id=foreign_project_id, citation_id=citation.id
            )
            is None
        )
        with pytest.raises(CitationValidationError):
            citation_repository.create_from_selected_candidate(
                project_id=foreign_project_id,
                retrieval_trace_id=hybrid_response.trace_id,
                document_chunk_id=matching_chunk_id,
            )
        analysis_repository = SqlAlchemyRequirementAnalysisRepository.from_database_url(
            database_url
        )
        analysis_service = RequirementAnalysisService(
            citation_repository=citation_repository,
            repository=analysis_repository,
        )

        run = analysis_service.analyze(
            project_id=project_id,
            citation_ids=(citation.id,),
        )
        assert run.findings

        reloaded_repository = SqlAlchemyRequirementAnalysisRepository.from_database_url(
            database_url
        )
        reloaded = reloaded_repository.get_for_project(
            project_id=project_id,
            run_id=run.id,
        )

        assert reloaded is not None
        assert reloaded.id == run.id
        assert reloaded.project_id == project_id
        assert reloaded.analyzer_version == "requirement-quality-rules/v1"
        assert reloaded.citation_ids == (citation.id,)
        assert reloaded.findings == run.findings
        assert all(
            evidence.citation_id == citation.id
            for finding in reloaded.findings
            for evidence in finding.evidence
        )

        assert (
            reloaded_repository.get_for_project(
                project_id=foreign_project_id,
                run_id=run.id,
            )
            is None
        )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE requirement_findings, requirement_analysis_runs, "
                    "citations, parser_jobs, document_intakes, retrieval_trace_candidates, "
                    "retrieval_traces, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, "
                    "source_locations, document_versions, documents, "
                    "parser_versions, analysis_runs, projects"
                )
            )
        engine.dispose()
