"""PostgreSQL-backed project API integration evidence for ``db-check`` only."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
import logging

from ai_qa_copilot_api.audit import AUTHORIZATION_AUDIT_LOGGER
from ai_qa_copilot_api.projects import SqlAlchemyProjectRepository
from ai_qa_copilot_api.analysis_runs import (
    AnalysisRunService,
    SqlAlchemyAnalysisRunRepository,
)
from ai_qa_copilot_api.auth import (
    AppEnvironment,
    AuthSettings,
    LocalDevelopmentOwnerPrincipal,
)
from ai_qa_copilot_api.citations import (
    CitationValidationError,
    SqlAlchemyCitationRepository,
)
from ai_qa_copilot_api.finding_feedback import (
    FindingFeedbackAction,
    FindingFeedbackService,
    SqlAlchemyFindingFeedbackRepository,
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
from ai_qa_copilot_api.execution_approvals import (
    ExecutionApprovalConflict,
    ExecutionApprovalService,
    SqlAlchemyExecutionApprovalRepository,
)
from ai_qa_copilot_api.execution_plans import ExecutionPlanV1, build_execution_plan
from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    GeneratedAssertionV1,
    GeneratedTestCaseV1,
    GeneratedTestKind,
    HttpMethod,
    RequestTemplateV1,
)
from ai_qa_copilot_api.documents import (
    ExecutionJobState,
    ExecutionResultOutcome,
    ExecutionResultRecord,
)
from ai_qa_copilot_api.execution_results import (
    ExecutionResultPayload,
    ExecutionResultRejected,
    SqlAlchemyExecutionResultRepository,
)
from ai_qa_copilot_api.execution_jobs import SqlAlchemyExecutionJobQueue


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


class ApprovalClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def execution_approval_plan(*, quantity: int) -> ExecutionPlanV1:
    return build_execution_plan(
        generated_test_case=GeneratedTestCaseV1(
            id=UUID("00000000-0000-0000-0000-000000000901"),
            title="Create a PostgreSQL synthetic order",
            kind=GeneratedTestKind.POSITIVE,
            source_finding_id=UUID("00000000-0000-0000-0000-000000000902"),
            citation_ids=(UUID("00000000-0000-0000-0000-000000000903"),),
            request=RequestTemplateV1(
                method=HttpMethod.POST,
                path="/orders",
                query=(),
                headers=(),
                json_body={"quantity": quantity},
            ),
            assertions=(
                GeneratedAssertionV1(
                    target=AssertionTarget.STATUS_CODE,
                    selector=None,
                    operator=AssertionOperator.EQUALS,
                    expected_value=201,
                ),
            ),
        ),
        target_id="synthetic-order-api",
    )


def execution_result_payload(
    *,
    outcome: ExecutionResultOutcome,
    failure_code: str | None,
    transport_send_count: int = 1,
) -> ExecutionResultPayload:
    return ExecutionResultPayload(
        outcome=outcome,
        failure_code=failure_code,
        assertion_results_json='[{"passed":true,"target":"status_code"}]',
        request_evidence_json=(
            '{"headers":[],"method":"POST",'
            '"url":"https://ai-qa-sandbox.onrender.com/api/orders"}'
        ),
        response_evidence_json=('{"body_bytes":24,"headers":[],"status_code":201}'),
        transport_send_count=transport_send_count,
    )


def truncate_postgres_approval_test_data(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE quality_report_revisions, execution_results, execution_jobs, "
                "execution_approvals, finding_feedback, requirement_findings, "
                "requirement_analysis_runs, citations, parser_jobs, "
                "document_intakes, retrieval_trace_candidates, retrieval_traces, "
                "document_chunk_embeddings, embedding_cache_entries, "
                "document_chunks, document_sections, source_locations, "
                "document_versions, documents, parser_versions, "
                "analysis_runs, projects"
            )
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
                    "TRUNCATE TABLE quality_report_revisions, execution_results, execution_jobs, execution_approvals, "
                    "finding_feedback, requirement_findings, "
                    "requirement_analysis_runs, "
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
                    "TRUNCATE TABLE quality_report_revisions, execution_results, execution_jobs, execution_approvals, "
                    "finding_feedback, requirement_findings, "
                    "requirement_analysis_runs, "
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
                    "TRUNCATE TABLE quality_report_revisions, execution_results, execution_jobs, execution_approvals, "
                    "finding_feedback, requirement_findings, "
                    "requirement_analysis_runs, "
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
                    "TRUNCATE TABLE quality_report_revisions, execution_results, execution_jobs, execution_approvals, "
                    "finding_feedback, requirement_findings, "
                    "requirement_analysis_runs, "
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
                    "TRUNCATE TABLE quality_report_revisions, execution_results, execution_jobs, execution_approvals, "
                    "finding_feedback, requirement_findings, "
                    "requirement_analysis_runs, "
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
        feedback_service = FindingFeedbackService(
            requirement_analysis_repository=reloaded_repository,
            repository=SqlAlchemyFindingFeedbackRepository.from_database_url(
                database_url
            ),
        )
        feedback = feedback_service.record(
            project_id=project_id,
            requirement_analysis_run_id=run.id,
            requirement_finding_id=run.findings[0].id,
            action=FindingFeedbackAction.ANNOTATE,
            annotation="Retain this finding for the review meeting.",
            reviewer=LocalDevelopmentOwnerPrincipal(),
        )

        reloaded_feedback = SqlAlchemyFindingFeedbackRepository.from_database_url(
            database_url
        ).list_for_finding(
            project_id=project_id,
            requirement_analysis_run_id=run.id,
            requirement_finding_id=run.findings[0].id,
        )

        assert reloaded_feedback == (feedback,)
        assert feedback.project_id == project_id
        assert feedback.requirement_analysis_run_id == run.id
        assert feedback.requirement_finding_id == run.findings[0].id
        assert feedback.citation_ids == (citation.id,)
        assert feedback.action is FindingFeedbackAction.ANNOTATE
        assert feedback.annotation == "Retain this finding for the review meeting."
        assert feedback.reviewer_id == "local-development-owner"
        assert feedback.reviewer_authentication_source == "local_bypass"
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
                    "TRUNCATE TABLE quality_report_revisions, execution_results, execution_jobs, execution_approvals, "
                    "finding_feedback, requirement_findings, "
                    "requirement_analysis_runs, "
                    "citations, parser_jobs, document_intakes, retrieval_trace_candidates, "
                    "retrieval_traces, document_chunk_embeddings, "
                    "embedding_cache_entries, document_chunks, document_sections, "
                    "source_locations, document_versions, documents, "
                    "parser_versions, analysis_runs, projects"
                )
            )
        engine.dispose()


@pytest.mark.postgres_integration
def test_postgres_execution_approval_expires_and_rejects_replay() -> None:
    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    project_id = uuid4()
    clock = ApprovalClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    repository = SqlAlchemyExecutionApprovalRepository(sessions, clock=clock)
    service = ExecutionApprovalService(repository)

    try:
        truncate_postgres_approval_test_data(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, name, description, created_at, archived_at) "
                    "VALUES (:id, 'Approval evidence', NULL, "
                    "CURRENT_TIMESTAMP, NULL)"
                ),
                {"id": project_id},
            )

        replay_plan = execution_approval_plan(quantity=2)
        service.approve(
            project_id=project_id,
            plan=replay_plan,
            expected_plan_hash=replay_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )

        claimed = repository.consume(
            project_id=project_id,
            plan_id=replay_plan.id,
            plan_hash=replay_plan.plan_hash,
        )
        replay = repository.consume(
            project_id=project_id,
            plan_id=replay_plan.id,
            plan_hash=replay_plan.plan_hash,
        )

        assert claimed is not None
        assert claimed.consumed_at == clock.current
        assert replay is None

        expiring_plan = execution_approval_plan(quantity=3)
        expiring = service.approve(
            project_id=project_id,
            plan=expiring_plan,
            expected_plan_hash=expiring_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        clock.current = expiring.expires_at

        assert (
            repository.consume(
                project_id=project_id,
                plan_id=expiring_plan.id,
                plan_hash=expiring_plan.plan_hash,
            )
            is None
        )
    finally:
        truncate_postgres_approval_test_data(engine)
        engine.dispose()


@pytest.mark.postgres_integration
def test_postgres_execution_approval_concurrency_allows_one_claim_and_one_create() -> (
    None
):
    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    project_id = uuid4()
    clock = ApprovalClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    repository = SqlAlchemyExecutionApprovalRepository(sessions, clock=clock)
    service = ExecutionApprovalService(repository)

    try:
        truncate_postgres_approval_test_data(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, name, description, created_at, archived_at) "
                    "VALUES (:id, 'Concurrent approval evidence', NULL, "
                    "CURRENT_TIMESTAMP, NULL)"
                ),
                {"id": project_id},
            )

        claim_plan = execution_approval_plan(quantity=4)
        service.approve(
            project_id=project_id,
            plan=claim_plan,
            expected_plan_hash=claim_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )

        claim_gate = Barrier(2)

        def claim() -> bool:
            claim_gate.wait()
            return (
                repository.consume(
                    project_id=project_id,
                    plan_id=claim_plan.id,
                    plan_hash=claim_plan.plan_hash,
                )
                is not None
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            claim_results = tuple(
                future.result()
                for future in (
                    executor.submit(claim),
                    executor.submit(claim),
                )
            )

        assert claim_results.count(True) == 1

        duplicate_plan = execution_approval_plan(quantity=5)
        creation_gate = Barrier(2)

        def create_approval() -> bool:
            creation_gate.wait()
            try:
                service.approve(
                    project_id=project_id,
                    plan=duplicate_plan,
                    expected_plan_hash=duplicate_plan.plan_hash,
                    approver=LocalDevelopmentOwnerPrincipal(),
                    comment=None,
                )
            except ExecutionApprovalConflict:
                return False
            return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            creation_results = tuple(
                future.result()
                for future in (
                    executor.submit(create_approval),
                    executor.submit(create_approval),
                )
            )

        assert creation_results.count(True) == 1
    finally:
        truncate_postgres_approval_test_data(engine)
        engine.dispose()


@pytest.mark.postgres_integration
def test_postgres_execution_job_claim_is_durable_and_single_winner() -> None:
    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    project_id = uuid4()
    clock = ApprovalClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    approval_repository = SqlAlchemyExecutionApprovalRepository(
        sessions,
        clock=clock,
    )
    approval_service = ExecutionApprovalService(approval_repository)
    queue = SqlAlchemyExecutionJobQueue(sessions, clock=clock)

    try:
        truncate_postgres_approval_test_data(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, name, description, created_at, archived_at) "
                    "VALUES (:id, 'Execution-job evidence', NULL, "
                    "CURRENT_TIMESTAMP, NULL)"
                ),
                {"id": project_id},
            )

        immutable_plan = execution_approval_plan(quantity=6)
        approval = approval_service.approve(
            project_id=project_id,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)

        claim_gate = Barrier(2)

        def claim() -> bool:
            claim_gate.wait()
            return queue.claim_next() is not None

        with ThreadPoolExecutor(max_workers=2) as executor:
            claim_results = tuple(
                future.result()
                for future in (
                    executor.submit(claim),
                    executor.submit(claim),
                )
            )

        assert claim_results.count(True) == 1

        claimed = queue.get(project_id=project_id, job_id=queued.id)
        assert claimed is not None
        assert claimed.state is ExecutionJobState.RUNNING
        assert claimed.started_at == clock.current
        assert (
            approval_repository.consume(
                project_id=project_id,
                plan_id=immutable_plan.id,
                plan_hash=immutable_plan.plan_hash,
            )
            is None
        )
    finally:
        truncate_postgres_approval_test_data(engine)
        engine.dispose()


@pytest.mark.postgres_integration
def test_postgres_execution_job_expiry_and_cancellation_prevent_claims() -> None:
    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    project_id = uuid4()
    clock = ApprovalClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    approval_repository = SqlAlchemyExecutionApprovalRepository(
        sessions,
        clock=clock,
    )
    approval_service = ExecutionApprovalService(approval_repository)
    queue = SqlAlchemyExecutionJobQueue(sessions, clock=clock)

    try:
        truncate_postgres_approval_test_data(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, name, description, created_at, archived_at) "
                    "VALUES (:id, 'Execution-job rejection evidence', NULL, "
                    "CURRENT_TIMESTAMP, NULL)"
                ),
                {"id": project_id},
            )

        expired_plan = execution_approval_plan(quantity=7)
        expired_approval = approval_service.approve(
            project_id=project_id,
            plan=expired_plan,
            expected_plan_hash=expired_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        expired_job = queue.enqueue(approval=expired_approval)
        clock.current = expired_approval.expires_at

        assert queue.claim_next() is None

        expired = queue.get(project_id=project_id, job_id=expired_job.id)
        assert expired is not None
        assert expired.state is ExecutionJobState.FAILED
        assert expired.started_at == clock.current
        assert expired.finished_at == clock.current

        cancellable_plan = execution_approval_plan(quantity=8)
        cancellable_approval = approval_service.approve(
            project_id=project_id,
            plan=cancellable_plan,
            expected_plan_hash=cancellable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        cancellable_job = queue.enqueue(approval=cancellable_approval)

        cancelled = queue.cancel(
            project_id=project_id,
            job_id=cancellable_job.id,
        )

        assert cancelled is not None
        assert cancelled.state is ExecutionJobState.CANCELLED
        assert cancelled.cancel_requested_at == clock.current
        assert cancelled.cancelled_at == clock.current
        assert queue.claim_next() is None
    finally:
        truncate_postgres_approval_test_data(engine)
        engine.dispose()


@pytest.mark.postgres_integration
def test_postgres_execution_result_completion_is_durable_and_idempotent() -> None:
    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    project_id = uuid4()
    clock = ApprovalClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    approval_repository = SqlAlchemyExecutionApprovalRepository(
        sessions,
        clock=clock,
    )
    approval_service = ExecutionApprovalService(approval_repository)
    queue = SqlAlchemyExecutionJobQueue(sessions, clock=clock)
    results = SqlAlchemyExecutionResultRepository(sessions, clock=clock)

    try:
        truncate_postgres_approval_test_data(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, name, description, created_at, archived_at) "
                    "VALUES (:id, 'Execution-result evidence', NULL, "
                    "CURRENT_TIMESTAMP, NULL)"
                ),
                {"id": project_id},
            )

        immutable_plan = execution_approval_plan(quantity=9)
        approval = approval_service.approve(
            project_id=project_id,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)
        claimed = queue.claim_next()
        assert claimed is not None

        payload = execution_result_payload(
            outcome=ExecutionResultOutcome.SUCCEEDED,
            failure_code=None,
        )
        stored = results.record(
            project_id=project_id,
            job_id=claimed.job.id,
            payload=payload,
        )
        repeated = results.record(
            project_id=project_id,
            job_id=claimed.job.id,
            payload=payload,
        )

        assert repeated == stored
        assert stored.execution_job_id == queued.id
        assert stored.outcome is ExecutionResultOutcome.SUCCEEDED
        assert stored.failure_code is None
        assert stored.recorded_at == clock.current

        persisted = results.get(
            project_id=project_id,
            job_id=queued.id,
        )
        assert persisted == stored

        completed = queue.get(project_id=project_id, job_id=queued.id)
        assert completed is not None
        assert completed.state is ExecutionJobState.SUCCEEDED
        assert completed.finished_at == clock.current
        assert completed.cancelled_at is None
    finally:
        truncate_postgres_approval_test_data(engine)
        engine.dispose()


@pytest.mark.postgres_integration
def test_postgres_execution_result_conflicts_have_exactly_one_winner() -> None:
    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    project_id = uuid4()
    clock = ApprovalClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    approval_repository = SqlAlchemyExecutionApprovalRepository(
        sessions,
        clock=clock,
    )
    approval_service = ExecutionApprovalService(approval_repository)
    queue = SqlAlchemyExecutionJobQueue(sessions, clock=clock)
    results = SqlAlchemyExecutionResultRepository(sessions, clock=clock)

    try:
        truncate_postgres_approval_test_data(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, name, description, created_at, archived_at) "
                    "VALUES (:id, 'Execution-result race evidence', NULL, "
                    "CURRENT_TIMESTAMP, NULL)"
                ),
                {"id": project_id},
            )

        immutable_plan = execution_approval_plan(quantity=10)
        approval = approval_service.approve(
            project_id=project_id,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)
        claimed = queue.claim_next()
        assert claimed is not None

        claim_gate = Barrier(2)

        def record(payload: ExecutionResultPayload) -> bool:
            claim_gate.wait()
            try:
                results.record(
                    project_id=project_id,
                    job_id=claimed.job.id,
                    payload=payload,
                )
            except ExecutionResultRejected:
                return False
            return True

        successful_payload = execution_result_payload(
            outcome=ExecutionResultOutcome.SUCCEEDED,
            failure_code=None,
        )
        failed_payload = execution_result_payload(
            outcome=ExecutionResultOutcome.FAILED,
            failure_code="assertions_failed",
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(
                future.result()
                for future in (
                    executor.submit(record, successful_payload),
                    executor.submit(record, failed_payload),
                )
            )

        assert outcomes.count(True) == 1

        persisted = results.get(
            project_id=project_id,
            job_id=queued.id,
        )
        assert persisted is not None
        assert persisted.outcome in {
            ExecutionResultOutcome.SUCCEEDED,
            ExecutionResultOutcome.FAILED,
        }

        completed = queue.get(project_id=project_id, job_id=queued.id)
        assert completed is not None
        expected_state = {
            ExecutionResultOutcome.SUCCEEDED: ExecutionJobState.SUCCEEDED,
            ExecutionResultOutcome.FAILED: ExecutionJobState.FAILED,
        }[persisted.outcome]
        assert completed.state is expected_state
        assert completed.finished_at == clock.current
    finally:
        truncate_postgres_approval_test_data(engine)
        engine.dispose()


@pytest.mark.postgres_integration
def test_postgres_evidence_view_redacts_without_mutating_stored_results(
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    projects = SqlAlchemyProjectRepository(sessions)
    approvals = SqlAlchemyExecutionApprovalRepository(sessions)
    queue = SqlAlchemyExecutionJobQueue(sessions)
    results = SqlAlchemyExecutionResultRepository(sessions)
    canary = "exec-006-postgres-display-canary"

    try:
        truncate_postgres_approval_test_data(engine)

        project = projects.create(
            name="PostgreSQL evidence viewer",
            description=None,
        )
        other_project = projects.create(
            name="Other evidence project",
            description=None,
        )
        plan = execution_approval_plan(quantity=11)
        approval = ExecutionApprovalService(approvals).approve(
            project_id=project.id,
            plan=plan,
            expected_plan_hash=plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)
        claimed = queue.claim_next()
        assert claimed is not None
        assert claimed.job.id == queued.id

        stored = results.record(
            project_id=project.id,
            job_id=queued.id,
            payload=execution_result_payload(
                outcome=ExecutionResultOutcome.SUCCEEDED,
                failure_code=None,
            ),
        )

        # Simulate an unsafe historical record in the isolated test database.
        # Normal writes still go through the repository's redaction checks.
        with sessions.begin() as session:
            record = session.get(ExecutionResultRecord, stored.id)
            assert record is not None
            record.request_evidence = {
                "method": "POST",
                "url": (
                    f"https://ai-qa-sandbox.onrender.com/api/orders?token={canary}"
                ),
                "headers": [["X-Api-Token", canary]],
                "json_body": {"password": canary, "quantity": 11},
            }
            record.response_evidence = {
                "status_code": 201,
                "elapsed_ms": 37,
                "headers": [["Set-Cookie", canary]],
                "json_body": {
                    "order_id": "ORDER-1001",
                    "nested": {"secret": canary},
                },
            }

        before = results.get(project_id=project.id, job_id=queued.id)
        assert before is not None
        assert canary in (before.request_evidence_json or "")
        assert canary in (before.response_evidence_json or "")
        job_before = queue.get(project_id=project.id, job_id=queued.id)

        app = create_app(
            local_bypass_settings(),
            project_repository=projects,
            execution_approval_repository=approvals,
            execution_job_queue=queue,
            execution_result_repository=results,
        )
        caplog.clear()
        caplog.set_level(logging.INFO, logger=AUTHORIZATION_AUDIT_LOGGER)

        path = f"/projects/{project.id}/execution-jobs/{queued.id}/evidence"
        with TestClient(app) as http:
            first = http.get(path)
            repeated = http.get(path)
            foreign = http.get(
                f"/projects/{other_project.id}/execution-jobs/{queued.id}/evidence"
            )

        assert first.status_code == 200
        assert repeated.status_code == 200
        assert repeated.json() == first.json()

        body = first.json()
        assert body["id"] == str(stored.id)
        assert body["execution_job_id"] == str(queued.id)
        assert body["outcome"] == "succeeded"
        assert body["response_status_code"] == 201
        assert body["response_elapsed_ms"] == 37
        assert body["transport_send_count"] == 1
        assert body["request_evidence"]["headers"] == [["X-Api-Token", "[REDACTED]"]]
        assert body["request_evidence"]["json_body"]["password"] == "[REDACTED]"
        assert body["response_evidence"]["headers"] == [["Set-Cookie", "[REDACTED]"]]
        assert (
            body["response_evidence"]["json_body"]["nested"]["secret"] == "[REDACTED]"
        )

        assert foreign.status_code == 404
        assert foreign.json() == {"detail": "Execution job not found"}

        for response in (first, repeated, foreign):
            assert canary not in response.text
            assert UUID(response.headers["X-Correlation-ID"])

        audit_records = [
            record
            for record in caplog.records
            if record.name == AUTHORIZATION_AUDIT_LOGGER
        ]
        assert audit_records
        assert canary not in caplog.text

        # Display redaction must not rewrite the immutable stored result.
        after = results.get(project_id=project.id, job_id=queued.id)
        assert after == before
        assert queue.get(project_id=project.id, job_id=queued.id) == job_before
    finally:
        try:
            truncate_postgres_approval_test_data(engine)
        finally:
            engine.dispose()


@pytest.mark.postgres_integration
def test_postgres_failure_analysis_is_read_only_and_never_asserts_root_cause() -> None:
    database_url = isolated_postgres_database_url()
    engine = create_engine(database_url)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    projects = SqlAlchemyProjectRepository(sessions)
    approvals = SqlAlchemyExecutionApprovalRepository(sessions)
    queue = SqlAlchemyExecutionJobQueue(sessions)
    results = SqlAlchemyExecutionResultRepository(sessions)

    try:
        truncate_postgres_approval_test_data(engine)

        project = projects.create(
            name="PostgreSQL failure analysis",
            description=None,
        )
        other_project = projects.create(
            name="Other failure-analysis project",
            description=None,
        )
        plan = execution_approval_plan(quantity=12)
        approval = ExecutionApprovalService(approvals).approve(
            project_id=project.id,
            plan=plan,
            expected_plan_hash=plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)
        claimed = queue.claim_next()
        assert claimed is not None
        assert claimed.job.id == queued.id

        stored = results.record(
            project_id=project.id,
            job_id=queued.id,
            payload=ExecutionResultPayload(
                outcome=ExecutionResultOutcome.FAILED,
                failure_code="assertions_failed",
                assertion_results_json=(
                    '[{"operator":"equals","passed":false,'
                    '"selector":null,"target":"status_code"}]'
                ),
                request_evidence_json=(
                    '{"headers":[],"method":"POST",'
                    '"url":"https://ai-qa-sandbox.onrender.com/api/orders"}'
                ),
                response_evidence_json=(
                    '{"elapsed_ms":41,"headers":[],"status_code":500}'
                ),
                transport_send_count=1,
            ),
        )
        before = results.get(project_id=project.id, job_id=queued.id)
        assert before == stored
        job_before = queue.get(project_id=project.id, job_id=queued.id)

        app = create_app(
            local_bypass_settings(),
            project_repository=projects,
            execution_approval_repository=approvals,
            execution_job_queue=queue,
            execution_result_repository=results,
        )

        path = f"/projects/{project.id}/execution-jobs/{queued.id}/failure-analysis"
        with TestClient(app) as http:
            first = http.get(path)
            repeated = http.get(path)
            foreign = http.get(
                f"/projects/{other_project.id}/execution-jobs/"
                f"{queued.id}/failure-analysis"
            )

        assert first.status_code == 200
        assert repeated.status_code == 200
        assert repeated.json() == first.json()

        body = first.json()
        assert body["execution_job_id"] == str(queued.id)
        assert body["outcome"] == "failed"
        assert body["failure_code"] == "assertions_failed"
        assert body["evidence_sufficiency"] == "insufficient_for_root_cause"
        assert body["root_cause"] is None
        assert [item["code"] for item in body["observations"]] == [
            "terminal_outcome",
            "recorded_failure_code",
            "transport_send_count",
            "response_status_code",
            "response_elapsed_ms",
            "failed_assertion_count",
        ]
        assert body["hypotheses"][0]["code"] == (
            "target_response_did_not_match_approved_expectations"
        )
        assert body["alternatives"][0]["code"] == "approved_expectations_may_be_stale"
        assert body["next_checks"][0]["code"] == (
            "compare_redacted_response_to_approved_plan"
        )

        assert foreign.status_code == 404
        assert foreign.json() == {"detail": "Execution job not found"}

        for response in (first, repeated, foreign):
            assert UUID(response.headers["X-Correlation-ID"])

        # Read-only analysis must not alter durable evidence or job state.
        assert results.get(project_id=project.id, job_id=queued.id) == before
        assert queue.get(project_id=project.id, job_id=queued.id) == job_before
    finally:
        try:
            truncate_postgres_approval_test_data(engine)
        finally:
            engine.dispose()
