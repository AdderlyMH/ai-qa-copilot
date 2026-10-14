from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from ai_qa_copilot_api.analysis_runs import analysis_run_repository_from_environment
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.citations import citation_repository_from_environment
from ai_qa_copilot_api.database_engine import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DatabaseEngineUnavailable,
    create_shared_engine,
    database_engine_from_environment,
    session_factory,
)
from ai_qa_copilot_api.execution_approvals import (
    execution_approval_repository_from_environment,
)
from ai_qa_copilot_api.execution_jobs import execution_job_queue_from_environment
from ai_qa_copilot_api.execution_results import (
    execution_result_repository_from_environment,
)
from ai_qa_copilot_api.finding_feedback import (
    finding_feedback_repository_from_environment,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import (
    UnavailableProjectRepository,
    project_repository_from_environment,
)
from ai_qa_copilot_api.quality_report_revisions import (
    quality_report_revision_repository_from_environment,
)
from ai_qa_copilot_api.requirements_analysis import (
    requirement_analysis_repository_from_environment,
)


FAKE_POSTGRES_URL = "postgresql+psycopg://app:not-a-secret@db.invalid:5432/app"


class _StopBeforeConnect(Exception):
    pass


def _bound_engine(repository: Any) -> object:
    factory = repository._session_factory  # noqa: SLF001 - composition assertion
    return factory.kw["bind"]


def _captured_connect_params(engine: Engine) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    @event.listens_for(engine, "do_connect")
    def capture(dialect: object, record: object, cargs: object, cparams: Any) -> None:
        captured.update(cparams)
        raise _StopBeforeConnect

    with pytest.raises(_StopBeforeConnect):
        engine.connect()
    return captured


def test_shared_engine_uses_null_pool_without_pre_ping(tmp_path: Path) -> None:
    engine = create_shared_engine(f"sqlite+pysqlite:///{tmp_path / 'engine.db'}")

    assert isinstance(engine.pool, NullPool)
    assert engine.pool._pre_ping is False  # noqa: SLF001 - pool configuration


def test_shared_engine_keeps_no_idle_connection_after_use(tmp_path: Path) -> None:
    engine = create_shared_engine(f"sqlite+pysqlite:///{tmp_path / 'engine.db'}")
    opened: list[object] = []
    closed: list[object] = []
    event.listen(engine, "connect", lambda connection, record: opened.append(record))
    event.listen(engine.pool, "close", lambda connection, record: closed.append(record))

    sessions = session_factory(engine)
    for _ in range(2):
        with sessions() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1

    assert len(opened) == 2
    assert len(closed) == 2


def test_postgres_url_gets_default_connect_timeout() -> None:
    engine = create_shared_engine(FAKE_POSTGRES_URL)

    params = _captured_connect_params(engine)

    assert params["connect_timeout"] == DEFAULT_CONNECT_TIMEOUT_SECONDS
    assert "connect_timeout" not in engine.url.query


def test_postgres_url_connect_timeout_is_read_from_url() -> None:
    engine = create_shared_engine(f"{FAKE_POSTGRES_URL}?connect_timeout=25")

    params = _captured_connect_params(engine)

    assert params["connect_timeout"] == 25
    assert "connect_timeout" not in engine.url.query


@pytest.mark.parametrize("value", ["0", "-3", "soon"])
def test_postgres_url_rejects_invalid_connect_timeout(value: str) -> None:
    with pytest.raises(DatabaseEngineUnavailable, match="connect_timeout") as error:
        create_shared_engine(f"{FAKE_POSTGRES_URL}?connect_timeout={value}")

    assert "not-a-secret" not in str(error.value)


def test_postgres_url_rejects_repeated_connect_timeout() -> None:
    with pytest.raises(DatabaseEngineUnavailable, match="repeated"):
        create_shared_engine(f"{FAKE_POSTGRES_URL}?connect_timeout=5&connect_timeout=6")


def test_sqlite_url_gets_no_connect_timeout(tmp_path: Path) -> None:
    engine = create_shared_engine(f"sqlite+pysqlite:///{tmp_path / 'engine.db'}")

    params = _captured_connect_params(engine)

    assert "connect_timeout" not in params


@pytest.mark.parametrize("value", ["", "   "])
def test_missing_database_url_fails_closed(value: str) -> None:
    with pytest.raises(DatabaseEngineUnavailable, match="not configured"):
        create_shared_engine(value)
    with pytest.raises(DatabaseEngineUnavailable, match="not configured"):
        database_engine_from_environment({"DATABASE_URL": value})
    with pytest.raises(DatabaseEngineUnavailable, match="not configured"):
        database_engine_from_environment({})


def test_invalid_database_url_fails_closed_without_echoing_it() -> None:
    with pytest.raises(DatabaseEngineUnavailable, match="not a valid") as error:
        create_shared_engine("not a url with secret-password")

    assert "secret-password" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_repositories_from_shared_engine_share_one_engine(tmp_path: Path) -> None:
    engine = create_shared_engine(f"sqlite+pysqlite:///{tmp_path / 'engine.db'}")

    repositories = [
        project_repository_from_environment(engine=engine),
        citation_repository_from_environment(engine=engine),
        analysis_run_repository_from_environment(engine=engine),
        requirement_analysis_repository_from_environment(engine=engine),
        finding_feedback_repository_from_environment(engine=engine),
        execution_approval_repository_from_environment(engine=engine),
        execution_job_queue_from_environment(engine=engine),
        execution_result_repository_from_environment(engine=engine),
        quality_report_revision_repository_from_environment(engine=engine),
    ]

    assert all(_bound_engine(repository) is engine for repository in repositories)


def test_factories_without_engine_keep_existing_fail_closed_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert isinstance(
        project_repository_from_environment(), UnavailableProjectRepository
    )


def _local_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


def test_create_app_injects_one_shared_engine_when_database_url_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    application = create_app(_local_settings())

    with TestClient(application):
        state = application.state
        engine = state.database_engine
        assert isinstance(engine, Engine)
        assert isinstance(engine.pool, NullPool)
        bound = [
            _bound_engine(state.project_repository),
            _bound_engine(state.citation_repository),
            _bound_engine(state.requirement_analysis_repository),
            _bound_engine(state.finding_feedback_repository),
            _bound_engine(state.execution_approval_repository),
            _bound_engine(state.execution_job_queue),
            _bound_engine(state.execution_result_repository),
            _bound_engine(state.quality_report_revision_repository),
            _bound_engine(
                state.quality_report_generation_service._evidence_collector  # noqa: SLF001
            ),
        ]
        assert all(item is engine for item in bound)


def test_create_app_without_database_url_builds_no_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    application = create_app(_local_settings())

    with TestClient(application):
        assert application.state.database_engine is None
        assert isinstance(
            application.state.project_repository, UnavailableProjectRepository
        )
