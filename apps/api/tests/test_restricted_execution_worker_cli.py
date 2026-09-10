from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from uuid import UUID

import pytest

from ai_qa_copilot_api import restricted_execution_worker_cli as worker_cli
from ai_qa_copilot_api.documents import ExecutionResultOutcome
from ai_qa_copilot_api.execution_results import StoredExecutionResult
from ai_qa_copilot_api.execution_worker import ExecutionWorkerRun
from ai_qa_copilot_api.generated_tests import HttpMethod
from ai_qa_copilot_api.restricted_execution import (
    ExecutionOutcome,
    ExecutionResult,
    RedactedRequestEvidence,
    RedactedResponseEvidence,
)


@dataclass
class FakeRuntime:
    run: ExecutionWorkerRun | None = None
    error: Exception | None = None
    run_calls: int = 0
    dispose_calls: int = 0

    def run_once(self) -> ExecutionWorkerRun:
        self.run_calls += 1
        if self.error is not None:
            raise self.error
        assert self.run is not None
        return self.run

    def dispose(self) -> None:
        self.dispose_calls += 1


def test_worker_cli_requires_the_exact_explicit_enablement_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///unused.db")
    monkeypatch.delenv(worker_cli.WORKER_ENABLED_ENVIRONMENT_VARIABLE, raising=False)

    assert worker_cli.main() == 2

    captured = capsys.readouterr()
    assert "disabled" in captured.err
    assert "queued job" not in captured.out


def test_worker_cli_requires_database_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(worker_cli.WORKER_ENABLED_ENVIRONMENT_VARIABLE, "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert worker_cli.main() == 2

    captured = capsys.readouterr()
    assert captured.err == "Restricted execution worker requires DATABASE_URL.\n"


def test_worker_cli_runs_once_and_disposes_an_idle_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(
        run=ExecutionWorkerRun(
            claimed_job_id=None,
            execution_result=None,
            stored_result=None,
        )
    )

    def build(database_url: str) -> FakeRuntime:
        assert database_url == "sqlite+pysqlite:///worker.db"
        return runtime

    monkeypatch.setenv(worker_cli.WORKER_ENABLED_ENVIRONMENT_VARIABLE, "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///worker.db")
    monkeypatch.setattr(worker_cli, "build_restricted_execution_worker", build)

    assert worker_cli.main() == 0

    captured = capsys.readouterr()
    assert captured.out == "Restricted execution worker found no queued job.\n"
    assert runtime.run_calls == 1
    assert runtime.dispose_calls == 1


def test_worker_cli_returns_safe_failure_when_runtime_raises(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(error=RuntimeError("token=must-not-be-disclosed"))

    def build(database_url: str) -> FakeRuntime:
        assert database_url == "sqlite+pysqlite:///worker.db"
        return runtime

    monkeypatch.setenv(worker_cli.WORKER_ENABLED_ENVIRONMENT_VARIABLE, "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///worker.db")
    monkeypatch.setattr(worker_cli, "build_restricted_execution_worker", build)

    assert worker_cli.main() == 1

    captured = capsys.readouterr()
    assert captured.err == "Restricted execution worker did not complete safely.\n"
    assert "token" not in captured.err
    assert runtime.run_calls == 1
    assert runtime.dispose_calls == 1


def test_worker_cli_never_prints_execution_evidence_canaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canary = "exec-006-worker-cli-canary"
    job_id = UUID("00000000-0000-0000-0000-000000000983")

    runtime = FakeRuntime(
        run=ExecutionWorkerRun(
            claimed_job_id=job_id,
            execution_result=ExecutionResult(
                job_id=job_id,
                outcome=ExecutionOutcome.SUCCEEDED,
                assertion_results=(),
                request_evidence=RedactedRequestEvidence(
                    method=HttpMethod.POST,
                    url=f"https://example.test/orders?token={canary}",
                    headers=(("X-Api-Token", canary),),
                    json_body={"password": canary},
                ),
                response_evidence=RedactedResponseEvidence(
                    status_code=201,
                    headers=(("Set-Cookie", canary),),
                    json_body={"nested": {"secret": canary}},
                    body_bytes=20,
                    body_sha256="a" * 64,
                    elapsed_ms=25,
                ),
                error_code=None,
                error_message=None,
                transport_send_count=1,
            ),
            stored_result=StoredExecutionResult(
                id=UUID("00000000-0000-0000-0000-000000000984"),
                execution_job_id=job_id,
                outcome=ExecutionResultOutcome.SUCCEEDED,
                failure_code=None,
                assertion_results_json=json.dumps(
                    [{"token": canary}],
                    separators=(",", ":"),
                ),
                request_evidence_json=json.dumps(
                    {"password": canary},
                    separators=(",", ":"),
                ),
                response_evidence_json=json.dumps(
                    {"secret": canary},
                    separators=(",", ":"),
                ),
                transport_send_count=1,
                recorded_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            ),
        )
    )

    def build(database_url: str) -> FakeRuntime:
        assert database_url == "sqlite+pysqlite:///worker.db"
        return runtime

    monkeypatch.setenv(worker_cli.WORKER_ENABLED_ENVIRONMENT_VARIABLE, "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///worker.db")
    monkeypatch.setattr(worker_cli, "build_restricted_execution_worker", build)

    assert worker_cli.main() == 0

    captured = capsys.readouterr()
    assert canary not in captured.out
    assert canary not in captured.err
    assert captured.err == ""
    assert captured.out == (
        f"Restricted execution worker completed job {job_id} with outcome succeeded.\n"
    )
    assert runtime.run_calls == 1
    assert runtime.dispose_calls == 1
