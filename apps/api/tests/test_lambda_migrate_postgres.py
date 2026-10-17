"""Migration runner against the isolated db-check PostgreSQL (INFRA-012).

Run by ``scripts/tasks.py db-check`` after the database is at head; skipped
otherwise. The local database has no TLS, so these tests build connections
without ``sslmode=require`` and exercise the runner's database layer, SCRAM
verifier, grants and failed-upgrade behaviour directly.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
import os
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy.engine import URL, make_url

from ai_qa_copilot_api.lambda_migrate import (
    APPEND_ONLY_TABLES,
    MUTABLE_TABLES,
    MigrationRunner,
    MigrationRunnerError,
    PsycopgMigrationDatabase,
    alembic_upgrade_to_head,
    app_user_statements,
    grant_statements,
    head_revision,
    scram_sha256_verifier,
)


pytestmark = pytest.mark.postgres_integration

ROOT = Path(__file__).resolve().parents[3]
POSTGRES_INTEGRATION_DATABASE_URL = "AI_QA_COPILOT_POSTGRES_INTEGRATION_DATABASE_URL"
PROBE_PASSWORD_SENTINEL = "integration-probe-sentinel"


@pytest.fixture
def database_url() -> URL:
    raw = os.environ.get(POSTGRES_INTEGRATION_DATABASE_URL, "").strip()
    if not raw:
        pytest.skip("requires the isolated PostgreSQL database from db-check")
    return make_url(raw)


def conninfo(url: URL, *, user: str | None = None, password: str | None = None) -> str:
    return psycopg.conninfo.make_conninfo(
        host=url.host or "",
        port=str(url.port or 5432),
        dbname=url.database or "",
        user=user or url.username or "",
        password=password if password is not None else (url.password or ""),
        sslmode="disable",
    )


@pytest.fixture
def database(database_url: URL) -> Iterator[PsycopgMigrationDatabase]:
    connection = psycopg.connect(conninfo(database_url), autocommit=True)
    wrapped = PsycopgMigrationDatabase(connection)
    try:
        yield wrapped
    finally:
        wrapped.close()


def test_revision_reads_the_packaged_head(database: PsycopgMigrationDatabase) -> None:
    assert database.current_revision() == head_revision()


def test_pgvector_version_is_read_from_pg_extension(
    database: PsycopgMigrationDatabase,
) -> None:
    row = database._connection.execute(
        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
    ).fetchone()

    assert row is not None
    assert database.vector_version() == row[0]


def test_the_advisory_lock_excludes_a_second_session(
    database_url: URL, database: PsycopgMigrationDatabase
) -> None:
    other = PsycopgMigrationDatabase(
        psycopg.connect(conninfo(database_url), autocommit=True)
    )
    try:
        assert database.try_lock()
        assert not other.try_lock()
        database.unlock()
        assert other.try_lock()
        other.unlock()
    finally:
        other.close()


def test_scram_verifier_login_and_grants(
    database_url: URL, database: PsycopgMigrationDatabase
) -> None:
    role = f"runner_test_{uuid4().hex[:12]}"
    future_table = f"runner_future_probe_{uuid4().hex[:8]}"
    password = f"pw-{uuid4().hex}"
    master = database_url.username or ""
    tables = database.public_tables()
    assert set(tables) == MUTABLE_TABLES | APPEND_ONLY_TABLES
    statements = app_user_statements(
        role=role,
        password_verifier=scram_sha256_verifier(password),
        database=database_url.database or "",
        master_role=master,
        tables=tables,
        create=True,
    )
    try:
        database.execute_in_transaction(statements)
        assert database.role_exists(role)

        with psycopg.connect(
            conninfo(database_url, user=role, password=password)
        ) as app:
            assert app.execute("SELECT current_user").fetchone() == (role,)

        def privilege(table: str, kind: str) -> bool:
            row = database._connection.execute(
                "SELECT has_table_privilege(%s, %s, %s)",
                (role, f"public.{table}", kind),
            ).fetchone()
            return bool(row and row[0])

        for table in tables:
            assert privilege(table, "SELECT") and privilege(table, "INSERT")
            assert privilege(table, "UPDATE") is (table in MUTABLE_TABLES), table
            assert not privilege(table, "DELETE"), table
            assert not privilege(table, "TRUNCATE")
        assert not privilege("alembic_version", "SELECT")

        # The same rules, exercised as the application role itself.
        with psycopg.connect(
            conninfo(database_url, user=role, password=password), autocommit=True
        ) as app:
            app.execute(
                "UPDATE public.projects SET archived_at = archived_at WHERE false"
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app.execute("UPDATE public.analysis_runs SET id = id WHERE false")
            for table in ("projects", "parser_jobs", "analysis_runs"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute(
                        sql.SQL("DELETE FROM {} WHERE false").format(
                            sql.Identifier("public", table)
                        )
                    )

        # A table created later by the master role gets SELECT, INSERT only,
        # also after the grants are re-applied (apply_grants) while it is in
        # neither list.
        database._connection.execute(
            sql.SQL("CREATE TABLE {} (id integer)").format(
                sql.Identifier("public", future_table)
            )
        )
        assert privilege(future_table, "SELECT") and privilege(future_table, "INSERT")
        assert not privilege(future_table, "UPDATE")
        assert not privilege(future_table, "DELETE")
        database.execute_in_transaction(
            grant_statements(
                role=role,
                database=database_url.database or "",
                master_role=master,
                tables=database.public_tables(),
            )
        )
        assert privilege(future_table, "INSERT")
        assert not privilege(future_table, "UPDATE")
        assert not privilege(future_table, "DELETE")
        row = database._connection.execute(
            "SELECT has_schema_privilege(%s, 'public', 'CREATE'), "
            "rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = %s",
            (role, role),
        ).fetchone()
        assert row == (False, False, False, False)

        # Rotation: the old password stops working, the new one works.
        new_password = f"pw-{uuid4().hex}"
        database.execute_in_transaction(
            app_user_statements(
                role=role,
                password_verifier=scram_sha256_verifier(new_password),
                database=database_url.database or "",
                master_role=master,
                tables=tables,
                create=False,
            )
        )
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(
                conninfo(database_url, user=role, password=password)
            ).close()
        psycopg.connect(
            conninfo(database_url, user=role, password=new_password)
        ).close()
    finally:
        database._connection.execute(
            sql.SQL("DROP TABLE IF EXISTS {}").format(
                sql.Identifier("public", future_table)
            )
        )
        role_id = sql.Identifier(role)
        master_id = sql.Identifier(master)
        for statement in (
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "REVOKE ALL ON TABLES FROM {}"
            ).format(master_id, role_id),
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "REVOKE ALL ON SEQUENCES FROM {}"
            ).format(master_id, role_id),
            sql.SQL("DROP OWNED BY {}").format(role_id),
            sql.SQL("DROP ROLE IF EXISTS {}").format(role_id),
        ):
            if database.role_exists(role):
                database._connection.execute(statement)


@pytest.fixture
def failing_scripts(tmp_path: Path) -> Path:
    """A copy of the migrations plus one revision that fails after DDL."""

    source = ROOT / "apps/api/alembic"
    target = tmp_path / "alembic"
    (target / "versions").mkdir(parents=True)
    shutil.copy(source / "env.py", target / "env.py")
    shutil.copy(source / "script.py.mako", target / "script.py.mako")
    for path in (source / "versions").glob("0*.py"):
        shutil.copy(path, target / "versions" / path.name)
    head = head_revision()
    (target / "versions" / "0999_runner_failure_probe.py").write_text(
        "from alembic import op\n"
        "revision = '0999_runner_failure_probe'\n"
        f"down_revision = {head!r}\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade() -> None:\n"
        "    op.execute('CREATE TABLE runner_failure_probe (id integer)')\n"
        f"    raise RuntimeError('probe failure {PROBE_PASSWORD_SENTINEL}')\n"
        "def downgrade() -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    ini = tmp_path / "alembic.ini"
    ini.write_text(
        "[alembic]\nscript_location = %(here)s/alembic\nprepend_sys_path = .\n"
        "path_separator = os\n",
        encoding="utf-8",
    )
    return ini


def test_a_failed_upgrade_leaves_the_revision_and_schema_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    database_url: URL,
    database: PsycopgMigrationDatabase,
    failing_scripts: Path,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    head = head_revision()
    local_url = database_url.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )

    class Secrets:
        def get_secret_value(self, **kwargs: Any) -> Mapping[str, Any]:
            return {
                "SecretString": json.dumps(
                    {"username": "copilot_master", "password": "unused-in-this-test"}
                )
            }

        def put_secret_value(self, **kwargs: Any) -> Mapping[str, Any]:
            raise AssertionError("not called")

    runner = MigrationRunner(
        environ={
            "MASTER_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:rds!db-x",
            "DATABASE_URL_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:u",
            "DB_HOST": "localhost",
            "DB_PORT": "5432",
            "DB_NAME": "ai_qa_copilot",
        },
        client_factory=Secrets,
        connect=lambda settings, credentials: database,
        upgrade=lambda _url: alembic_upgrade_to_head(local_url, failing_scripts),
        head=lambda: head_revision(failing_scripts),
    )

    with pytest.raises(MigrationRunnerError) as raised:
        runner({"action": "migrate"})

    assert str(raised.value) == (
        f"Upgrade failed (RuntimeError); revision before {head}, after {head}"
    )
    assert PROBE_PASSWORD_SENTINEL not in str(raised.value)
    assert "DATABASE_URL" not in os.environ
    check = PsycopgMigrationDatabase(
        psycopg.connect(conninfo(database_url), autocommit=True)
    )
    try:
        assert check.current_revision() == head
        assert check._connection.execute(
            "SELECT to_regclass('public.runner_failure_probe')"
        ).fetchone() == (None,)
        assert check.try_lock()  # released by the failed run
        check.unlock()
    finally:
        check.close()
