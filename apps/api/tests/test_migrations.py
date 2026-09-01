from pathlib import Path
from typing import Protocol, cast

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from ai_qa_copilot_api.migration_config import database_url_from_environment


ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_CONFIG = ROOT / "apps" / "api" / "alembic.ini"
EXPECTED_REVISION = "0006_create_parser_jobs"
PARSER_JOB_REVISION = "0006_create_parser_jobs"
DOCUMENT_INTAKE_REVISION = "0005_create_document_intakes"
DOCUMENT_PROVENANCE_REVISION = "0004_create_document_provenance"
ANALYSIS_RUN_REVISION = "0003_create_analysis_runs"
PROJECT_REVISION = "0002_create_projects"
INITIAL_REVISION = "0001_enable_pgvector"


class MigrationOperations(Protocol):
    def execute(self, statement: str) -> None: ...


class MigrationModule(Protocol):
    op: MigrationOperations

    def upgrade(self) -> None: ...

    def downgrade(self) -> None: ...


def migration_script(revision_id: str) -> MigrationModule:
    config = Config(str(ALEMBIC_CONFIG))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(revision_id)
    assert revision is not None
    return cast(MigrationModule, revision.module)


def test_database_url_is_read_from_environment_only() -> None:
    expected = "postgresql+psycopg://user:password@127.0.0.1:5432/example"

    assert database_url_from_environment({"DATABASE_URL": expected}) == expected
    with pytest.raises(RuntimeError, match="DATABASE_URL must be set"):
        database_url_from_environment({})


def test_alembic_has_reversible_project_head_after_pgvector_baseline() -> None:
    config = Config(str(ALEMBIC_CONFIG))
    script = ScriptDirectory.from_config(config)

    assert config.get_main_option("sqlalchemy.url") is None
    assert script.get_heads() == [EXPECTED_REVISION]
    revision = script.get_revision(EXPECTED_REVISION)
    assert revision is not None
    assert revision.down_revision == DOCUMENT_INTAKE_REVISION
    intake_revision = script.get_revision(DOCUMENT_INTAKE_REVISION)
    assert intake_revision is not None
    assert intake_revision.down_revision == DOCUMENT_PROVENANCE_REVISION
    document_revision = script.get_revision(DOCUMENT_PROVENANCE_REVISION)
    assert document_revision is not None
    assert document_revision.down_revision == ANALYSIS_RUN_REVISION
    analysis_run_revision = script.get_revision(ANALYSIS_RUN_REVISION)
    assert analysis_run_revision is not None
    assert analysis_run_revision.down_revision == PROJECT_REVISION
    project_revision = script.get_revision(PROJECT_REVISION)
    assert project_revision is not None
    assert project_revision.down_revision == INITIAL_REVISION
    baseline = script.get_revision(INITIAL_REVISION)
    assert baseline is not None
    assert baseline.down_revision is None


def test_initial_migration_enables_and_removes_pgvector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration_script(INITIAL_REVISION)
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)

    module.upgrade()
    module.downgrade()

    assert statements == [
        "CREATE EXTENSION IF NOT EXISTS vector",
        "DROP EXTENSION IF EXISTS vector",
    ]


