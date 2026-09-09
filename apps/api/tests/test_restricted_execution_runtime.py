from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import socket
from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    ExecutionJobRecord,
    ExecutionJobState,
)
from ai_qa_copilot_api.projects import Base
from ai_qa_copilot_api.restricted_execution_runtime import (
    SocketAddressResolver,
    SqlAlchemyExecutionJobCancellationProbe,
    build_restricted_execution_worker,
)


NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)
RUNNING_JOB_ID = UUID("00000000-0000-0000-0000-000000000961")
CANCELLED_JOB_ID = UUID("00000000-0000-0000-0000-000000000962")
QUEUED_JOB_ID = UUID("00000000-0000-0000-0000-000000000963")


def test_socket_address_resolver_deduplicates_and_bounds_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda hostname, port, type: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                6,
                "",
                ("2001:4860:4860::8888", 0, 0, 0),
            ),
        ],
    )

    answer = SocketAddressResolver().resolve("ai-qa-sandbox.onrender.com")

    assert answer == ("8.8.8.8", "2001:4860:4860::8888")


def test_socket_address_resolver_returns_empty_answer_on_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_getaddrinfo(
        hostname: str,
        port: object,
        type: int,
    ) -> list[object]:
        del hostname, port, type
        raise OSError("DNS unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)

    assert SocketAddressResolver().resolve("ai-qa-sandbox.onrender.com") == ()


def test_cancellation_probe_fails_closed_for_cancelled_unknown_and_nonrunning_jobs(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'execution-runtime.db'}"
    engine = create_engine(database_url)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    probe = SqlAlchemyExecutionJobCancellationProbe(sessions)

    try:
        Base.metadata.create_all(engine)
        with sessions.begin() as session:
            session.add_all(
                [
                    execution_job(
                        job_id=RUNNING_JOB_ID,
                        state=ExecutionJobState.RUNNING,
                        started_at=NOW,
                        cancel_requested_at=None,
                    ),
                    execution_job(
                        job_id=CANCELLED_JOB_ID,
                        state=ExecutionJobState.RUNNING,
                        started_at=NOW,
                        cancel_requested_at=NOW,
                    ),
                    execution_job(
                        job_id=QUEUED_JOB_ID,
                        state=ExecutionJobState.QUEUED,
                        started_at=None,
                        cancel_requested_at=None,
                    ),
                ]
            )

        assert probe.is_cancel_requested(RUNNING_JOB_ID) is False
        assert probe.is_cancel_requested(CANCELLED_JOB_ID) is True
        assert probe.is_cancel_requested(QUEUED_JOB_ID) is True
        assert probe.is_cancel_requested(uuid4()) is True
    finally:
        engine.dispose()


def test_runtime_factory_does_not_start_dns_or_http_work_for_an_empty_queue(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-runtime.db'}"
    runtime = build_restricted_execution_worker(database_url)

    try:
        Base.metadata.create_all(runtime.engine)

        run = runtime.run_once()

        assert run.claimed_job_id is None
        assert run.execution_result is None
        assert run.stored_result is None
    finally:
        runtime.dispose()


def execution_job(
    *,
    job_id: UUID,
    state: ExecutionJobState,
    started_at: datetime | None,
    cancel_requested_at: datetime | None,
) -> ExecutionJobRecord:
    return ExecutionJobRecord(
        id=job_id,
        project_id=UUID("00000000-0000-0000-0000-000000000964"),
        execution_approval_id=uuid5(job_id, "execution-runtime-test-approval"),
        plan_id=UUID("00000000-0000-0000-0000-000000000966"),
        plan_hash="a" * 64,
        state=state.value,
        created_at=NOW,
        started_at=started_at,
        finished_at=None,
        cancel_requested_at=cancel_requested_at,
        cancelled_at=None,
    )
