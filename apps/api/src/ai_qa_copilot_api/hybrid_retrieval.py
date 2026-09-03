"""Project-scoped pgvector retrieval with deterministic reciprocal-rank fusion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
import os
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import Text, bindparam, cast, create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import UserDefinedType

from ai_qa_copilot_api.documents import (
    DocumentChunkEmbeddingRecord,
    DocumentChunkRecord,
    DocumentRecord,
    DocumentVersionRecord,
    EmbeddingCacheRecord,
    RetrievalTraceCandidateRecord,
    RetrievalTraceRecord,
)


HYBRID_RETRIEVAL_VERSION = "hybrid-v1"
FUSION_METHOD = "reciprocal-rank-fusion-v1"
RECIPROCAL_RANK_OFFSET = 60
DEFAULT_HYBRID_CANDIDATE_LIMIT = 20
DEFAULT_HYBRID_RESULT_LIMIT = 20
MAX_HYBRID_RESULT_LIMIT = 100
MAX_QUERY_EMBEDDING_DIMENSIONS = 2_000


class HybridRetrievalUnavailable(RuntimeError):
    """Raised when pgvector retrieval or trace persistence cannot safely complete."""


class PgVectorType(UserDefinedType[object]):
    """Minimal PostgreSQL pgvector type used without a provider-specific SDK."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "vector"


@dataclass(frozen=True)
class HybridRetrievalFilters:
    """Versioned filters enforced before either candidate mode is ranked."""

    embedding_model: str
    embedding_version: str
    document_version_ids: tuple[UUID, ...] | None = None
    document_types: tuple[str, ...] | None = None
    chunking_version: str | None = None

    def validate(self) -> None:
        if not self.embedding_model.strip() or not self.embedding_version.strip():
            raise ValueError("Embedding model and version must be non-empty")
        if self.document_version_ids is not None and not all(
            isinstance(value, UUID) for value in self.document_version_ids
        ):
            raise ValueError("Document version filters must contain UUIDs")
        if self.document_types is not None:
            if not self.document_types or any(
                not value.strip() for value in self.document_types
            ):
                raise ValueError("Document type filters must be non-empty")
        if self.chunking_version is not None and not self.chunking_version.strip():
            raise ValueError("Chunking version filter must be non-empty")


@dataclass(frozen=True)
class HybridCandidate:
    """One immutable chunk with its independent and fused rank inputs."""

    chunk_id: UUID
    project_id: UUID
    document_version_id: UUID
    source_location_id: UUID
    document_type: str
    chunking_version: str
    ordinal: int
    normalized_text: str
    lexical_score: float | None
    lexical_rank: int | None
    semantic_distance: float | None
    semantic_rank: int | None
    fusion_score: float
    rank: int | None


@dataclass(frozen=True)
class HybridRetrievalResponse:
    """Auditable result set including the durable trace that records all candidates."""

    retrieval_version: str
    fusion_method: str
    trace_id: UUID
    query: str
    project_id: UUID
    candidates: tuple[HybridCandidate, ...]


class HybridRetrievalStore(Protocol):
    """Persistence boundary for hybrid candidates and immutable retrieval traces."""

    def retrieve(
        self,
        *,
        project_id: UUID,
        query: str,
        query_embedding: tuple[float, ...],
        filters: HybridRetrievalFilters,
        candidate_limit: int,
        result_limit: int,
    ) -> tuple[UUID, tuple[HybridCandidate, ...]]: ...


class HybridRetrievalService:
    """Validate bounded hybrid inputs before PostgreSQL ranks either signal."""

    def __init__(self, store: HybridRetrievalStore) -> None:
        self._store = store

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
        normalized_query = " ".join(query.split())
        if not normalized_query or not any(
            character.isalnum() for character in normalized_query
        ):
            raise ValueError("Hybrid query must contain searchable text")
        _validate_query_embedding(query_embedding)
        if not 1 <= result_limit <= MAX_HYBRID_RESULT_LIMIT:
            raise ValueError(
                f"Hybrid result limit must be between 1 and {MAX_HYBRID_RESULT_LIMIT}"
            )
        if not result_limit <= candidate_limit <= MAX_HYBRID_RESULT_LIMIT:
            raise ValueError(
                "Hybrid candidate limit must be at least the result limit and at most "
                f"{MAX_HYBRID_RESULT_LIMIT}"
            )
        filters.validate()
        trace_id, candidates = self._store.retrieve(
            project_id=project_id,
            query=normalized_query,
            query_embedding=query_embedding,
            filters=filters,
            candidate_limit=candidate_limit,
            result_limit=result_limit,
        )
        return HybridRetrievalResponse(
            retrieval_version=HYBRID_RETRIEVAL_VERSION,
            fusion_method=FUSION_METHOD,
            trace_id=trace_id,
            query=normalized_query,
            project_id=project_id,
            candidates=candidates,
        )


