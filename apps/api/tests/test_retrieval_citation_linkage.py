from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import pytest

from ai_qa_copilot_api.citations import Citation, SourceLocation
from ai_qa_copilot_api.hybrid_retrieval import (
    DEFAULT_HYBRID_CANDIDATE_LIMIT,
    DEFAULT_HYBRID_RESULT_LIMIT,
    FUSION_METHOD,
    HYBRID_RETRIEVAL_VERSION,
    HybridCandidate,
    HybridRetrievalFilters,
    HybridRetrievalResponse,
)
from ai_qa_copilot_api.indexing import EmbeddingConfiguration
from ai_qa_copilot_api.retrieval_citation_linkage import (
    RetrievalCitationService,
    RetrievalCitationUnavailable,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000b01")
TRACE_ID = UUID("00000000-0000-0000-0000-000000000b02")
CHUNK_ID = UUID("00000000-0000-0000-0000-000000000b03")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000b04")
NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)


def candidate() -> HybridCandidate:
    return HybridCandidate(
        chunk_id=CHUNK_ID,
        project_id=PROJECT_ID,
        document_version_id=UUID("00000000-0000-0000-0000-000000000b05"),
        source_location_id=UUID("00000000-0000-0000-0000-000000000b06"),
        document_type="markdown",
        chunking_version="chunking-v1",
        ordinal=0,
        normalized_text="REQ-001: Cart IDs are required.",
        lexical_score=0.5,
        lexical_rank=1,
        semantic_distance=0.1,
        semantic_rank=1,
        fusion_score=0.03,
        rank=1,
    )


@dataclass
class FakeEmbedder:
    vectors: tuple[tuple[float, ...], ...] = ((0.25, 0.75),)
    calls: list[tuple[tuple[str, ...], EmbeddingConfiguration]] = field(
        default_factory=list
    )

    def embed(
        self, texts: Sequence[str], configuration: EmbeddingConfiguration
    ) -> Sequence[Sequence[float]]:
        self.calls.append((tuple(texts), configuration))
        return self.vectors


@dataclass
class FakeRetriever:
    response: HybridRetrievalResponse
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def retrieve(
        self,
        *,
        project_id: UUID,
        query: str,
        query_embedding: tuple[float, ...],
        filters: HybridRetrievalFilters,
        candidate_limit: int = DEFAULT_HYBRID_CANDIDATE_LIMIT,
        result_limit: int = DEFAULT_HYBRID_RESULT_LIMIT,
    ) -> HybridRetrievalResponse:
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
        return self.response


@dataclass
class FakeCitations:
    calls: list[tuple[UUID, UUID, tuple[UUID, ...]]] = field(default_factory=list)

    def create_from_selected_candidates(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_ids: tuple[UUID, ...],
    ) -> tuple[Citation, ...]:
        self.calls.append((project_id, retrieval_trace_id, document_chunk_ids))
        return tuple(
            Citation(
                id=CITATION_ID,
                project_id=project_id,
                retrieval_trace_id=retrieval_trace_id,
                document_chunk_id=chunk_id,
                document_version_id=candidate().document_version_id,
                source_location=SourceLocation(
                    id=candidate().source_location_id,
                    location_kind="line_range",
                    heading="Checkout",
                    line_start=2,
                    line_end=2,
                    page_start=None,
                    page_end=None,
                    json_pointer=None,
                ),
                document_type="markdown",
                display_name="requirements.md",
                passage=candidate().normalized_text,
                created_at=NOW,
            )
            for chunk_id in document_chunk_ids
        )


def response(
    *, candidates: tuple[HybridCandidate, ...] = (candidate(),)
) -> HybridRetrievalResponse:
    return HybridRetrievalResponse(
        retrieval_version=HYBRID_RETRIEVAL_VERSION,
        fusion_method=FUSION_METHOD,
        trace_id=TRACE_ID,
        query="Cart identifiers",
        project_id=PROJECT_ID,
        candidates=candidates,
    )


def test_retrieval_embeds_once_and_links_only_selected_project_candidates() -> None:
    embedder = FakeEmbedder()
    retriever = FakeRetriever(response())
    citations = FakeCitations()
    service = RetrievalCitationService(
        retriever=retriever,
        citations=citations,
        embedding_adapter=embedder,
    )

    result = service.retrieve(project_id=PROJECT_ID, query="  Cart   identifiers  ")

    assert embedder.calls == [
        (
            ("Cart identifiers",),
            EmbeddingConfiguration("embedding-test-v1", "embedding-v1"),
        )
    ]
    assert retriever.calls[0][:3] == (
        PROJECT_ID,
        "Cart identifiers",
        (0.25, 0.75),
    )
    filters = retriever.calls[0][3]
    assert isinstance(filters, HybridRetrievalFilters)
    assert (
        filters.embedding_model,
        filters.embedding_version,
        filters.chunking_version,
    ) == (
        "embedding-test-v1",
        "embedding-v1",
        "chunking-v1",
    )
    assert citations.calls == [(PROJECT_ID, TRACE_ID, (CHUNK_ID,))]
    assert result.retrieval.trace_id == TRACE_ID
    assert result.results[0].rank == 1
    assert result.results[0].citation.document_chunk_id == CHUNK_ID


def test_empty_retrieval_does_not_create_citations() -> None:
    citations = FakeCitations()
    service = RetrievalCitationService(
        retriever=FakeRetriever(response(candidates=())),
        citations=citations,
        embedding_adapter=FakeEmbedder(),
    )

    assert service.retrieve(project_id=PROJECT_ID, query="cart").results == ()
    assert citations.calls == []


@pytest.mark.parametrize("vectors", [(), ((),), ((float("nan"),),), ((0.5,), (0.25,))])
def test_invalid_query_embedding_fails_before_retrieval(
    vectors: tuple[tuple[float, ...], ...],
) -> None:
    retriever = FakeRetriever(response())
    service = RetrievalCitationService(
        retriever=retriever,
        citations=FakeCitations(),
        embedding_adapter=FakeEmbedder(vectors=vectors),
    )

    with pytest.raises(RetrievalCitationUnavailable):
        service.retrieve(project_id=PROJECT_ID, query="cart")

    assert retriever.calls == []
