"""Bounded linkage from a project retrieval trace to immutable citations.

The caller supplies the injected embedding adapter. This module does not open a
network connection, select a provider, generate an answer, or execute work.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol
from uuid import UUID

from ai_qa_copilot_api.citations import (
    Citation,
    CitationUnavailable,
)
from ai_qa_copilot_api.hybrid_retrieval import (
    DEFAULT_HYBRID_CANDIDATE_LIMIT,
    DEFAULT_HYBRID_RESULT_LIMIT,
    HybridCandidate,
    HybridRetrievalFilters,
    HybridRetrievalResponse,
    HybridRetrievalUnavailable,
)
from ai_qa_copilot_api.indexing import (
    DEFAULT_CHUNKING_VERSION,
    EmbeddingAdapter,
    EmbeddingConfiguration,
    EmbeddingProtocolError,
)
from ai_qa_copilot_api.observability import traced


MAX_RETRIEVAL_QUERY_CHARACTERS = 4_000
RETRIEVAL_CITATION_UNAVAILABLE_DETAIL = "Evidence retrieval is temporarily unavailable"


class RetrievalCitationUnavailable(RuntimeError):
    """Raised when a safe query cannot be linked to durable citations."""


class HybridRetriever(Protocol):
    def retrieve(
        self,
        *,
        project_id: UUID,
        query: str,
        query_embedding: tuple[float, ...],
        filters: HybridRetrievalFilters,
        candidate_limit: int = DEFAULT_HYBRID_CANDIDATE_LIMIT,
        result_limit: int = DEFAULT_HYBRID_RESULT_LIMIT,
    ) -> HybridRetrievalResponse: ...


class CitationBatchWriter(Protocol):
    """Create the requested citation batch in one transaction."""

    def create_from_selected_candidates(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_ids: tuple[UUID, ...],
    ) -> tuple[Citation, ...]: ...


@dataclass(frozen=True)
class LinkedRetrievalCitation:
    """A selected candidate rank and its immutable citation."""

    rank: int
    candidate: HybridCandidate
    citation: Citation


@dataclass(frozen=True)
class RetrievalCitationResult:
    """One durable retrieval trace with citations for its selected chunks."""

    retrieval: HybridRetrievalResponse
    results: tuple[LinkedRetrievalCitation, ...]


class RetrievalCitationService:
    """Embed one bounded query, retrieve project evidence, then cite it atomically."""

    def __init__(
        self,
        *,
        retriever: HybridRetriever,
        citations: CitationBatchWriter,
        embedding_adapter: EmbeddingAdapter,
        embedding: EmbeddingConfiguration = EmbeddingConfiguration(),
        chunking_version: str = DEFAULT_CHUNKING_VERSION,
    ) -> None:
        embedding.validate()
        if not chunking_version.strip():
            raise ValueError("Chunking version must be non-empty")
        self._retriever = retriever
        self._citations = citations
        self._embedding_adapter = embedding_adapter
        self._embedding = embedding
        self._chunking_version = chunking_version

    @traced("retrieval.citation_linkage")
    def retrieve(
        self,
        *,
        project_id: UUID,
        query: str,
        document_version_ids: tuple[UUID, ...] | None = None,
        document_types: tuple[str, ...] | None = None,
        candidate_limit: int = DEFAULT_HYBRID_CANDIDATE_LIMIT,
        result_limit: int = DEFAULT_HYBRID_RESULT_LIMIT,
    ) -> RetrievalCitationResult:
        normalized_query = " ".join(query.split())
        if (
            not normalized_query
            or len(normalized_query) > MAX_RETRIEVAL_QUERY_CHARACTERS
            or not any(character.isalnum() for character in normalized_query)
        ):
            raise ValueError("Retrieval query must contain bounded searchable text")
        filters = HybridRetrievalFilters(
            embedding_model=self._embedding.model,
            embedding_version=self._embedding.version,
            document_version_ids=document_version_ids,
            document_types=document_types,
            chunking_version=self._chunking_version,
        )
        try:
            query_embedding = self._embed_query(normalized_query)
            retrieval = self._retriever.retrieve(
                project_id=project_id,
                query=normalized_query,
                query_embedding=query_embedding,
                filters=filters,
                candidate_limit=candidate_limit,
                result_limit=result_limit,
            )
            if retrieval.project_id != project_id or any(
                candidate.project_id != project_id for candidate in retrieval.candidates
            ):
                raise RetrievalCitationUnavailable(
                    "Retriever returned evidence outside the requested project"
                )
            if not retrieval.candidates:
                return RetrievalCitationResult(retrieval, ())
            if any(
                candidate.rank is None or candidate.rank < 1
                for candidate in retrieval.candidates
            ):
                raise RetrievalCitationUnavailable(
                    "Retriever returned an unselected result"
                )
            citations = self._citations.create_from_selected_candidates(
                project_id=project_id,
                retrieval_trace_id=retrieval.trace_id,
                document_chunk_ids=tuple(
                    candidate.chunk_id for candidate in retrieval.candidates
                ),
            )
        except (
            CitationUnavailable,
            EmbeddingProtocolError,
            HybridRetrievalUnavailable,
        ) as error:
            raise RetrievalCitationUnavailable from error
        if len(citations) != len(retrieval.candidates):
            raise RetrievalCitationUnavailable("Citation result count changed")
        linked: list[LinkedRetrievalCitation] = []
        for candidate, citation in zip(retrieval.candidates, citations, strict=True):
            if (
                candidate.rank is None
                or citation.project_id != project_id
                or citation.retrieval_trace_id != retrieval.trace_id
                or citation.document_chunk_id != candidate.chunk_id
            ):
                raise RetrievalCitationUnavailable(
                    "Citation linkage provenance changed"
                )
            linked.append(LinkedRetrievalCitation(candidate.rank, candidate, citation))
        return RetrievalCitationResult(retrieval, tuple(linked))

    def _embed_query(self, query: str) -> tuple[float, ...]:
        vectors = self._embedding_adapter.embed((query,), self._embedding)
        if len(vectors) != 1:
            raise EmbeddingProtocolError(
                "Query embedding adapter must return one vector"
            )
        try:
            values = tuple(float(value) for value in vectors[0])
        except (TypeError, ValueError) as error:
            raise EmbeddingProtocolError(
                "Query embedding adapter returned invalid values"
            ) from error
        if not values or any(not math.isfinite(value) for value in values):
            raise EmbeddingProtocolError(
                "Query embedding adapter must return finite non-empty vectors"
            )
        return values


class UnavailableRetrievalCitationService:
    """Fail closed until deployment composes a durable retriever and adapter."""

    def retrieve(
        self,
        *,
        project_id: UUID,
        query: str,
        document_version_ids: tuple[UUID, ...] | None = None,
        document_types: tuple[str, ...] | None = None,
        candidate_limit: int = DEFAULT_HYBRID_CANDIDATE_LIMIT,
        result_limit: int = DEFAULT_HYBRID_RESULT_LIMIT,
    ) -> RetrievalCitationResult:
        del (
            project_id,
            query,
            document_version_ids,
            document_types,
            candidate_limit,
            result_limit,
        )
        raise RetrievalCitationUnavailable
