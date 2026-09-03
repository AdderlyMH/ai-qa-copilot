from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.citations import (
    CitationValidationError,
    SqlAlchemyCitationRepository,
)
from ai_qa_copilot_api.documents import (
    DocumentChunkRecord,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
    ParserVersionRecord,
    RetrievalTraceCandidateRecord,
    RetrievalTraceRecord,
    SourceLocationRecord,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import Base, ProjectRecord, SqlAlchemyProjectRepository


TIMESTAMP = datetime(2026, 9, 3, tzinfo=timezone.utc)
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000a01")
FOREIGN_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000a02")
TRACE_ID = UUID("00000000-0000-0000-0000-000000000a03")
CHUNK_ID = UUID("00000000-0000-0000-0000-000000000a04")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000a05")


@pytest.fixture
def sessions(tmp_path: Path) -> Generator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'citations.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    engine.dispose()


def seed_selected_candidate(sessions: sessionmaker[Session]) -> None:
    parser_id = UUID("00000000-0000-0000-0000-000000000a06")
    document_id = UUID("00000000-0000-0000-0000-000000000a07")
    version_id = UUID("00000000-0000-0000-0000-000000000a08")
    location_id = UUID("00000000-0000-0000-0000-000000000a09")
    section_id = UUID("00000000-0000-0000-0000-000000000a10")
    trace_candidate_id = UUID("00000000-0000-0000-0000-000000000a11")
    with sessions.begin() as session:
        session.add_all(
            [
                ProjectRecord(
                    id=PROJECT_ID,
                    name="Citation project",
                    description=None,
                    created_at=TIMESTAMP,
                    archived_at=None,
                ),
                ProjectRecord(
                    id=FOREIGN_PROJECT_ID,
                    name="Foreign project",
                    description=None,
                    created_at=TIMESTAMP,
                    archived_at=None,
                ),
                ParserVersionRecord(
                    id=parser_id,
                    parser_name="markdown",
                    parser_version="v1",
                    normalization_version="normalization-v1",
                    created_at=TIMESTAMP,
                ),
                DocumentRecord(
                    id=document_id,
                    project_id=PROJECT_ID,
                    document_type="markdown",
                    display_name="checkout.md",
                    created_at=TIMESTAMP,
                ),
                DocumentVersionRecord(
                    id=version_id,
                    document_id=document_id,
                    parser_version_id=parser_id,
                    version_number=1,
                    content_sha256="a" * 64,
                    byte_size=42,
                    content_type="text/markdown",
                    created_at=TIMESTAMP,
                ),
                SourceLocationRecord(
                    id=location_id,
                    document_version_id=version_id,
                    location_kind="line_range",
                    heading="Checkout",
                    line_start=12,
                    line_end=14,
                    page_start=None,
                    page_end=None,
                    json_pointer=None,
                ),
                DocumentSectionRecord(
                    id=section_id,
                    document_version_id=version_id,
                    source_location_id=location_id,
                    ordinal=0,
                    section_key="REQ-CHECKOUT-001",
                    normalized_text="The cart ID is required before checkout.",
                    content_sha256="b" * 64,
                ),
                DocumentChunkRecord(
                    id=CHUNK_ID,
                    document_version_id=version_id,
                    document_section_id=section_id,
                    source_location_id=location_id,
                    ordinal=0,
                    normalized_text="The cart ID is required before checkout.",
                    content_sha256="b" * 64,
                    chunking_version="chunking-v1",
                ),
                RetrievalTraceRecord(
                    id=TRACE_ID,
                    project_id=PROJECT_ID,
                    retrieval_version="hybrid-v1",
                    fusion_method="reciprocal-rank-fusion-v1",
                    query="checkout cart ID",
                    query_embedding=[0.5, 0.5],
                    embedding_model="embedding-test-v1",
                    embedding_version="embedding-v1",
                    document_version_ids=[str(version_id)],
                    document_types=["markdown"],
                    chunking_version="chunking-v1",
                    candidate_limit=10,
                    result_limit=10,
                    created_at=TIMESTAMP,
                ),
                RetrievalTraceCandidateRecord(
                    id=trace_candidate_id,
                    retrieval_trace_id=TRACE_ID,
                    document_chunk_id=CHUNK_ID,
                    lexical_score=0.4,
                    lexical_rank=1,
                    semantic_distance=0.1,
                    semantic_rank=1,
                    fusion_score=0.03,
                    final_rank=1,
                ),
            ]
        )


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


def test_selected_candidate_creates_immutable_citation_and_source_view(
    sessions: sessionmaker[Session],
) -> None:
    seed_selected_candidate(sessions)
    repository = SqlAlchemyCitationRepository(
        sessions, id_factory=lambda: CITATION_ID, clock=lambda: TIMESTAMP
    )

    citation = repository.create_from_selected_candidate(
        project_id=PROJECT_ID, retrieval_trace_id=TRACE_ID, document_chunk_id=CHUNK_ID
    )
    repeated = repository.create_from_selected_candidate(
        project_id=PROJECT_ID, retrieval_trace_id=TRACE_ID, document_chunk_id=CHUNK_ID
    )

    assert citation == repeated
    assert citation.id == CITATION_ID
    assert citation.document_version_id == UUID("00000000-0000-0000-0000-000000000a08")
    assert citation.source_location.heading == "Checkout"
    assert citation.source_location.line_start == 12
    assert citation.passage == "The cart ID is required before checkout."

    app = create_app(
        local_bypass_settings(),
        project_repository=SqlAlchemyProjectRepository(sessions),
        citation_repository=repository,
    )
    with TestClient(app) as client:
        response = client.get(f"/projects/{PROJECT_ID}/citations/{CITATION_ID}")

    assert response.status_code == 200
    assert response.json()["passage"] == citation.passage
    assert response.json()["source_location"]["heading"] == "Checkout"
    assert UUID(response.headers["X-Correlation-ID"])


def test_invalid_or_foreign_citations_are_rejected(
    sessions: sessionmaker[Session],
) -> None:
    seed_selected_candidate(sessions)
    repository = SqlAlchemyCitationRepository(
        sessions, id_factory=lambda: CITATION_ID, clock=lambda: TIMESTAMP
    )
    citation = repository.create_from_selected_candidate(
        project_id=PROJECT_ID, retrieval_trace_id=TRACE_ID, document_chunk_id=CHUNK_ID
    )

    with pytest.raises(CitationValidationError):
        repository.create_from_selected_candidate(
            project_id=FOREIGN_PROJECT_ID,
            retrieval_trace_id=TRACE_ID,
            document_chunk_id=CHUNK_ID,
        )

    app = create_app(
        local_bypass_settings(),
        project_repository=SqlAlchemyProjectRepository(sessions),
        citation_repository=repository,
    )
    with TestClient(app) as client:
        foreign = client.get(f"/projects/{FOREIGN_PROJECT_ID}/citations/{citation.id}")
        missing = client.get(
            "/projects/00000000-0000-0000-0000-000000000a02/"
            "citations/00000000-0000-0000-0000-000000000a12"
        )

    assert foreign.status_code == 404
    assert foreign.json() == {"detail": "Citation not found"}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Citation not found"}
