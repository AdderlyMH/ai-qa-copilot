"""Explicit, fail-closed composition for one restricted execution worker."""

from __future__ import annotations

from dataclasses import dataclass
import socket
from typing import Final
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import ExecutionJobRecord, ExecutionJobState
from ai_qa_copilot_api.execution_jobs import SqlAlchemyExecutionJobQueue
from ai_qa_copilot_api.execution_results import (
    SqlAlchemyExecutionResultRepository,
)
from ai_qa_copilot_api.execution_worker import (
    ExecutionWorkerRun,
    RestrictedExecutionWorker,
)
from ai_qa_copilot_api.restricted_execution import RestrictedExecutionExecutor
from ai_qa_copilot_api.restricted_http_transport import (
    PinnedHttpxExecutionTransport,
)
from ai_qa_copilot_api.target_registry import AddressResolver


_MAX_RESOLVED_ADDRESSES: Final = 16


class SocketAddressResolver:
    """Resolve a registered hostname without accepting URLs or target changes."""

    def resolve(self, hostname: str) -> tuple[str, ...]:
        """Return a bounded, de-duplicated DNS answer or an empty failure answer."""

        if (
            not isinstance(hostname, str)
            or not hostname
            or hostname != hostname.strip()
            or "\x00" in hostname
        ):
            return ()

        try:
            records = socket.getaddrinfo(
                hostname,
                None,
                type=socket.SOCK_STREAM,
            )
        except OSError:
            return ()

        addresses: list[str] = []
        for _, _, _, _, socket_address in records:
            if not socket_address:
                continue
            address = socket_address[0]
            if not isinstance(address, str) or address in addresses:
                continue
            addresses.append(address)
            if len(addresses) == _MAX_RESOLVED_ADDRESSES:
                break

        return tuple(addresses)


class SqlAlchemyExecutionJobCancellationProbe:
    """Fail closed when cancellation state cannot prove that a job may continue."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def is_cancel_requested(self, job_id: UUID) -> bool:
        """Return true for cancellation, a non-running job, absence, or DB failure."""

        try:
            with self._session_factory() as session:
                record = session.execute(
                    select(ExecutionJobRecord).where(ExecutionJobRecord.id == job_id)
                ).scalar_one_or_none()
        except SQLAlchemyError:
            return True

        return (
            record is None
            or record.state != ExecutionJobState.RUNNING.value
            or record.cancel_requested_at is not None
        )


@dataclass
class RestrictedExecutionWorkerRuntime:
    """Own one explicit worker composition; nothing starts it automatically."""

    worker: RestrictedExecutionWorker
    engine: Engine

    def run_once(self) -> ExecutionWorkerRun:
        """Run one claimed job at most; the caller owns scheduling and retries."""

        return self.worker.run_once()

    def dispose(self) -> None:
        """Release this runtime's database resources."""

        self.engine.dispose()


def build_restricted_execution_worker(
    database_url: str,
) -> RestrictedExecutionWorkerRuntime:
    """Compose durable state with pinned transport without starting a worker loop."""

    engine = create_engine(database_url, pool_pre_ping=True)
    sessions = sessionmaker(engine, expire_on_commit=False)

    worker = RestrictedExecutionWorker(
        jobs=SqlAlchemyExecutionJobQueue(sessions),
        executor=RestrictedExecutionExecutor(
            resolver=_address_resolver(),
            transport=PinnedHttpxExecutionTransport(),
            cancellation_probe=SqlAlchemyExecutionJobCancellationProbe(sessions),
        ),
        results=SqlAlchemyExecutionResultRepository(sessions),
    )
    return RestrictedExecutionWorkerRuntime(
        worker=worker,
        engine=engine,
    )


def _address_resolver() -> AddressResolver:
    """Keep the production DNS adapter behind the existing resolver protocol."""

    return SocketAddressResolver()
