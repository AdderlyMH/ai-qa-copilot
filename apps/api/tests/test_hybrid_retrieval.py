from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from ai_qa_copilot_api.hybrid_retrieval import (
    DEFAULT_HYBRID_CANDIDATE_LIMIT,
    DEFAULT_HYBRID_RESULT_LIMIT,
    FUSION_METHOD,
    HYBRID_RETRIEVAL_VERSION,
    MAX_HYBRID_RESULT_LIMIT,
    HybridCandidate,
    HybridRetrievalFilters,
    HybridRetrievalService,
    HybridRetrievalUnavailable,
    _fuse_candidates,
    hybrid_retrieval_from_environment,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000901")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000902")
LOCATION_ID = UUID("00000000-0000-0000-0000-000000000903")
TRACE_ID = UUID("00000000-0000-0000-0000-000000000904")


def candidate(
    *,
    chunk_id: UUID | None = None,
    lexical_score: float | None = None,
    lexical_rank: int | None = None,
    semantic_distance: float | None = None,
    semantic_rank: int | None = None,
    ordinal: int = 0,
) -> HybridCandidate:
    return HybridCandidate(
        chunk_id=chunk_id or uuid4(),
        project_id=PROJECT_ID,
        document_version_id=VERSION_ID,
        source_location_id=LOCATION_ID,
        document_type="markdown",
        chunking_version="chunking-v1",
        ordinal=ordinal,
        normalized_text="FR-RAG-002 retrieval evidence",
        lexical_score=lexical_score,
        lexical_rank=lexical_rank,
        semantic_distance=semantic_distance,
        semantic_rank=semantic_rank,
        fusion_score=0.0,
        rank=None,
    )


class FakeHybridStore:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def retrieve(
        self,
        *,
        project_id: UUID,
        query: str,
        query_embedding: tuple[float, ...],
        filters: HybridRetrievalFilters,
        candidate_limit: int,
        result_limit: int,
    ) -> tuple[UUID, tuple[HybridCandidate, ...]]:
        self.calls.append(
            (
                project_id,
                query,
                query_embedding,
                filters,
                candidate_limit,
                result_limit,
            )
        )
        return TRACE_ID, (candidate(lexical_score=0.5, lexical_rank=1),)


def filters() -> HybridRetrievalFilters:
    return HybridRetrievalFilters(
        embedding_model="embedding-test-v1",
        embedding_version="embedding-v1",
        document_version_ids=(VERSION_ID,),
        document_types=("markdown",),
        chunking_version="chunking-v1",
    )


def test_service_normalizes_inputs_and_records_hybrid_identity() -> None:
    store = FakeHybridStore()
    service = HybridRetrievalService(store)

    response = service.retrieve(
        project_id=PROJECT_ID,
        query="  FR-RAG-002  ",
        query_embedding=(0.5, 0.25),
        filters=filters(),
    )

    assert response.retrieval_version == HYBRID_RETRIEVAL_VERSION
    assert response.fusion_method == FUSION_METHOD
    assert response.trace_id == TRACE_ID
    assert response.project_id == PROJECT_ID
    assert response.query == "FR-RAG-002"
    assert store.calls == [
        (
            PROJECT_ID,
            "FR-RAG-002",
            (0.5, 0.25),
            filters(),
            DEFAULT_HYBRID_CANDIDATE_LIMIT,
            DEFAULT_HYBRID_RESULT_LIMIT,
        )
    ]


def test_reciprocal_rank_fusion_merges_signals_and_ties_deterministically() -> None:
    shared_id = UUID("00000000-0000-0000-0000-000000000905")
    lexical = (
        candidate(chunk_id=shared_id, lexical_score=0.4, lexical_rank=1, ordinal=2),
        candidate(lexical_score=0.3, lexical_rank=2, ordinal=1),
    )
    semantic = (
        candidate(
            chunk_id=shared_id,
            semantic_distance=0.1,
            semantic_rank=2,
            ordinal=2,
        ),
        candidate(semantic_distance=0.01, semantic_rank=1, ordinal=0),
    )

    traced, selected = _fuse_candidates(
        lexical=lexical, semantic=semantic, result_limit=2
    )

    assert len(traced) == 3
    assert selected[0].chunk_id == shared_id
    assert selected[0].lexical_rank == 1
    assert selected[0].semantic_rank == 2
    assert selected[0].fusion_score == pytest.approx(1 / 61 + 1 / 62)
    assert [result.rank for result in selected] == [1, 2]
    assert traced[-1].rank is None


@pytest.mark.parametrize("query", ["", "  ", "---"])
def test_service_rejects_non_searchable_query(query: str) -> None:
    with pytest.raises(ValueError, match="searchable text"):
        HybridRetrievalService(FakeHybridStore()).retrieve(
            project_id=PROJECT_ID,
            query=query,
            query_embedding=(0.5,),
            filters=filters(),
        )


@pytest.mark.parametrize("embedding", [(), (float("nan"),), (float("inf"),)])
def test_service_rejects_unsafe_query_embeddings(
    embedding: tuple[float, ...],
) -> None:
    with pytest.raises(ValueError, match="Query embedding"):
        HybridRetrievalService(FakeHybridStore()).retrieve(
            project_id=PROJECT_ID,
            query="evidence",
            query_embedding=embedding,
            filters=filters(),
        )


def test_service_rejects_unbounded_candidate_limits() -> None:
    with pytest.raises(ValueError, match="candidate limit"):
        HybridRetrievalService(FakeHybridStore()).retrieve(
            project_id=PROJECT_ID,
            query="evidence",
            query_embedding=(0.5,),
            filters=filters(),
            candidate_limit=MAX_HYBRID_RESULT_LIMIT + 1,
        )


def test_filters_reject_missing_embedding_identity() -> None:
    with pytest.raises(ValueError, match="Embedding model"):
        HybridRetrievalFilters("", "embedding-v1").validate()


def test_unavailable_database_url_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(HybridRetrievalUnavailable):
        hybrid_retrieval_from_environment()
