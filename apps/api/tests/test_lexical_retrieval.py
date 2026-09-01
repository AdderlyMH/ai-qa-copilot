from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func
from sqlalchemy.dialects import postgresql

from ai_qa_copilot_api.documents import DocumentChunkRecord
from ai_qa_copilot_api.lexical_retrieval import (
    DEFAULT_LEXICAL_RESULT_LIMIT,
    LEXICAL_RETRIEVAL_VERSION,
    MAX_LEXICAL_RESULT_LIMIT,
    LexicalCandidate,
    LexicalRetrievalFilters,
    LexicalRetrievalService,
    LexicalRetrievalUnavailable,
    lexical_retrieval_from_environment,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000801")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000802")
CHUNK_ID = UUID("00000000-0000-0000-0000-000000000803")
LOCATION_ID = UUID("00000000-0000-0000-0000-000000000804")


class FakeLexicalStore:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, LexicalRetrievalFilters, int]] = []

    def search(
        self,
        *,
        project_id: UUID,
        query: str,
        filters: LexicalRetrievalFilters,
        limit: int,
    ) -> tuple[LexicalCandidate, ...]:
        self.calls.append((project_id, query, filters, limit))
        return (
            LexicalCandidate(
                chunk_id=CHUNK_ID,
                project_id=project_id,
                document_version_id=VERSION_ID,
                source_location_id=LOCATION_ID,
                document_type="markdown",
                chunking_version="chunking-v1",
                ordinal=0,
                normalized_text="FR-AUTH-001 requires authentication.",
                score=0.5,
                rank=1,
            ),
        )


def test_service_normalizes_query_and_preserves_project_scope() -> None:
    store = FakeLexicalStore()
    service = LexicalRetrievalService(store)

    response = service.search(project_id=PROJECT_ID, query="  FR-AUTH-001   ")

    assert response.retrieval_version == LEXICAL_RETRIEVAL_VERSION
    assert response.project_id == PROJECT_ID
    assert response.query == "FR-AUTH-001"
    assert response.candidates[0].project_id == PROJECT_ID
    assert store.calls == [
        (
            PROJECT_ID,
            "FR-AUTH-001",
            LexicalRetrievalFilters(),
            DEFAULT_LEXICAL_RESULT_LIMIT,
        )
    ]


def test_service_passes_all_deterministic_filters() -> None:
    store = FakeLexicalStore()
    service = LexicalRetrievalService(store)
    filters = LexicalRetrievalFilters(
        document_version_ids=(VERSION_ID,),
        document_types=("markdown",),
        chunking_version="chunking-v1",
    )

    service.search(
        project_id=PROJECT_ID,
        query="status 401",
        filters=filters,
        limit=7,
    )

    assert store.calls == [(PROJECT_ID, "status 401", filters, 7)]


@pytest.mark.parametrize("query", ["", "   ", "---", "!!!"])
def test_service_rejects_queries_without_searchable_text(query: str) -> None:
    service = LexicalRetrievalService(FakeLexicalStore())

    with pytest.raises(ValueError, match="searchable text"):
        service.search(project_id=PROJECT_ID, query=query)


@pytest.mark.parametrize("limit", [0, -1, MAX_LEXICAL_RESULT_LIMIT + 1])
def test_service_rejects_unbounded_result_limits(limit: int) -> None:
    service = LexicalRetrievalService(FakeLexicalStore())

    with pytest.raises(ValueError, match="result limit"):
        service.search(project_id=PROJECT_ID, query="auth", limit=limit)


def test_filters_reject_blank_values() -> None:
    with pytest.raises(ValueError, match="Document type"):
        LexicalRetrievalFilters(document_types=("",)).validate()
    with pytest.raises(ValueError, match="Chunking version"):
        LexicalRetrievalFilters(chunking_version="  ").validate()


def test_postgresql_fts_expression_uses_simple_configuration() -> None:
    query_text = func.plainto_tsquery("simple", "FR-AUTH-001")
    search_vector = func.to_tsvector("simple", DocumentChunkRecord.normalized_text)
    compiled = str(
        search_vector.op("@@")(query_text).compile(dialect=postgresql.dialect())
    )

    assert "to_tsvector" in compiled
    assert "plainto_tsquery" in compiled
    assert "@@" in compiled


def test_unavailable_database_url_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(LexicalRetrievalUnavailable):
        lexical_retrieval_from_environment()
