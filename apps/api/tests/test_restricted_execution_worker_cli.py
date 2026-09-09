from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai_qa_copilot_api.execution_worker import ExecutionWorkerRun
from ai_qa_copilot_api import restricted_execution_worker_cli as worker_cli


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
