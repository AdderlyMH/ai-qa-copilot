"""Atomic claims for durable indexing jobs; embeddings remain a separate boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, select, true, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import IndexingJobRecord
from ai_qa_copilot_api.indexing import (
    DEFAULT_CHUNKING_VERSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_VERSION,
)
from ai_qa_copilot_api.parser_queue import utc_now


class IndexingJobClaimRejected(RuntimeError):
    """The claim is missing, expired, altered, or already terminal."""


class IndexingJobUnavailable(RuntimeError):
    """The durable indexing-job state could not be read or written safely."""


@dataclass(frozen=True)
class ClaimedIndexingJob:
    """Lease identity and configuration; never source bytes or storage keys."""

    job_id: UUID
    project_id: UUID
    document_version_id: UUID
    chunking_version: str
    embedding_model: str
    embedding_version: str
    claim_token: UUID
    claimed_at: datetime
    claim_expires_at: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Indexing claim clock must be timezone-aware")
    return value.astimezone(timezone.utc)


class SqlAlchemyIndexingJobClaims:
    """Claim once and preserve terminal outcomes; never replay abandoned indexing."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
        claim_duration: timedelta = timedelta(seconds=60),
        document_version_id: UUID | None = None,
        chunking_version: str = DEFAULT_CHUNKING_VERSION,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedding_version: str = DEFAULT_EMBEDDING_VERSION,
    ) -> None:
        if claim_duration <= timedelta(0):
            raise ValueError("Indexing claim duration must be positive")
        if not all(
            value.strip()
            for value in (chunking_version, embedding_model, embedding_version)
        ):
            raise ValueError("Indexing configuration values must be non-empty")

        self._sessions = session_factory
        self._clock = clock
        self._id_factory = id_factory
        self._duration = claim_duration
        self._scope = (
            IndexingJobRecord.document_version_id == document_version_id
            if document_version_id is not None
            else true()
        )
        self._configuration_scope = and_(
            IndexingJobRecord.chunking_version == chunking_version,
            IndexingJobRecord.embedding_model == embedding_model,
            IndexingJobRecord.embedding_version == embedding_version,
        )

    def claim_next(self) -> ClaimedIndexingJob | None:
        now = _utc(self._clock())
        token = self._id_factory()
        deadline = now + self._duration
        candidate = (
            select(IndexingJobRecord.id)
            .where(
                IndexingJobRecord.state == "queued",
                IndexingJobRecord.created_at <= now,
                self._scope,
                self._configuration_scope,
            )
            .order_by(IndexingJobRecord.created_at, IndexingJobRecord.id)
            .limit(1)
            .scalar_subquery()
        )
        try:
            with self._sessions.begin() as session:
                row = session.execute(
                    update(IndexingJobRecord)
                    .where(
                        IndexingJobRecord.id == candidate,
                        IndexingJobRecord.state == "queued",
                        self._scope,
                        self._configuration_scope,
                    )
                    .values(
                        state="claimed",
                        claim_token=token,
                        claimed_at=now,
                        claim_expires_at=deadline,
                    )
                    .returning(
                        IndexingJobRecord.id,
                        IndexingJobRecord.project_id,
                        IndexingJobRecord.document_version_id,
                        IndexingJobRecord.chunking_version,
                        IndexingJobRecord.embedding_model,
                        IndexingJobRecord.embedding_version,
                    )
                    .execution_options(synchronize_session=False)
                ).one_or_none()
                if row is None:
                    return None
                return ClaimedIndexingJob(
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    token,
                    now,
                    deadline,
                )
        except SQLAlchemyError as error:
            raise IndexingJobUnavailable(
                "Indexing job claim could not be stored"
            ) from error

    def accept(self, claim: ClaimedIndexingJob) -> None:
        self._finish(claim, state="accepted", code=None)

    def fail(self, claim: ClaimedIndexingJob) -> None:
        self._finish(claim, state="failed", code="INDEXING_WORKER_FAILED")

    def _finish(
        self, claim: ClaimedIndexingJob, *, state: str, code: str | None
    ) -> None:
        now = _utc(self._clock())
        try:
            with self._sessions.begin() as session:
                job_id = session.scalar(
                    update(IndexingJobRecord)
                    .where(
                        IndexingJobRecord.id == claim.job_id,
                        self._scope,
                        self._configuration_scope,
                        IndexingJobRecord.project_id == claim.project_id,
                        IndexingJobRecord.document_version_id
                        == claim.document_version_id,
                        IndexingJobRecord.chunking_version == claim.chunking_version,
                        IndexingJobRecord.embedding_model == claim.embedding_model,
                        IndexingJobRecord.embedding_version == claim.embedding_version,
                        IndexingJobRecord.state == "claimed",
                        IndexingJobRecord.claim_token == claim.claim_token,
                        IndexingJobRecord.claimed_at == _utc(claim.claimed_at),
                        IndexingJobRecord.claim_expires_at
                        == _utc(claim.claim_expires_at),
                        IndexingJobRecord.claimed_at <= now,
                        IndexingJobRecord.claim_expires_at > now,
                    )
                    .values(state=state, completed_at=now, failure_code=code)
                    .returning(IndexingJobRecord.id)
                    .execution_options(synchronize_session=False)
                )
                if job_id is None:
                    raise IndexingJobClaimRejected("Indexing job claim is not active")
        except SQLAlchemyError as error:
            raise IndexingJobUnavailable(
                "Indexing job completion could not be stored"
            ) from error

    def expire_claims(self) -> int:
        """Terminalize abandoned work; a late worker cannot publish or requeue it."""
        now = _utc(self._clock())
        try:
            with self._sessions.begin() as session:
                ids = tuple(
                    session.scalars(
                        update(IndexingJobRecord)
                        .where(
                            IndexingJobRecord.state == "claimed",
                            self._scope,
                            self._configuration_scope,
                            IndexingJobRecord.claim_expires_at <= now,
                        )
                        .values(
                            state="failed",
                            completed_at=now,
                            failure_code="INDEXING_CLAIM_EXPIRED",
                        )
                        .returning(IndexingJobRecord.id)
                        .execution_options(synchronize_session=False)
                    )
                )
                return len(ids)
        except SQLAlchemyError as error:
            raise IndexingJobUnavailable(
                "Expired indexing claims could not be stored"
            ) from error
