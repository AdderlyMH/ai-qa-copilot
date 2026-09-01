"""Opaque parser-job queue boundary; raw bytes never enter a queue message."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import ParserJobRecord, ParserJobState


class ParserJobQueueUnavailable(RuntimeError):
    """Raised when the parser queue cannot durably accept a job."""


@dataclass(frozen=True)
class ParserJob:
    """The sole parser-queue payload: an opaque document-intake identifier."""

    document_intake_id: UUID


class ParserJobQueue(Protocol):
    """Queue boundary shared by the API producer and restricted worker only."""

    def enqueue(self, job: ParserJob) -> None: ...


def utc_now() -> datetime:
    """Return a timezone-aware queue timestamp."""

    return datetime.now(timezone.utc)


class SqlAlchemyParserJobQueue:
    """A durable local queue contract with idempotent opaque enqueue semantics."""

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

    def enqueue(self, job: ParserJob) -> None:
        try:
            with self._session_factory.begin() as session:
                session.add(
                    ParserJobRecord(
                        id=self._id_factory(),
                        document_intake_id=job.document_intake_id,
                        state=ParserJobState.QUEUED.value,
                        created_at=self._clock(),
                    )
                )
        except IntegrityError:
            try:
                with self._session_factory() as session:
                    existing = session.scalar(
                        select(ParserJobRecord.id).where(
                            ParserJobRecord.document_intake_id == job.document_intake_id
                        )
                    )
                if existing is not None:
                    return
            except SQLAlchemyError as error:
                raise ParserJobQueueUnavailable from error
            raise ParserJobQueueUnavailable
        except SQLAlchemyError as error:
            raise ParserJobQueueUnavailable from error


class InMemoryParserJobQueue:
    """Deterministic queue fake for API-boundary tests only."""

    def __init__(self) -> None:
        self.jobs: list[ParserJob] = []

    def enqueue(self, job: ParserJob) -> None:
        if job not in self.jobs:
            self.jobs.append(job)


class UnavailableParserJobQueue:
    """Fail closed until a durable parser queue is configured explicitly."""

    def enqueue(self, job: ParserJob) -> None:
        del job
        raise ParserJobQueueUnavailable
