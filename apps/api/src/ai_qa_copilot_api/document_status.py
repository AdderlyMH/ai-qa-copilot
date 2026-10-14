"""Read-only owner view of uploaded documents and their parser stage (INFRA-006).

The status is derived from existing state only: the intake outcome and the one
parser job per intake. It never reads storage keys, content hashes, bucket
names or raw bytes, and it needs no schema change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.engine import Row
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    DocumentIntakeRecord,
    DocumentIntakeState,
    ParserJobRecord,
    ParserJobState,
)


DOCUMENT_STATUS_LIST_LIMIT = 100


class DocumentStatusUnavailable(RuntimeError):
    """Raised when document status cannot be read; callers fail closed."""


class DocumentStatus(StrEnum):
    """Closed set of owner-visible document states."""

    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    PARSER_QUEUED = "parser_queued"
    PARSING = "parsing"
    PARSED = "parsed"
    PARSE_FAILED = "parse_failed"


class IndexingStatus(StrEnum):
    """Indexing is outside the production scope until INFRA-013."""

    INDEXING_NOT_ENABLED = "indexing_not_enabled"


@dataclass(frozen=True)
class DocumentStatusView:
    """Safe projection of one upload; no key, hash or content is carried."""

    id: UUID
    project_id: UUID
    document_id: UUID | None
    filename: str
    content_type: str
    byte_size: int
    outcome: DocumentIntakeState
    rejection_code: str | None
    status: DocumentStatus
    parser_stage: ParserJobState | None
    indexing: IndexingStatus | None
    created_at: datetime


_PARSER_STATUS = {
    ParserJobState.QUEUED: DocumentStatus.PARSER_QUEUED,
    ParserJobState.CLAIMED: DocumentStatus.PARSING,
    ParserJobState.ACCEPTED: DocumentStatus.PARSED,
    ParserJobState.REJECTED: DocumentStatus.PARSE_FAILED,
    ParserJobState.FAILED: DocumentStatus.PARSE_FAILED,
}


def derive_document_status(
    outcome: DocumentIntakeState, parser_stage: ParserJobState | None
) -> DocumentStatus:
    """Map the intake outcome and parser job state to one closed status."""

    if outcome is DocumentIntakeState.REJECTED:
        if parser_stage is not None:
            raise ValueError("A rejected upload cannot have a parser job")
        return DocumentStatus.REJECTED
    if parser_stage is None:
        return DocumentStatus.QUARANTINED
    return _PARSER_STATUS[parser_stage]


class DocumentStatusRepository(Protocol):
    """Owner read boundary; every query is scoped to one project."""

    def list_for_project(
        self, *, project_id: UUID, limit: int = DOCUMENT_STATUS_LIST_LIMIT
    ) -> tuple[DocumentStatusView, ...]: ...

    def get_for_project(
        self, *, project_id: UUID, document_id: UUID
    ) -> DocumentStatusView | None: ...


class SqlAlchemyDocumentStatusRepository:
    """Join each intake with its parser job, newest first, bounded."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_for_project(
        self, *, project_id: UUID, limit: int = DOCUMENT_STATUS_LIST_LIMIT
    ) -> tuple[DocumentStatusView, ...]:
        bounded = max(1, min(limit, DOCUMENT_STATUS_LIST_LIMIT))
        statement = (
            _status_statement()
            .where(DocumentIntakeRecord.project_id == project_id)
            .order_by(
                DocumentIntakeRecord.created_at.desc(),
                DocumentIntakeRecord.id.desc(),
            )
            .limit(bounded)
        )
        try:
            with self._session_factory() as session:
                return tuple(_view(row) for row in session.execute(statement))
        except (SQLAlchemyError, ValueError) as error:
            raise DocumentStatusUnavailable from error

    def get_for_project(
        self, *, project_id: UUID, document_id: UUID
    ) -> DocumentStatusView | None:
        statement = _status_statement().where(
            DocumentIntakeRecord.project_id == project_id,
            DocumentIntakeRecord.id == document_id,
        )
        try:
            with self._session_factory() as session:
                row = session.execute(statement).one_or_none()
                return _view(row) if row is not None else None
        except (SQLAlchemyError, ValueError) as error:
            raise DocumentStatusUnavailable from error


class UnavailableDocumentStatusRepository:
    """Fail closed until durable state is configured explicitly."""

    def list_for_project(
        self, *, project_id: UUID, limit: int = DOCUMENT_STATUS_LIST_LIMIT
    ) -> tuple[DocumentStatusView, ...]:
        del project_id, limit
        raise DocumentStatusUnavailable

    def get_for_project(
        self, *, project_id: UUID, document_id: UUID
    ) -> DocumentStatusView | None:
        del project_id, document_id
        raise DocumentStatusUnavailable


def _status_statement() -> Select[tuple[DocumentIntakeRecord, str]]:
    # Select whole intake rows plus the job state only; the quarantine key and
    # content hash are never copied into the view. The outer join yields a
    # NULL state for an intake with no parser job.
    return select(DocumentIntakeRecord, ParserJobRecord.state).outerjoin(
        ParserJobRecord,
        ParserJobRecord.document_intake_id == DocumentIntakeRecord.id,
    )


def _view(row: Row[tuple[DocumentIntakeRecord, str]]) -> DocumentStatusView:
    intake = row[0]
    parser_state: str | None = row[1]
    outcome = DocumentIntakeState(intake.state)
    parser_stage = ParserJobState(parser_state) if parser_state is not None else None
    status = derive_document_status(outcome, parser_stage)
    return DocumentStatusView(
        id=intake.id,
        project_id=intake.project_id,
        document_id=intake.document_id,
        filename=intake.original_filename,
        content_type=intake.declared_content_type,
        byte_size=intake.byte_size,
        outcome=outcome,
        rejection_code=intake.rejection_code,
        status=status,
        parser_stage=parser_stage,
        indexing=(
            IndexingStatus.INDEXING_NOT_ENABLED
            if status is DocumentStatus.PARSED
            else None
        ),
        created_at=_utc(intake.created_at),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
