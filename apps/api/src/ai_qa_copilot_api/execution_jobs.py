"""Durable, non-executable queue state for approved execution plans."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4
import os

from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    ExecutionApprovalRecord,
    ExecutionJobRecord,
    ExecutionJobState,
)
from ai_qa_copilot_api.execution_approvals import (
    ExecutionApproval,
    ExecutionApprovalUnavailable,
    _approval_from_record,
)


class ExecutionJobQueueUnavailable(RuntimeError):
    """Raised when durable execution-job state cannot be safely accessed."""


class ExecutionJobRejected(ValueError):
    """Raised when a job cannot be bound to one valid immutable approval."""


@dataclass(frozen=True)
class ExecutionJob:
    """One durable future-worker job; creating it performs no execution."""

    id: UUID
    project_id: UUID
    execution_approval_id: UUID
    plan_id: UUID
    plan_hash: str
    state: ExecutionJobState
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    cancelled_at: datetime | None


@dataclass(frozen=True)
class ClaimedExecutionJob:
    """A job and approval atomically claimed by a future restricted worker."""

    job: ExecutionJob
    approval: ExecutionApproval


class ExecutionJobQueue(Protocol):
    """Durable boundary used only by a future approved-execution worker."""

    def enqueue(self, *, approval: ExecutionApproval) -> ExecutionJob: ...

    def get(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> ExecutionJob | None: ...

    def claim_next(self) -> ClaimedExecutionJob | None: ...

    def cancel(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> ExecutionJob | None: ...


def utc_now() -> datetime:
    """Return a timezone-aware timestamp for deterministic state transitions."""

    return datetime.now(timezone.utc)


class SqlAlchemyExecutionJobQueue:
    """Persist jobs and atomically bind a worker claim to approval consumption."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_database_url(cls, database_url: str) -> SqlAlchemyExecutionJobQueue:
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def enqueue(self, *, approval: ExecutionApproval) -> ExecutionJob:
        now = _utc_datetime(self._clock())
        if approval.consumed_at is not None:
            raise ExecutionJobRejected("A consumed approval cannot create a job")
        if approval.expires_at <= now:
            raise ExecutionJobRejected("An expired approval cannot create a job")

        record = ExecutionJobRecord(
            id=self._id_factory(),
            project_id=approval.project_id,
            execution_approval_id=approval.id,
            plan_id=approval.plan.id,
            plan_hash=approval.plan.plan_hash,
            state=ExecutionJobState.QUEUED.value,
            created_at=now,
            started_at=None,
            finished_at=None,
            cancel_requested_at=None,
            cancelled_at=None,
        )

        try:
            with self._session_factory.begin() as session:
                session.add(record)
        except IntegrityError:
            existing = self._existing_job(approval.id)
            if existing is not None:
                return existing
            raise ExecutionJobQueueUnavailable from None
        except SQLAlchemyError as error:
            raise ExecutionJobQueueUnavailable from error

        return _job_from_record(record)

    def get(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> ExecutionJob | None:
        try:
            with self._session_factory() as session:
                record = session.execute(
                    select(ExecutionJobRecord).where(
                        ExecutionJobRecord.id == job_id,
                        ExecutionJobRecord.project_id == project_id,
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise ExecutionJobQueueUnavailable from error

        return _job_from_record(record) if record is not None else None

    def claim_next(self) -> ClaimedExecutionJob | None:
        """Claim one queued job and consume its approval in the same transaction."""

        now = _utc_datetime(self._clock())

        try:
            with self._session_factory.begin() as session:
                job_record = session.execute(
                    select(ExecutionJobRecord)
                    .where(ExecutionJobRecord.state == ExecutionJobState.QUEUED.value)
                    .order_by(ExecutionJobRecord.created_at, ExecutionJobRecord.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).scalar_one_or_none()

                if job_record is None:
                    return None

                approval_record = session.execute(
                    select(ExecutionApprovalRecord).where(
                        ExecutionApprovalRecord.id == job_record.execution_approval_id,
                        ExecutionApprovalRecord.project_id == job_record.project_id,
                        ExecutionApprovalRecord.plan_id == job_record.plan_id,
                        ExecutionApprovalRecord.plan_hash == job_record.plan_hash,
                    )
                ).scalar_one_or_none()

                if approval_record is None:
                    _fail_job(job_record, now)
                    return None

                try:
                    approval = _approval_from_record(approval_record)
                except ExecutionApprovalUnavailable:
                    _fail_job(job_record, now)
                    return None

                if approval.consumed_at is not None or approval.expires_at <= now:
                    _fail_job(job_record, now)
                    return None

                consumed_id = session.execute(
                    update(ExecutionApprovalRecord)
                    .where(
                        ExecutionApprovalRecord.id == approval.id,
                        ExecutionApprovalRecord.consumed_at.is_(None),
                        ExecutionApprovalRecord.expires_at > now,
                    )
                    .values(consumed_at=now)
                    .returning(ExecutionApprovalRecord.id)
                    .execution_options(synchronize_session=False)
                ).scalar_one_or_none()

                if consumed_id is None:
                    _fail_job(job_record, now)
                    return None

                job_record.state = ExecutionJobState.RUNNING.value
                job_record.started_at = now

                return ClaimedExecutionJob(
                    job=_job_from_record(job_record),
                    approval=replace(approval, consumed_at=now),
                )
        except SQLAlchemyError as error:
            raise ExecutionJobQueueUnavailable from error

    def cancel(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> ExecutionJob | None:
        now = _utc_datetime(self._clock())

        try:
            with self._session_factory.begin() as session:
                cancelled_id = session.execute(
                    update(ExecutionJobRecord)
                    .where(
                        ExecutionJobRecord.id == job_id,
                        ExecutionJobRecord.project_id == project_id,
                        ExecutionJobRecord.state == ExecutionJobState.QUEUED.value,
                    )
                    .values(
                        state=ExecutionJobState.CANCELLED.value,
                        cancel_requested_at=now,
                        cancelled_at=now,
                    )
                    .returning(ExecutionJobRecord.id)
                    .execution_options(synchronize_session=False)
                ).scalar_one_or_none()

                if cancelled_id is None:
                    return None

                record = session.get(ExecutionJobRecord, cancelled_id)
                if record is None:
                    raise ExecutionJobQueueUnavailable

                return _job_from_record(record)
        except SQLAlchemyError as error:
            raise ExecutionJobQueueUnavailable from error

    def _existing_job(self, approval_id: UUID) -> ExecutionJob | None:
        try:
            with self._session_factory() as session:
                record = session.execute(
                    select(ExecutionJobRecord).where(
                        ExecutionJobRecord.execution_approval_id == approval_id
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise ExecutionJobQueueUnavailable from error

        return _job_from_record(record) if record is not None else None


class UnavailableExecutionJobQueue:
    """Fail closed until durable execution-job storage is explicitly configured."""

    def enqueue(self, *, approval: ExecutionApproval) -> ExecutionJob:
        del approval
        raise ExecutionJobQueueUnavailable

    def get(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> ExecutionJob | None:
        del project_id, job_id
        raise ExecutionJobQueueUnavailable

    def claim_next(self) -> ClaimedExecutionJob | None:
        raise ExecutionJobQueueUnavailable

    def cancel(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> ExecutionJob | None:
        del project_id, job_id
        raise ExecutionJobQueueUnavailable


def execution_job_queue_from_environment() -> ExecutionJobQueue:
    """Build durable job storage only when the database is explicitly configured."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableExecutionJobQueue()
    return SqlAlchemyExecutionJobQueue.from_database_url(database_url)


def _fail_job(record: ExecutionJobRecord, now: datetime) -> None:
    """Persist a terminal preflight failure without any transport attempt."""

    record.state = ExecutionJobState.FAILED.value
    record.started_at = now
    record.finished_at = now


def _job_from_record(record: ExecutionJobRecord) -> ExecutionJob:
    return ExecutionJob(
        id=record.id,
        project_id=record.project_id,
        execution_approval_id=record.execution_approval_id,
        plan_id=record.plan_id,
        plan_hash=record.plan_hash,
        state=ExecutionJobState(record.state),
        created_at=_utc_datetime(record.created_at),
        started_at=(
            _utc_datetime(record.started_at) if record.started_at is not None else None
        ),
        finished_at=(
            _utc_datetime(record.finished_at)
            if record.finished_at is not None
            else None
        ),
        cancel_requested_at=(
            _utc_datetime(record.cancel_requested_at)
            if record.cancel_requested_at is not None
            else None
        ),
        cancelled_at=(
            _utc_datetime(record.cancelled_at)
            if record.cancelled_at is not None
            else None
        ),
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
