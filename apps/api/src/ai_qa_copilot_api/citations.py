"""Validated, project-scoped citation objects and immutable source passages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    CitationRecord,
    DocumentChunkRecord,
    DocumentRecord,
    DocumentVersionRecord,
    RetrievalTraceCandidateRecord,
    RetrievalTraceRecord,
    SourceLocationRecord,
)


CITATIONS_UNAVAILABLE_DETAIL = "Citation service is temporarily unavailable"


class CitationUnavailable(RuntimeError):
    """Raised when durable citation state cannot be read or written safely."""


class CitationValidationError(ValueError):
    """Raised when a requested citation is not a selected candidate in its project."""


@dataclass(frozen=True)
class SourceLocation:
    """Safe immutable coordinate displayed with a cited source passage."""

    id: UUID
    location_kind: str
    heading: str | None
    line_start: int | None
    line_end: int | None
    page_start: int | None
    page_end: int | None
    json_pointer: str | None


@dataclass(frozen=True)
class Citation:
    """Validated link from one retrieval trace to immutable source evidence."""

    id: UUID
    project_id: UUID
    retrieval_trace_id: UUID
    document_chunk_id: UUID
    document_version_id: UUID
    source_location: SourceLocation
    document_type: str
    display_name: str
    passage: str
    created_at: datetime


class CitationRepository(Protocol):
    """Persistence boundary for project-scoped citation creation and viewing."""

    def create_from_selected_candidate(
        self, *, project_id: UUID, retrieval_trace_id: UUID, document_chunk_id: UUID
    ) -> Citation: ...

    def get_for_project(
        self, *, project_id: UUID, citation_id: UUID
    ) -> Citation | None: ...


class UnavailableCitationRepository:
    """Fail closed until a database URL supplies durable citation state."""

    def create_from_selected_candidate(
        self, *, project_id: UUID, retrieval_trace_id: UUID, document_chunk_id: UUID
    ) -> Citation:
        raise CitationUnavailable

    def get_for_project(
        self, *, project_id: UUID, citation_id: UUID
    ) -> Citation | None:
        raise CitationUnavailable


class SqlAlchemyCitationRepository:
    """Read and write citations only through their selected, project-scoped evidence."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_database_url(cls, database_url: str) -> "SqlAlchemyCitationRepository":
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def create_from_selected_candidate(
        self, *, project_id: UUID, retrieval_trace_id: UUID, document_chunk_id: UUID
    ) -> Citation:
        try:
            with self._session_factory.begin() as session:
                citation = session.execute(
                    _citation_statement().where(
                        CitationRecord.project_id == project_id,
                        CitationRecord.retrieval_trace_id == retrieval_trace_id,
                        CitationRecord.document_chunk_id == document_chunk_id,
                    )
                ).one_or_none()
                if citation is not None:
                    return _citation_from_row(citation)

                candidate = session.execute(
                    _selected_candidate_statement().where(
                        RetrievalTraceRecord.project_id == project_id,
                        RetrievalTraceCandidateRecord.retrieval_trace_id
                        == retrieval_trace_id,
                        RetrievalTraceCandidateRecord.document_chunk_id
                        == document_chunk_id,
                    )
                ).one_or_none()
                if candidate is None:
                    raise CitationValidationError(
                        "Citation must reference a selected candidate in its project"
                    )
                record = CitationRecord(
                    id=self._id_factory(),
                    project_id=project_id,
                    retrieval_trace_id=retrieval_trace_id,
                    document_chunk_id=document_chunk_id,
                    document_version_id=candidate.document_version_id,
                    source_location_id=candidate.source_location_id,
                    created_at=self._clock(),
                )
                session.add(record)
                session.flush()
                row = session.execute(
                    _citation_statement().where(CitationRecord.id == record.id)
                ).one()
                return _citation_from_row(row)
        except CitationValidationError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise CitationUnavailable from error

    def get_for_project(
        self, *, project_id: UUID, citation_id: UUID
    ) -> Citation | None:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    _citation_statement().where(
                        CitationRecord.id == citation_id,
                        CitationRecord.project_id == project_id,
                    )
                ).one_or_none()
        except SQLAlchemyError as error:
            raise CitationUnavailable from error
        return _citation_from_row(row) if row is not None else None


def citation_repository_from_environment() -> CitationRepository:
    """Build citation persistence only from the explicit durable database URL."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableCitationRepository()
    return SqlAlchemyCitationRepository.from_database_url(database_url)


def _selected_candidate_statement() -> Any:
    return (
        select(
            DocumentChunkRecord.document_version_id,
            DocumentChunkRecord.source_location_id,
        )
        .join(
            RetrievalTraceCandidateRecord,
            RetrievalTraceCandidateRecord.document_chunk_id == DocumentChunkRecord.id,
        )
        .join(
            RetrievalTraceRecord,
            RetrievalTraceCandidateRecord.retrieval_trace_id == RetrievalTraceRecord.id,
        )
        .join(
            DocumentVersionRecord,
            DocumentChunkRecord.document_version_id == DocumentVersionRecord.id,
        )
        .join(DocumentRecord, DocumentVersionRecord.document_id == DocumentRecord.id)
        .where(
            RetrievalTraceCandidateRecord.final_rank.is_not(None),
            DocumentRecord.project_id == RetrievalTraceRecord.project_id,
        )
    )


def _citation_statement() -> Any:
    return (
        select(
            CitationRecord.id,
            CitationRecord.project_id,
            CitationRecord.retrieval_trace_id,
            CitationRecord.document_chunk_id,
            CitationRecord.document_version_id,
            CitationRecord.created_at,
            DocumentChunkRecord.normalized_text,
            DocumentRecord.document_type,
            DocumentRecord.display_name,
            SourceLocationRecord.id.label("source_location_id"),
            SourceLocationRecord.location_kind,
            SourceLocationRecord.heading,
            SourceLocationRecord.line_start,
            SourceLocationRecord.line_end,
            SourceLocationRecord.page_start,
            SourceLocationRecord.page_end,
            SourceLocationRecord.json_pointer,
        )
        .join(
            DocumentChunkRecord,
            CitationRecord.document_chunk_id == DocumentChunkRecord.id,
        )
        .join(
            DocumentVersionRecord,
            CitationRecord.document_version_id == DocumentVersionRecord.id,
        )
        .join(DocumentRecord, DocumentVersionRecord.document_id == DocumentRecord.id)
        .join(
            SourceLocationRecord,
            CitationRecord.source_location_id == SourceLocationRecord.id,
        )
        .where(
            DocumentChunkRecord.document_version_id
            == CitationRecord.document_version_id,
            DocumentChunkRecord.source_location_id == CitationRecord.source_location_id,
            DocumentRecord.project_id == CitationRecord.project_id,
        )
    )


def _citation_from_row(row: Any) -> Citation:
    return Citation(
        id=row.id,
        project_id=row.project_id,
        retrieval_trace_id=row.retrieval_trace_id,
        document_chunk_id=row.document_chunk_id,
        document_version_id=row.document_version_id,
        source_location=SourceLocation(
            id=row.source_location_id,
            location_kind=row.location_kind,
            heading=row.heading,
            line_start=row.line_start,
            line_end=row.line_end,
            page_start=row.page_start,
            page_end=row.page_end,
            json_pointer=row.json_pointer,
        ),
        document_type=row.document_type,
        display_name=row.display_name,
        passage=row.normalized_text,
        created_at=row.created_at,
    )