class SqlAlchemyHybridRetrievalStore:
    """PostgreSQL FTS plus pgvector candidates, persisted with their fusion inputs."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    @classmethod
    def from_database_url(cls, database_url: str) -> "SqlAlchemyHybridRetrievalStore":
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

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
        filters.validate()
        try:
            with self._session_factory.begin() as session:
                lexical = _lexical_candidates(
                    session,
                    project_id=project_id,
                    query=query,
                    filters=filters,
                    limit=candidate_limit,
                )
                semantic = _semantic_candidates(
                    session,
                    project_id=project_id,
                    query_embedding=query_embedding,
                    filters=filters,
                    limit=candidate_limit,
                )
                all_candidates, selected = _fuse_candidates(
                    lexical=lexical, semantic=semantic, result_limit=result_limit
                )
                trace_id = uuid4()
                session.add(
                    RetrievalTraceRecord(
                        id=trace_id,
                        project_id=project_id,
                        retrieval_version=HYBRID_RETRIEVAL_VERSION,
                        fusion_method=FUSION_METHOD,
                        query=query,
                        query_embedding=list(query_embedding),
                        embedding_model=filters.embedding_model,
                        embedding_version=filters.embedding_version,
                        document_version_ids=(
                            [str(value) for value in filters.document_version_ids]
                            if filters.document_version_ids is not None
                            else None
                        ),
                        document_types=(
                            list(filters.document_types)
                            if filters.document_types
                            else None
                        ),
                        chunking_version=filters.chunking_version,
                        candidate_limit=candidate_limit,
                        result_limit=result_limit,
                        created_at=self._clock(),
                    )
                )
                session.add_all(
                    RetrievalTraceCandidateRecord(
                        id=uuid4(),
                        retrieval_trace_id=trace_id,
                        document_chunk_id=candidate.chunk_id,
                        lexical_score=candidate.lexical_score,
                        lexical_rank=candidate.lexical_rank,
                        semantic_distance=candidate.semantic_distance,
                        semantic_rank=candidate.semantic_rank,
                        fusion_score=candidate.fusion_score,
                        final_rank=candidate.rank,
                    )
                    for candidate in all_candidates
                )
                return trace_id, selected
        except SQLAlchemyError as error:
            raise HybridRetrievalUnavailable from error


def hybrid_retrieval_from_environment() -> HybridRetrievalService:
    """Build durable hybrid retrieval only when a database URL is configured."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise HybridRetrievalUnavailable
    return HybridRetrievalService(
        SqlAlchemyHybridRetrievalStore.from_database_url(database_url)
    )


def _validate_query_embedding(query_embedding: tuple[float, ...]) -> None:
    if not query_embedding or len(query_embedding) > MAX_QUERY_EMBEDDING_DIMENSIONS:
        raise ValueError(
            "Query embedding must be non-empty and within the supported dimension limit"
        )
    if any(not math.isfinite(value) for value in query_embedding):
        raise ValueError("Query embedding values must be finite")


def _candidate_statement(*, project_id: UUID, filters: HybridRetrievalFilters) -> Any:
    statement = (
        select(
            DocumentChunkRecord.id,
            DocumentRecord.project_id,
            DocumentChunkRecord.document_version_id,
            DocumentChunkRecord.source_location_id,
            DocumentRecord.document_type,
            DocumentChunkRecord.chunking_version,
            DocumentChunkRecord.ordinal,
            DocumentChunkRecord.normalized_text,
        )
        .join(
            DocumentVersionRecord,
            DocumentChunkRecord.document_version_id == DocumentVersionRecord.id,
        )
        .join(DocumentRecord, DocumentVersionRecord.document_id == DocumentRecord.id)
        .where(DocumentRecord.project_id == project_id)
    )
    if filters.document_version_ids is not None:
        statement = statement.where(
            DocumentChunkRecord.document_version_id.in_(filters.document_version_ids)
        )
    if filters.document_types is not None:
        statement = statement.where(
            DocumentRecord.document_type.in_(filters.document_types)
        )
    if filters.chunking_version is not None:
        statement = statement.where(
            DocumentChunkRecord.chunking_version == filters.chunking_version
        )
    return statement


def _lexical_candidates(
    session: Session,
    *,
    project_id: UUID,
    query: str,
    filters: HybridRetrievalFilters,
    limit: int,
) -> tuple[HybridCandidate, ...]:
    query_text = func.plainto_tsquery("simple", query)
    search_vector = func.to_tsvector("simple", DocumentChunkRecord.normalized_text)
    score = func.ts_rank_cd(search_vector, query_text)
    statement = (
        _candidate_statement(project_id=project_id, filters=filters)
        .add_columns(score.label("lexical_score"))
        .where(search_vector.op("@@")(query_text))
        .order_by(
            score.desc(),
            DocumentChunkRecord.ordinal.asc(),
            DocumentChunkRecord.id.asc(),
        )
        .limit(limit)
    )
    return tuple(
        _candidate_from_row(
            row, lexical_score=float(row.lexical_score), lexical_rank=index
        )
        for index, row in enumerate(session.execute(statement), start=1)
    )