def test_project_migration_creates_and_removes_the_minimum_durable_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration_script(PROJECT_REVISION)
    calls: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        module.op,
        "create_table",
        lambda *args, **kwargs: calls.append(("create_table", args)),
    )
    monkeypatch.setattr(
        module.op,
        "create_index",
        lambda *args, **kwargs: calls.append(("create_index", args)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_index",
        lambda *args, **kwargs: calls.append(("drop_index", args)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_table",
        lambda *args, **kwargs: calls.append(("drop_table", args)),
    )

    module.upgrade()
    module.downgrade()

    assert [(name, args[0]) for name, args in calls] == [
        ("create_table", "projects"),
        ("create_index", "ix_projects_active_created_at"),
        ("drop_index", "ix_projects_active_created_at"),
        ("drop_table", "projects"),
    ]


def test_analysis_run_migration_creates_and_removes_the_run_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration_script(ANALYSIS_RUN_REVISION)
    calls: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        module.op,
        "create_table",
        lambda *args, **kwargs: calls.append(("create_table", args)),
    )
    monkeypatch.setattr(
        module.op,
        "create_index",
        lambda *args, **kwargs: calls.append(("create_index", args)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_index",
        lambda *args, **kwargs: calls.append(("drop_index", args)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_table",
        lambda *args, **kwargs: calls.append(("drop_table", args)),
    )

    module.upgrade()
    module.downgrade()

    assert [(name, args[0]) for name, args in calls] == [
        ("create_table", "analysis_runs"),
        ("create_index", "ix_analysis_runs_project_created_at"),
        ("drop_index", "ix_analysis_runs_project_created_at"),
        ("drop_table", "analysis_runs"),
    ]


def test_document_provenance_migration_creates_and_removes_the_ingestion_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration_script(DOCUMENT_PROVENANCE_REVISION)
    calls: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        module.op,
        "create_table",
        lambda *args, **kwargs: calls.append(("create_table", args)),
    )
    monkeypatch.setattr(
        module.op,
        "create_index",
        lambda *args, **kwargs: calls.append(("create_index", args)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_index",
        lambda *args, **kwargs: calls.append(("drop_index", args)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_table",
        lambda *args, **kwargs: calls.append(("drop_table", args)),
    )

    module.upgrade()
    module.downgrade()

    assert [(name, args[0]) for name, args in calls] == [
        ("create_table", "parser_versions"),
        ("create_table", "documents"),
        ("create_index", "ix_documents_project_created_at"),
        ("create_table", "document_versions"),
        ("create_index", "ix_document_versions_document_created_at"),
        ("create_table", "source_locations"),
        ("create_table", "document_sections"),
        ("create_table", "document_chunks"),
        ("create_index", "ix_document_chunks_version_ordinal"),
        ("drop_index", "ix_document_chunks_version_ordinal"),
        ("drop_table", "document_chunks"),
        ("drop_table", "document_sections"),
        ("drop_table", "source_locations"),
        ("drop_index", "ix_document_versions_document_created_at"),
        ("drop_table", "document_versions"),
        ("drop_index", "ix_documents_project_created_at"),
        ("drop_table", "documents"),
        ("drop_table", "parser_versions"),
    ]


def test_document_intake_migration_creates_and_removes_quarantine_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration_script(DOCUMENT_INTAKE_REVISION)
    calls: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        module.op,
        "create_table",
        lambda *args, **kwargs: calls.append(("create_table", args)),
    )
    monkeypatch.setattr(
        module.op,
        "create_index",
        lambda *args, **kwargs: calls.append(("create_index", args)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_index",
        lambda *args, **kwargs: calls.append(("drop_index", args)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_table",
        lambda *args, **kwargs: calls.append(("drop_table", args)),
    )

    module.upgrade()
    module.downgrade()

    assert [(name, args[0]) for name, args in calls] == [
        ("create_table", "document_intakes"),
        ("create_index", "ix_document_intakes_project_state_created_at"),
        ("create_index", "ix_document_intakes_project_content_hash"),
        ("drop_index", "ix_document_intakes_project_content_hash"),
        ("drop_index", "ix_document_intakes_project_state_created_at"),
        ("drop_table", "document_intakes"),
    ]


def test_parser_job_migration_creates_and_removes_only_opaque_queue_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration_script(PARSER_JOB_REVISION)
    calls: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        module.op,
        "create_table",
        lambda *args, **kwargs: calls.append(("create_table", args)),
    )
    monkeypatch.setattr(
        module.op,
        "drop_table",
        lambda *args, **kwargs: calls.append(("drop_table", args)),
    )

    module.upgrade()
    module.downgrade()

    assert [(name, args[0]) for name, args in calls] == [
        ("create_table", "parser_jobs"),
        ("drop_table", "parser_jobs"),
    ]
