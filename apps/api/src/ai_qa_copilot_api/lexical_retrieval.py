"""Project-scoped PostgreSQL full-text retrieval over accepted chunks."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    DocumentChunkRecord,
    DocumentRecord,
    DocumentVersionRecord,
)


LEXICAL_RETRIEVAL_VERSION = "lexical-v1"
DEFAULT_LEXICAL_RESULT_LIMIT = 20
MAX_LEXICAL_RESULT_LIMIT = 100


class LexicalRetrievalUnavailable(RuntimeError):
    """Raised when the lexical retrieval store cannot safely serve a query."""


@dataclass(frozen=True)
class LexicalRetrievalFilters:
    """Deterministic optional filters applied within the mandatory project scope."""

    document_version_ids: tuple[UUID, ...] | None = None
    document_types: tuple[str, ...] | None = None
    chunking_version: str | None = None

    def validate(self) -> None:
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
class LexicalCandidate:
    """One ranked chunk returned by project-scoped lexical search."""

    chunk_id: UUID
    project_id: UUID
    document_version_id: UUID
    source_location_id: UUID
    document_type: str
    chunking_version: str
    ordinal: int
    normalized_text: str
    score: float
    rank: int


@dataclass(frozen=True)
class LexicalRetrievalResponse:
    """Reproducible lexical result set with its immutable query configuration."""

    retrieval_version: str
    query: str
    project_id: UUID
    candidates: tuple[LexicalCandidate, ...]


class LexicalRetrievalStore(Protocol):
    """Persistence boundary for project-scoped lexical candidate retrieval."""

    def search(
        self,
        *,
        project_id: UUID,
        query: str,
        filters: LexicalRetrievalFilters,
        limit: int,
    ) -> tuple[LexicalCandidate, ...]: ...


class LexicalRetrievalService:
    """Validate bounded lexical queries before delegating to PostgreSQL."""

    def __init__(self, store: LexicalRetrievalStore) -> None:
        self._store = store

    def search(
        self,
        *,
        project_id: UUID,
        query: str,
        filters: LexicalRetrievalFilters = LexicalRetrievalFilters(),
        limit: int = DEFAULT_LEXICAL_RESULT_LIMIT,
    ) -> LexicalRetrievalResponse:
        normalized_query = " ".join(query.split())
        if not normalized_query or not any(
            character.isalnum() for character in normalized_query
        ):
            raise ValueError("Lexical query must contain searchable text")
        if limit < 1 or limit > MAX_LEXICAL_RESULT_LIMIT:
            raise ValueError(
                f"Lexical result limit must be between 1 and {MAX_LEXICAL_RESULT_LIMIT}"
            )
        filters.validate()
        candidates = self._store.search(
            project_id=project_id,
            query=normalized_query,
            filters=filters,
            limit=limit,
        )
        return LexicalRetrievalResponse(
            retrieval_version=LEXICAL_RETRIEVAL_VERSION,
            query=normalized_query,
            project_id=project_id,
            candidates=candidates,
        )


class SqlAlchemyLexicalRetrievalStore:
    """PostgreSQL full-text store over immutable accepted document chunks."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @classmethod
    def from_database_url(cls, database_url: str) -> "SqlAlchemyLexicalRetrievalStore":
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def search(
        self,
        *,
        project_id: UUID,
        query: str,
        filters: LexicalRetrievalFilters,
        limit: int,
    ) -> tuple[LexicalCandidate, ...]:
        filters.validate()
        query_text = func.plainto_tsquery("simple", query)
        search_vector = func.to_tsvector(
            "simple", DocumentChunkRecord.normalized_text
        )
        score = func.ts_rank_cd(search_vector, query_text)
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
                score.label("score"),
            )
            .join(
                DocumentVersionRecord,
                DocumentChunkRecord.document_version_id == DocumentVersionRecord.id,
            )
            .join(
                DocumentRecord,
                DocumentVersionRecord.document_id == DocumentRecord.id,
            )
            .where(
                DocumentRecord.project_id == project_id,
                search_vector.op("@@")(query_text),
            )
        )
        if filters.document_version_ids is not None:
            statement = statement.where(
                DocumentChunkRecord.document_version_id.in_(
                    filters.document_version_ids
                )
            )
        if filters.document_types is not None:
            statement = statement.where(
                DocumentRecord.document_type.in_(filters.document_types)
            )
        if filters.chunking_version is not None:
            statement = statement.where(
                DocumentChunkRecord.chunking_version == filters.chunking_version
            )
        statement = statement.order_by(
            score.desc(),
            DocumentChunkRecord.ordinal.asc(),
            DocumentChunkRecord.id.asc(),
        ).limit(limit)

        try:
            with self._session_factory() as session:
                rows = tuple(session.execute(statement))
        except SQLAlchemyError as error:
            raise LexicalRetrievalUnavailable from error

        return tuple(
            LexicalCandidate(
                chunk_id=row.id,
                project_id=row.project_id,
                document_version_id=row.document_version_id,
                source_location_id=row.source_location_id,
                document_type=row.document_type,
                chunking_version=row.chunking_version,
                ordinal=row.ordinal,
                normalized_text=row.normalized_text,
                score=float(row.score),
                rank=index,
            )
            for index, row in enumerate(rows, start=1)
        )


def lexical_retrieval_from_environment() -> LexicalRetrievalService:
    """Build the durable lexical service only from an explicit database URL."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise LexicalRetrievalUnavailable
    return LexicalRetrievalService(
        SqlAlchemyLexicalRetrievalStore.from_database_url(database_url)
    )
