from pathlib import Path
from typing import Protocol, cast

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from ai_qa_copilot_api.migration_config import database_url_from_environment


ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_CONFIG = ROOT / "apps" / "api" / "alembic.ini"
EXPECTED_REVISION = "0001_enable_pgvector"


class MigrationOperations(Protocol):
    def execute(self, statement: str) -> None: ...


class MigrationModule(Protocol):
    op: MigrationOperations

    def upgrade(self) -> None: ...

    def downgrade(self) -> None: ...


def migration_script() -> MigrationModule:
    config = Config(str(ALEMBIC_CONFIG))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(EXPECTED_REVISION)
    assert revision is not None
    return cast(MigrationModule, revision.module)


def test_database_url_is_read_from_environment_only() -> None:
    expected = "postgresql+psycopg://user:password@127.0.0.1:5432/example"

    assert database_url_from_environment({"DATABASE_URL": expected}) == expected
    with pytest.raises(RuntimeError, match="DATABASE_URL must be set"):
        database_url_from_environment({})


def test_alembic_has_one_reversible_baseline_revision() -> None:
    config = Config(str(ALEMBIC_CONFIG))
    script = ScriptDirectory.from_config(config)

    assert config.get_main_option("sqlalchemy.url") is None
    assert script.get_heads() == [EXPECTED_REVISION]
    revision = script.get_revision(EXPECTED_REVISION)
    assert revision is not None
    assert revision.down_revision is None


def test_initial_migration_enables_and_removes_pgvector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration_script()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)

    module.upgrade()
    module.downgrade()

    assert statements == [
        "CREATE EXTENSION IF NOT EXISTS vector",
        "DROP EXTENSION IF EXISTS vector",
    ]