def _semantic_candidates(
    session: Session,
    *,
    project_id: UUID,
    query_embedding: tuple[float, ...],
    filters: HybridRetrievalFilters,
    limit: int,
) -> tuple[HybridCandidate, ...]:
    stored_vector = cast(cast(EmbeddingCacheRecord.values, Text), PgVectorType())
    query_vector = cast(
        bindparam("query_embedding", _pgvector_literal(query_embedding)), PgVectorType()
    )
    distance = stored_vector.op("<=>")(query_vector)
    statement = (
        _candidate_statement(project_id=project_id, filters=filters)
        .join(
            DocumentChunkEmbeddingRecord,
            DocumentChunkEmbeddingRecord.document_chunk_id == DocumentChunkRecord.id,
        )
        .join(
            EmbeddingCacheRecord,
            DocumentChunkEmbeddingRecord.embedding_cache_id == EmbeddingCacheRecord.id,
        )
        .add_columns(distance.label("semantic_distance"))
        .where(
            DocumentChunkEmbeddingRecord.embedding_model == filters.embedding_model,
            DocumentChunkEmbeddingRecord.embedding_version == filters.embedding_version,
            EmbeddingCacheRecord.project_id == project_id,
            EmbeddingCacheRecord.embedding_model == filters.embedding_model,
            EmbeddingCacheRecord.embedding_version == filters.embedding_version,
        )
        .order_by(
            distance.asc(),
            DocumentChunkRecord.ordinal.asc(),
            DocumentChunkRecord.id.asc(),
        )
        .limit(limit)
    )
    return tuple(
        _candidate_from_row(
            row, semantic_distance=float(row.semantic_distance), semantic_rank=index
        )
        for index, row in enumerate(session.execute(statement), start=1)
    )


def _candidate_from_row(
    row: Any,
    *,
    lexical_score: float | None = None,
    lexical_rank: int | None = None,
    semantic_distance: float | None = None,
    semantic_rank: int | None = None,
) -> HybridCandidate:
    return HybridCandidate(
        chunk_id=row.id,
        project_id=row.project_id,
        document_version_id=row.document_version_id,
        source_location_id=row.source_location_id,
        document_type=row.document_type,
        chunking_version=row.chunking_version,
        ordinal=row.ordinal,
        normalized_text=row.normalized_text,
        lexical_score=lexical_score,
        lexical_rank=lexical_rank,
        semantic_distance=semantic_distance,
        semantic_rank=semantic_rank,
        fusion_score=0.0,
        rank=None,
    )


def _fuse_candidates(
    *,
    lexical: tuple[HybridCandidate, ...],
    semantic: tuple[HybridCandidate, ...],
    result_limit: int,
) -> tuple[tuple[HybridCandidate, ...], tuple[HybridCandidate, ...]]:
    candidates = {candidate.chunk_id: candidate for candidate in lexical}
    for candidate in semantic:
        existing = candidates.get(candidate.chunk_id)
        if existing is None:
            candidates[candidate.chunk_id] = candidate
        else:
            candidates[candidate.chunk_id] = replace(
                existing,
                semantic_distance=candidate.semantic_distance,
                semantic_rank=candidate.semantic_rank,
            )
    scored = tuple(
        replace(candidate, fusion_score=_reciprocal_rank_score(candidate))
        for candidate in candidates.values()
    )
    ordered = tuple(
        sorted(
            scored,
            key=lambda candidate: (
                -candidate.fusion_score,
                candidate.ordinal,
                str(candidate.chunk_id),
            ),
        )
    )
    selected_ids = {candidate.chunk_id for candidate in ordered[:result_limit]}
    traced = tuple(
        replace(
            candidate,
            rank=index if candidate.chunk_id in selected_ids else None,
        )
        for index, candidate in enumerate(ordered, start=1)
    )
    return traced, tuple(
        candidate for candidate in traced if candidate.rank is not None
    )


def _reciprocal_rank_score(candidate: HybridCandidate) -> float:
    return sum(
        1.0 / (RECIPROCAL_RANK_OFFSET + rank)
        for rank in (candidate.lexical_rank, candidate.semantic_rank)
        if rank is not None
    )


def _pgvector_literal(values: tuple[float, ...]) -> str:
    return "[" + ",".join(format(value, ".17g") for value in values) + "]"
