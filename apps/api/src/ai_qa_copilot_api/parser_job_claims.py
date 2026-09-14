"""Atomic claims for opaque parser jobs; parsing and promotion are separate boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, true, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import DocumentIntakeRecord, ParserJobRecord
from ai_qa_copilot_api.parser_queue import ParserJobQueueUnavailable, utc_now


class ParserJobClaimRejected(RuntimeError):
    """The claim is missing, expired, altered, or already terminal."""


@dataclass(frozen=True)
class ClaimedParserJob:
    """Opaque lease identity; never includes source bytes or a quarantine key."""

    job_id: UUID
    document_intake_id: UUID
    claim_token: UUID
    claimed_at: datetime
    claim_expires_at: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Parser claim clock must be timezone-aware")
    return value.astimezone(timezone.utc)


class SqlAlchemyParserJobClaims:
    """Claim once and preserve terminal failures; never automatically retry a parser."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
        claim_duration: timedelta = timedelta(seconds=60),
        intake_id: UUID | None = None,
    ) -> None:
        if claim_duration <= timedelta(0):
            raise ValueError("Parser claim duration must be positive")
        self._sessions = session_factory
        self._clock = clock
        self._id_factory = id_factory
        self._duration = claim_duration
        self._scope = (
            ParserJobRecord.document_intake_id == intake_id
            if intake_id is not None
            else true()
        )

    def claim_next(self) -> ClaimedParserJob | None:
        now = _utc(self._clock())
        token = self._id_factory()
        deadline = now + self._duration
        candidate = (
            select(ParserJobRecord.id)
            .join(
                DocumentIntakeRecord,
                DocumentIntakeRecord.id == ParserJobRecord.document_intake_id,
            )
            .where(
                ParserJobRecord.state == "queued",
                ParserJobRecord.created_at <= now,
                DocumentIntakeRecord.state == "quarantined",
                self._scope,
            )
            .order_by(ParserJobRecord.created_at, ParserJobRecord.id)
            .limit(1)
            .scalar_subquery()
        )
        try:
            with self._sessions.begin() as session:
                # The state predicate is rechecked atomically by the database.
                # A concurrent caller may get no job and poll again; it cannot
                # obtain this claim or cause this job to execute twice.
                row = session.execute(
                    update(ParserJobRecord)
                    .where(
                        ParserJobRecord.id == candidate,
                        ParserJobRecord.state == "queued",
                    )
                    .values(
                        state="claimed",
                        claim_token=token,
                        claimed_at=now,
                        claim_expires_at=deadline,
                    )
                    .returning(ParserJobRecord.id, ParserJobRecord.document_intake_id)
                    .execution_options(synchronize_session=False)
                ).one_or_none()
                if row is None:
                    return None
                return ClaimedParserJob(row[0], row[1], token, now, deadline)
        except SQLAlchemyError as error:
            raise ParserJobQueueUnavailable(
                "Parser job claim could not be stored"
            ) from error

    def reject(self, claim: ClaimedParserJob) -> None:
        self._finish(claim, state="rejected", code="PARSER_DOCUMENT_REJECTED")

    def fail(self, claim: ClaimedParserJob) -> None:
        self._finish(claim, state="failed", code="PARSER_WORKER_FAILED")

    def _finish(self, claim: ClaimedParserJob, *, state: str, code: str) -> None:
        now = _utc(self._clock())
        try:
            with self._sessions.begin() as session:
                job_id = session.scalar(
                    update(ParserJobRecord)
                    .where(
                        ParserJobRecord.id == claim.job_id,
                        self._scope,
                        ParserJobRecord.document_intake_id == claim.document_intake_id,
                        ParserJobRecord.state == "claimed",
                        ParserJobRecord.claim_token == claim.claim_token,
                        ParserJobRecord.claimed_at == _utc(claim.claimed_at),
                        ParserJobRecord.claim_expires_at
                        == _utc(claim.claim_expires_at),
                        ParserJobRecord.claimed_at <= now,
                        ParserJobRecord.claim_expires_at > now,
                    )
                    .values(state=state, completed_at=now, failure_code=code)
                    .returning(ParserJobRecord.id)
                    .execution_options(synchronize_session=False)
                )
                if job_id is None:
                    raise ParserJobClaimRejected("Parser job claim is not active")
        except SQLAlchemyError as error:
            raise ParserJobQueueUnavailable(
                "Parser job failure could not be stored"
            ) from error

    def expire_claims(self) -> int:
        """Terminalize abandoned work; late workers cannot publish or requeue it."""
        now = _utc(self._clock())
        try:
            with self._sessions.begin() as session:
                ids = tuple(
                    session.scalars(
                        update(ParserJobRecord)
                        .where(
                            ParserJobRecord.state == "claimed",
                            self._scope,
                            ParserJobRecord.claim_expires_at <= now,
                        )
                        .values(
                            state="failed",
                            completed_at=now,
                            failure_code="PARSER_CLAIM_EXPIRED",
                        )
                        .returning(ParserJobRecord.id)
                        .execution_options(synchronize_session=False)
                    )
                )
                return len(ids)
        except SQLAlchemyError as error:
            raise ParserJobQueueUnavailable(
                "Expired parser claims could not be stored"
            ) from error
