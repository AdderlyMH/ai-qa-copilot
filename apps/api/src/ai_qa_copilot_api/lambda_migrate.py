"""One-shot migration runner Lambda (INFRA-012, ADR-018, ADR-020).

Container CMD (``migrate`` target): ``ai_qa_copilot_api.lambda_migrate.handler``.
The owner invokes it manually; it has no API, event source or schedule.

Actions (event field ``action``; an empty event means ``migrate``):

- ``status``: read the revision in ``alembic_version``, compare it with the
  head of the packaged migration scripts, and report the installed pgvector
  version (``pgvector_version``; ``migrate`` reports it too).
- ``migrate``: take a PostgreSQL advisory lock (a second run fails instead of
  waiting), run ``alembic upgrade head`` and read the revision back. ``env.py``
  runs every pending migration in one transaction (``transaction_per_migration``
  is not set and PostgreSQL has transactional DDL), so a failed upgrade leaves
  the revision unchanged; the error reports the revision read back afterwards.
- ``create_app_user``: create the non-superuser application role with a
  generated password and least-privilege grants, then write its PostgreSQL URL
  to the ``database-url`` secret. If the role exists the action fails unless the
  event has ``"rotate": true``, which resets the password and rewrites the URL.
- ``apply_grants``: under the same lock, re-apply the grants for the existing
  role (no password change, no secret write); this is how a table added to
  ``MUTABLE_TABLES`` gets UPDATE without a rotation. It never touches the
  parser role.
- ``create_parser_user`` (INFRA-008 Stage B, ADR-018 fallback): the same flow
  for the parser role (``PARSER_DB_USER``), with only the grants in
  ``PARSER_TABLE_GRANTS``; its URL goes to the secret named by
  ``PARSER_DATABASE_URL_SECRET_ARN``. ``rotate`` also re-applies its grants.

Application-role grants: SELECT, INSERT on every table; UPDATE only on
``MUTABLE_TABLES``; DELETE nowhere; a table in neither list gets SELECT, INSERT
(fail closed); future tables default to SELECT, INSERT.

Credentials: the RDS-managed master secret (``MASTER_SECRET_ARN``) is read at
invocation; host, port and database name come from non-secret environment
variables. Every connection and every URL written uses
``sslmode=verify-full`` against the RDS CA bundle at ``RDS_CA_BUNDLE_PATH``,
which every Lambda image contains. The master password reaches Alembic only through
``DATABASE_URL`` in this process for the duration of the upgrade, because the
unchanged ``env.py`` reads it from there.

The application password is sent to PostgreSQL only as a SCRAM-SHA-256 verifier
computed here, which PostgreSQL stores as-is, so no SQL text, server log entry,
exception, log record or response contains it. SQL is composed only with
``psycopg.sql`` (``Identifier`` and ``Literal``). Every error is a
``MigrationRunnerError`` naming the logical step and an AWS error code or
exception type only; the original exception is not chained. Responses contain
revision identifiers, booleans and counts only.
"""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import threading
from typing import Any, Protocol

from botocore.exceptions import ClientError
from psycopg import sql


MASTER_SECRET_ARN_ENVIRONMENT_VARIABLE = "MASTER_SECRET_ARN"
DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE = "DATABASE_URL_SECRET_ARN"
DB_HOST_ENVIRONMENT_VARIABLE = "DB_HOST"
DB_PORT_ENVIRONMENT_VARIABLE = "DB_PORT"
DB_NAME_ENVIRONMENT_VARIABLE = "DB_NAME"
APP_DB_USER_ENVIRONMENT_VARIABLE = "APP_DB_USER"
DEFAULT_APP_DB_USER = "ai_qa_copilot_app"
PARSER_DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE = "PARSER_DATABASE_URL_SECRET_ARN"
PARSER_DB_USER_ENVIRONMENT_VARIABLE = "PARSER_DB_USER"
DEFAULT_PARSER_DB_USER = "ai_qa_copilot_parser"
# The public RDS CA bundle copied into every Lambda image (Dockerfile.lambda).
# Every URL this runner builds or writes verifies the server against it.
RDS_CA_BUNDLE_PATH = "/var/task/certs/rds-global-bundle.pem"

ACTIONS = frozenset(
    {"migrate", "status", "create_app_user", "apply_grants", "create_parser_user"}
)
# Arbitrary fixed key for pg_try_advisory_lock; every runner action that writes
# takes it, so two writing runs never overlap.
ADVISORY_LOCK_KEY = 4_812_012_009
APP_PASSWORD_BYTES = 32
SCRAM_ITERATIONS = 4096
CONNECT_TIMEOUT_SECONDS = 10

# Tables the application updates at run time (ORM updates, row locks with
# SELECT ... FOR UPDATE, which PostgreSQL allows only with UPDATE privilege):
# SELECT, INSERT, UPDATE. Every other table is append-only for the application
# role: SELECT, INSERT. The application never deletes rows, so no table gets
# DELETE. A contract test keeps this split in step with the migrations.
MUTABLE_TABLES = frozenset(
    {
        "document_versions",  # parser promotion sets parser_version_id
        "execution_approvals",  # consumption
        "execution_jobs",  # claim, terminal state, FOR UPDATE
        "indexing_jobs",  # claims and leases
        "parser_jobs",  # claims and leases
        "projects",  # archived_at
        # Rows are never updated; UPDATE is needed only because the code takes
        # SELECT ... FOR UPDATE locks. Immutability rests on application code.
        "quality_report_revisions",
    }
)
APPEND_ONLY_TABLES = frozenset(
    {
        "analysis_runs",
        "citations",
        "document_chunk_embeddings",
        "document_chunks",
        "document_intakes",
        "document_sections",
        "documents",
        "embedding_cache_entries",
        "evaluation_review_adjudications",
        "evaluation_review_disagreements",
        "evaluation_review_labels",
        "evaluation_reviewer_attestations",
        "execution_results",
        "finding_feedback",
        "parser_versions",
        "requirement_analysis_runs",
        "requirement_findings",
        "retrieval_trace_candidates",
        "retrieval_traces",
        "source_locations",
    }
)
_IGNORED_TABLES = frozenset({"alembic_version"})

# The parser role (ADR-018 fallback, INFRA-008 Stage B): exactly what the parser
# handler's code path does (parser_job_claims.py, parser_evidence_promotion.py),
# and nothing on any other table. No DELETE, no default privileges.
PARSER_TABLE_GRANTS = {
    # claim, lease renewal, accept/reject/fail, reaping
    "parser_jobs": sql.SQL("GRANT SELECT, UPDATE ON TABLE {} TO {}"),
    # parser_version_id set on promotion
    "document_versions": sql.SQL("GRANT SELECT, UPDATE ON TABLE {} TO {}"),
    # first-use insert of the parser version row
    "parser_versions": sql.SQL("GRANT SELECT, INSERT ON TABLE {} TO {}"),
    # evidence rows (an existence check reads them first)
    "source_locations": sql.SQL("GRANT SELECT, INSERT ON TABLE {} TO {}"),
    "document_sections": sql.SQL("GRANT SELECT, INSERT ON TABLE {} TO {}"),
    # the queued indexing job created with the promotion
    "indexing_jobs": sql.SQL("GRANT SELECT, INSERT ON TABLE {} TO {}"),
    # read only: source checks
    "document_intakes": sql.SQL("GRANT SELECT ON TABLE {} TO {}"),
    "documents": sql.SQL("GRANT SELECT ON TABLE {} TO {}"),
}

_SAFE_ERROR_CODE = re.compile(r"[A-Za-z0-9.]{1,64}")
_SECRET_ARN = re.compile(r"arn:aws[a-z-]*:secretsmanager:[a-z0-9-]+:\d{12}:secret:.+")
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}")

_logger = logging.getLogger(__name__)
_environment_lock = threading.Lock()


class MigrationRunnerError(RuntimeError):
    """A runner step failed; the message carries no secret or identifier."""


# --- Settings and credentials ---------------------------------------------------


@dataclass(frozen=True)
class RunnerSettings:
    master_secret_arn: str
    database_url_secret_arn: str
    host: str
    port: int
    database: str
    app_user: str
    parser_database_url_secret_arn: str | None = None
    parser_user: str = DEFAULT_PARSER_DB_USER

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> RunnerSettings:
        def required(name: str) -> str:
            value = environ.get(name, "").strip()
            if not value:
                raise MigrationRunnerError(f"{name} must be configured")
            return value

        master_arn = required(MASTER_SECRET_ARN_ENVIRONMENT_VARIABLE)
        url_arn = required(DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE)
        for name, arn in (
            (MASTER_SECRET_ARN_ENVIRONMENT_VARIABLE, master_arn),
            (DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE, url_arn),
        ):
            if not _SECRET_ARN.fullmatch(arn):
                raise MigrationRunnerError(
                    f"{name} is not a Secrets Manager secret ARN"
                )
        host = required(DB_HOST_ENVIRONMENT_VARIABLE)
        if not _HOST.fullmatch(host):
            raise MigrationRunnerError(
                f"{DB_HOST_ENVIRONMENT_VARIABLE} is not a host name"
            )
        try:
            port = int(required(DB_PORT_ENVIRONMENT_VARIABLE))
        except ValueError:
            raise MigrationRunnerError(
                f"{DB_PORT_ENVIRONMENT_VARIABLE} must be an integer"
            ) from None
        if not 1 <= port <= 65535:
            raise MigrationRunnerError(
                f"{DB_PORT_ENVIRONMENT_VARIABLE} is out of range"
            )
        database = required(DB_NAME_ENVIRONMENT_VARIABLE)
        app_user = (
            environ.get(APP_DB_USER_ENVIRONMENT_VARIABLE, "").strip()
            or DEFAULT_APP_DB_USER
        )
        parser_user = (
            environ.get(PARSER_DB_USER_ENVIRONMENT_VARIABLE, "").strip()
            or DEFAULT_PARSER_DB_USER
        )
        for name, value in (
            (DB_NAME_ENVIRONMENT_VARIABLE, database),
            (APP_DB_USER_ENVIRONMENT_VARIABLE, app_user),
            (PARSER_DB_USER_ENVIRONMENT_VARIABLE, parser_user),
        ):
            if not _IDENTIFIER.fullmatch(value):
                raise MigrationRunnerError(f"{name} is not a lower-case SQL identifier")
        if parser_user == app_user:
            raise MigrationRunnerError("PARSER_DB_USER must differ from APP_DB_USER")
        # Required only by create_parser_user; validated whenever it is set.
        parser_arn = (
            environ.get(PARSER_DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE, "").strip()
            or None
        )
        if parser_arn is not None and not _SECRET_ARN.fullmatch(parser_arn):
            raise MigrationRunnerError(
                f"{PARSER_DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE} is not a "
                "Secrets Manager secret ARN"
            )
        return cls(
            master_arn,
            url_arn,
            host,
            port,
            database,
            app_user,
            parser_database_url_secret_arn=parser_arn,
            parser_user=parser_user,
        )


@dataclass(frozen=True)
class MasterCredentials:
    username: str
    password: str = field(repr=False)


class SecretsManagerClient(Protocol):
    def get_secret_value(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_secret_value(self, **kwargs: Any) -> Mapping[str, Any]: ...


def default_secrets_manager_client() -> SecretsManagerClient:
    """Default chain; standard mode, at most 3 attempts in total, 5 s timeouts."""

    import boto3
    from botocore.config import Config

    client: SecretsManagerClient = boto3.session.Session().client(
        "secretsmanager",
        config=Config(
            connect_timeout=5,
            read_timeout=5,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
    )
    return client


def _aws_failure(step: str, error: Exception) -> MigrationRunnerError:
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "")
        detail = (
            code
            if isinstance(code, str) and _SAFE_ERROR_CODE.fullmatch(code)
            else "ClientError"
        )
    else:
        detail = type(error).__name__
    return MigrationRunnerError(f"{step} failed ({detail})")


def read_master_credentials(
    client: SecretsManagerClient, settings: RunnerSettings
) -> MasterCredentials:
    try:
        response = client.get_secret_value(SecretId=settings.master_secret_arn)
    except Exception as error:
        raise _aws_failure("Reading the master-user secret", error) from None
    value = response.get("SecretString")
    if not isinstance(value, str) or not value.strip():
        raise MigrationRunnerError("The master-user secret has no string value")
    try:
        document = json.loads(value)
    except ValueError:
        raise MigrationRunnerError("The master-user secret is not JSON") from None
    if not isinstance(document, dict):
        raise MigrationRunnerError("The master-user secret is not a JSON object")
    username = document.get("username")
    password = document.get("password")
    if not isinstance(username, str) or not _IDENTIFIER.fullmatch(username):
        raise MigrationRunnerError("The master-user secret has no usable username")
    if not isinstance(password, str) or not password:
        raise MigrationRunnerError("The master-user secret has no password")
    return MasterCredentials(username=username, password=password)


def write_secret_url(
    client: SecretsManagerClient, secret_arn: str, label: str, url: str
) -> None:
    try:
        client.put_secret_value(SecretId=secret_arn, SecretString=url)
    except Exception as error:
        raise _aws_failure(f"Writing the {label} secret", error) from None


# --- URLs and SQL ---------------------------------------------------------------


def _postgresql_url(
    settings: RunnerSettings, username: str, password: str, *, connect_timeout: bool
) -> str:
    from sqlalchemy.engine import URL

    query = {"sslmode": "verify-full", "sslrootcert": RDS_CA_BUNDLE_PATH}
    if connect_timeout:
        query["connect_timeout"] = str(CONNECT_TIMEOUT_SECONDS)
    return URL.create(
        "postgresql+psycopg",
        username=username,
        password=password,
        host=settings.host,
        port=settings.port,
        database=settings.database,
        query=query,
    ).render_as_string(hide_password=False)


def application_database_url(settings: RunnerSettings, password: str) -> str:
    """The URL the API and general worker load from the database-url secret."""

    return _postgresql_url(settings, settings.app_user, password, connect_timeout=False)


def parser_database_url(settings: RunnerSettings, password: str) -> str:
    """The URL the parser function receives as DATABASE_URL (ADR-018 fallback)."""

    return _postgresql_url(
        settings, settings.parser_user, password, connect_timeout=False
    )


def scram_sha256_verifier(
    password: str,
    *,
    salt: bytes | None = None,
    iterations: int = SCRAM_ITERATIONS,
) -> str:
    """Return the PostgreSQL SCRAM-SHA-256 verifier for ``password`` (RFC 7677).

    PostgreSQL stores a pre-encrypted password as-is, so the plaintext never
    leaves this process. The generated passwords are ASCII, so no SASLprep
    normalization is needed.
    """

    if not password.isascii():
        raise MigrationRunnerError("Only ASCII application passwords are supported")
    salt = salt if salt is not None else secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    return (
        f"SCRAM-SHA-256${iterations}:{b64encode(salt).decode()}"
        f"${b64encode(stored_key).decode()}:{b64encode(server_key).decode()}"
    )


def grant_statements(
    *,
    role: str,
    database: str,
    master_role: str,
    tables: Sequence[str],
) -> list[sql.Composed]:
    """Compose the least-privilege grants for an existing role.

    No DELETE anywhere (the application never deletes rows). Tables in
    ``MUTABLE_TABLES`` get SELECT, INSERT, UPDATE; every other table, including
    one in neither list, gets SELECT, INSERT only (fail closed). Future tables
    created by the master role default to SELECT, INSERT; a table that needs
    UPDATE is added to ``MUTABLE_TABLES`` and the grants re-applied
    (``apply_grants``).
    """

    role_id = sql.Identifier(role)
    statements = [
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), role_id
        ),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role_id),
        sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(role_id),
    ]
    append_only_grant = sql.SQL("GRANT SELECT, INSERT ON TABLE {} TO {}")
    mutable_grant = sql.SQL("GRANT SELECT, INSERT, UPDATE ON TABLE {} TO {}")
    for table in sorted(tables):
        table_id = sql.Identifier("public", table)
        grant = mutable_grant if table in MUTABLE_TABLES else append_only_grant
        statements.append(
            sql.SQL("REVOKE ALL ON TABLE {} FROM {}").format(table_id, role_id)
        )
        statements.append(grant.format(table_id, role_id))
    statements.extend(
        [
            sql.SQL(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
            ).format(role_id),
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "REVOKE ALL ON TABLES FROM {}"
            ).format(sql.Identifier(master_role), role_id),
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT SELECT, INSERT ON TABLES TO {}"
            ).format(sql.Identifier(master_role), role_id),
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(sql.Identifier(master_role), role_id),
        ]
    )
    return statements


def app_user_statements(
    *,
    role: str,
    password_verifier: str,
    database: str,
    master_role: str,
    tables: Sequence[str],
    create: bool,
) -> list[sql.Composed]:
    """Compose the role statement and the grants; no value is interpolated as text."""

    return [
        _role_statement(role, password_verifier, create=create),
        *grant_statements(
            role=role, database=database, master_role=master_role, tables=tables
        ),
    ]


def _role_statement(role: str, password_verifier: str, *, create: bool) -> sql.Composed:
    role_id = sql.Identifier(role)
    if create:
        return sql.SQL(
            "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
            "NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(role_id, sql.Literal(password_verifier))
    return sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
        role_id, sql.Literal(password_verifier)
    )


def parser_user_statements(
    *,
    role: str,
    password_verifier: str,
    database: str,
    tables: Sequence[str],
    create: bool,
) -> list[sql.Composed]:
    """Compose the parser role and its grants (ADR-018 fallback).

    Every existing table first loses all privileges for the role, then only the
    tables in ``PARSER_TABLE_GRANTS`` get their exact privileges. No default
    privileges, no schema CREATE, no DELETE.
    """

    role_id = sql.Identifier(role)
    statements = [
        _role_statement(role, password_verifier, create=create),
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), role_id
        ),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role_id),
        sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(role_id),
    ]
    for table in sorted(tables):
        statements.append(
            sql.SQL("REVOKE ALL ON TABLE {} FROM {}").format(
                sql.Identifier("public", table), role_id
            )
        )
    for table in sorted(PARSER_TABLE_GRANTS):
        statements.append(
            PARSER_TABLE_GRANTS[table].format(sql.Identifier("public", table), role_id)
        )
    return statements


def append_only_count(tables: Sequence[str]) -> int:
    return sum(1 for table in tables if table not in MUTABLE_TABLES)


# --- Database -------------------------------------------------------------------


class MigrationDatabase(Protocol):
    def try_lock(self) -> bool: ...

    def unlock(self) -> None: ...

    def current_revision(self) -> str | None: ...

    def role_exists(self, role: str) -> bool: ...

    def public_tables(self) -> list[str]: ...

    def vector_version(self) -> str | None: ...

    def execute_in_transaction(self, statements: Sequence[sql.Composable]) -> None: ...

    def close(self) -> None: ...


class PsycopgMigrationDatabase:
    """Master-user session in autocommit mode; DDL goes through one transaction."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @classmethod
    def connect(
        cls, settings: RunnerSettings, credentials: MasterCredentials
    ) -> PsycopgMigrationDatabase:
        import psycopg

        try:
            connection = psycopg.connect(
                host=settings.host,
                port=settings.port,
                dbname=settings.database,
                user=credentials.username,
                password=credentials.password,
                sslmode="verify-full",
                sslrootcert=RDS_CA_BUNDLE_PATH,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                application_name="ai-qa-copilot-migrate",
                autocommit=True,
            )
        except Exception as error:
            raise MigrationRunnerError(
                f"Connecting to the database failed ({type(error).__name__})"
            ) from None
        return cls(connection)

    def _scalar(self, query: sql.Composable, params: Sequence[object] = ()) -> Any:
        row = self._connection.execute(query, params).fetchone()
        return None if row is None else row[0]

    def try_lock(self) -> bool:
        return bool(
            self._scalar(
                sql.SQL("SELECT pg_try_advisory_lock(%s)"), (ADVISORY_LOCK_KEY,)
            )
        )

    def unlock(self) -> None:
        self._scalar(sql.SQL("SELECT pg_advisory_unlock(%s)"), (ADVISORY_LOCK_KEY,))

    def current_revision(self) -> str | None:
        if (
            self._scalar(sql.SQL("SELECT to_regclass('public.alembic_version')"))
            is None
        ):
            return None
        rows = self._connection.execute(
            sql.SQL("SELECT version_num FROM public.alembic_version")
        ).fetchall()
        if len(rows) > 1:
            raise MigrationRunnerError("alembic_version holds more than one revision")
        return None if not rows else str(rows[0][0])

    def role_exists(self, role: str) -> bool:
        return (
            self._scalar(sql.SQL("SELECT 1 FROM pg_roles WHERE rolname = %s"), (role,))
            is not None
        )

    def public_tables(self) -> list[str]:
        rows = self._connection.execute(
            sql.SQL(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"
            )
        ).fetchall()
        return [str(row[0]) for row in rows if str(row[0]) not in _IGNORED_TABLES]

    def vector_version(self) -> str | None:
        version = self._scalar(
            sql.SQL("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        return None if version is None else str(version)

    def execute_in_transaction(self, statements: Sequence[sql.Composable]) -> None:
        with self._connection.transaction():
            for statement in statements:
                self._connection.execute(statement)

    def close(self) -> None:
        self._connection.close()


# --- Alembic --------------------------------------------------------------------


def alembic_config_path() -> Path:
    """``migrations/alembic.ini`` in the image; ``apps/api/alembic.ini`` in the repo.

    The image keeps the scripts under ``migrations/`` because a top-level
    ``alembic/`` directory in the task root would collide with the installed
    ``alembic`` package.
    """

    task_root = os.environ.get("LAMBDA_TASK_ROOT", "").strip()
    if task_root:
        return Path(task_root) / "migrations" / "alembic.ini"
    return Path(__file__).resolve().parents[2] / "alembic.ini"


def head_revision(config_path: Path | None = None) -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(
        Config(str(config_path or alembic_config_path()))
    ).get_current_head()
    if head is None:
        raise MigrationRunnerError("The packaged migrations have no single head")
    return head


def alembic_upgrade_to_head(database_url: str, config_path: Path | None = None) -> None:
    """Run ``alembic upgrade head`` through the unchanged ``env.py``.

    ``env.py`` reads ``DATABASE_URL``; it is set for this call only and removed
    afterwards. A ``DATABASE_URL`` already in the environment is refused.
    """

    from alembic import command
    from alembic.config import Config

    with _environment_lock:
        if os.environ.get("DATABASE_URL"):
            raise MigrationRunnerError("DATABASE_URL must not be set for the runner")
        os.environ["DATABASE_URL"] = database_url
        try:
            command.upgrade(Config(str(config_path or alembic_config_path())), "head")
        finally:
            os.environ.pop("DATABASE_URL", None)


# --- Runner ---------------------------------------------------------------------


Connector = Callable[[RunnerSettings, MasterCredentials], MigrationDatabase]


@dataclass
class MigrationRunner:
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    client_factory: Callable[[], SecretsManagerClient] = default_secrets_manager_client
    connect: Connector = PsycopgMigrationDatabase.connect
    upgrade: Callable[[str], None] = alembic_upgrade_to_head
    head: Callable[[], str] = head_revision
    generate_password: Callable[[], str] = lambda: secrets.token_urlsafe(
        APP_PASSWORD_BYTES
    )

    def __call__(self, event: object) -> dict[str, object]:
        action, rotate = _parse_event(event)
        settings = RunnerSettings.from_environment(self.environ)
        try:
            client = self.client_factory()
        except Exception as error:
            raise MigrationRunnerError(
                f"Creating the Secrets Manager client failed ({type(error).__name__})"
            ) from None
        credentials = read_master_credentials(client, settings)
        _logger.info("migrate.action action=%s", action)
        if action == "status":
            return self._status(settings, credentials)
        if action == "migrate":
            return self._migrate(settings, credentials)
        if action == "apply_grants":
            return self._apply_grants(settings, credentials)
        if action == "create_parser_user":
            return self._create_parser_user(
                settings, credentials, client, rotate=rotate
            )
        return self._create_app_user(settings, credentials, client, rotate=rotate)

    def _head(self) -> str:
        try:
            return self.head()
        except MigrationRunnerError:
            raise
        except Exception as error:
            raise MigrationRunnerError(
                f"Reading the migration head failed ({type(error).__name__})"
            ) from None

    def _status(
        self, settings: RunnerSettings, credentials: MasterCredentials
    ) -> dict[str, object]:
        head = self._head()
        database = self.connect(settings, credentials)
        try:
            revision = _read_revision(database)
            vector = _read_vector_version(database)
        finally:
            database.close()
        return {
            "action": "status",
            "revision": revision,
            "head": head,
            "at_head": revision == head,
            "pgvector_version": vector,
        }

    def _migrate(
        self, settings: RunnerSettings, credentials: MasterCredentials
    ) -> dict[str, object]:
        head = self._head()
        database = self.connect(settings, credentials)
        try:
            _acquire_lock(database)
            try:
                before = _read_revision(database)
                url = _postgresql_url(
                    settings,
                    credentials.username,
                    credentials.password,
                    connect_timeout=True,
                )
                try:
                    self.upgrade(url)
                except Exception as error:
                    after = _revision_or_unknown(database)
                    raise MigrationRunnerError(
                        f"Upgrade failed ({type(error).__name__}); revision before "
                        f"{before or 'none'}, after {after}"
                    ) from None
                after_upgrade = _read_revision(database)
                vector = _read_vector_version(database)
            finally:
                _release_lock(database)
        finally:
            database.close()
        _logger.info("migrate.done revision=%s", after_upgrade)
        return {
            "action": "migrate",
            "revision_before": before,
            "revision": after_upgrade,
            "head": head,
            "at_head": after_upgrade == head,
            "upgraded": after_upgrade != before,
            "pgvector_version": vector,
        }

    def _apply_grants(
        self, settings: RunnerSettings, credentials: MasterCredentials
    ) -> dict[str, object]:
        """Re-apply the grants for the existing role: no password, no secret."""

        if settings.app_user == credentials.username:
            raise MigrationRunnerError("APP_DB_USER must differ from the master user")
        database = self.connect(settings, credentials)
        try:
            _acquire_lock(database)
            try:
                if not _database_step(
                    "Checking the application role",
                    database.role_exists,
                    settings.app_user,
                ):
                    raise MigrationRunnerError(
                        "The application role does not exist; run create_app_user first"
                    )
                tables = _database_step("Listing tables", database.public_tables)
                _database_step(
                    "Applying the grants",
                    database.execute_in_transaction,
                    grant_statements(
                        role=settings.app_user,
                        database=settings.database,
                        master_role=credentials.username,
                        tables=tables,
                    ),
                )
            finally:
                _release_lock(database)
        finally:
            database.close()
        _logger.info("migrate.grants tables=%d", len(tables))
        return {
            "action": "apply_grants",
            "tables_granted": len(tables),
            "append_only_tables": append_only_count(tables),
        }

    def _create_login_role(
        self,
        settings: RunnerSettings,
        credentials: MasterCredentials,
        client: SecretsManagerClient,
        *,
        rotate: bool,
        role: str,
        kind: str,
        secret_arn: str,
        secret_label: str,
        statements_for: Callable[[str, list[str], bool], list[sql.Composed]],
        url_for: Callable[[str], str],
        required_tables: frozenset[str] = frozenset(),
    ) -> tuple[bool, list[str]]:
        """Create or re-password one login role, then write its URL secret.

        Role and grants commit first, in one transaction; the secret is written
        last. If the secret write fails, the database already has the new
        password and the secret does not: the error says to rerun with rotate.
        """

        if role == credentials.username:
            raise MigrationRunnerError(
                f"The {kind} role name must differ from the master user"
            )
        database = self.connect(settings, credentials)
        try:
            _acquire_lock(database)
            try:
                if _read_revision(database) is None:
                    raise MigrationRunnerError(
                        "The database is not migrated; run migrate first"
                    )
                exists = _database_step(
                    f"Checking the {kind} role", database.role_exists, role
                )
                if exists and not rotate:
                    raise MigrationRunnerError(
                        f"The {kind} role already exists; send rotate=true to reset its password"
                    )
                if rotate and not exists:
                    raise MigrationRunnerError(
                        f"rotate=true was sent but the {kind} role does not exist"
                    )
                tables = _database_step("Listing tables", database.public_tables)
                if not required_tables <= set(tables):
                    raise MigrationRunnerError(
                        f"The database lacks a table the {kind} role needs; run migrate first"
                    )
                password = self.generate_password()
                statements = statements_for(
                    scram_sha256_verifier(password), tables, not exists
                )
                _database_step(
                    f"Creating the {kind} role"
                    if not exists
                    else f"Rotating the {kind} password",
                    database.execute_in_transaction,
                    statements,
                )
                try:
                    write_secret_url(
                        client, secret_arn, secret_label, url_for(password)
                    )
                except MigrationRunnerError as error:
                    raise MigrationRunnerError(
                        f"{error}; the role was {'rotated' if exists else 'created'} but the "
                        "secret was not written, so rerun with rotate=true"
                    ) from None
                finally:
                    del password
            finally:
                _release_lock(database)
        finally:
            database.close()
        _logger.info("migrate.%s_role created=%s rotated=%s", kind, not exists, exists)
        return exists, tables

    def _create_app_user(
        self,
        settings: RunnerSettings,
        credentials: MasterCredentials,
        client: SecretsManagerClient,
        *,
        rotate: bool,
    ) -> dict[str, object]:
        exists, tables = self._create_login_role(
            settings,
            credentials,
            client,
            rotate=rotate,
            role=settings.app_user,
            kind="application",
            secret_arn=settings.database_url_secret_arn,
            secret_label="database-url",
            statements_for=lambda verifier, tables, create: app_user_statements(
                role=settings.app_user,
                password_verifier=verifier,
                database=settings.database,
                master_role=credentials.username,
                tables=tables,
                create=create,
            ),
            url_for=lambda password: application_database_url(settings, password),
        )
        return {
            "action": "create_app_user",
            "role_created": not exists,
            "password_rotated": exists,
            "secret_written": True,
            "tables_granted": len(tables),
            "append_only_tables": append_only_count(tables),
        }

    def _create_parser_user(
        self,
        settings: RunnerSettings,
        credentials: MasterCredentials,
        client: SecretsManagerClient,
        *,
        rotate: bool,
    ) -> dict[str, object]:
        if settings.parser_database_url_secret_arn is None:
            raise MigrationRunnerError(
                f"{PARSER_DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE} must be configured"
            )
        exists, _ = self._create_login_role(
            settings,
            credentials,
            client,
            rotate=rotate,
            role=settings.parser_user,
            kind="parser",
            secret_arn=settings.parser_database_url_secret_arn,
            secret_label="parser-database-url",
            statements_for=lambda verifier, tables, create: parser_user_statements(
                role=settings.parser_user,
                password_verifier=verifier,
                database=settings.database,
                tables=tables,
                create=create,
            ),
            url_for=lambda password: parser_database_url(settings, password),
            required_tables=frozenset(PARSER_TABLE_GRANTS),
        )
        read_only = sum(
            1
            for grant in PARSER_TABLE_GRANTS.values()
            if grant.as_string().startswith("GRANT SELECT ON")
        )
        return {
            "action": "create_parser_user",
            "role_created": not exists,
            "password_rotated": exists,
            "secret_written": True,
            "tables_granted": len(PARSER_TABLE_GRANTS),
            "read_only_tables": read_only,
        }


def _parse_event(event: object) -> tuple[str, bool]:
    if event is None:
        event = {}
    if not isinstance(event, Mapping):
        raise MigrationRunnerError("The event must be a JSON object")
    unknown = set(event) - {"action", "rotate"}
    if unknown:
        raise MigrationRunnerError("The event has unknown fields")
    action = event.get("action", "migrate")
    if not isinstance(action, str) or action not in ACTIONS:
        raise MigrationRunnerError("Unknown action")
    rotate = event.get("rotate", False)
    if not isinstance(rotate, bool):
        raise MigrationRunnerError("rotate must be true or false")
    if rotate and action not in {"create_app_user", "create_parser_user"}:
        raise MigrationRunnerError(
            "rotate applies to create_app_user and create_parser_user only"
        )
    return action, rotate


def _database_step(step: str, operation: Callable[..., Any], *args: Any) -> Any:
    try:
        return operation(*args)
    except MigrationRunnerError:
        raise
    except Exception as error:
        raise MigrationRunnerError(f"{step} failed ({type(error).__name__})") from None


def _read_revision(database: MigrationDatabase) -> str | None:
    result: str | None = _database_step(
        "Reading the revision", database.current_revision
    )
    return result


def _read_vector_version(database: MigrationDatabase) -> str | None:
    result: str | None = _database_step(
        "Reading the pgvector version", database.vector_version
    )
    return result


def _revision_or_unknown(database: MigrationDatabase) -> str:
    try:
        return database.current_revision() or "none"
    except Exception:
        return "unknown"


def _acquire_lock(database: MigrationDatabase) -> None:
    if not _database_step("Taking the migration lock", database.try_lock):
        raise MigrationRunnerError("Another runner holds the migration lock")


def _release_lock(database: MigrationDatabase) -> None:
    try:
        database.unlock()
    except Exception:
        # The session-level lock ends with the connection, which is closed next.
        _logger.warning("migrate.unlock_failed")


_runner = MigrationRunner()


def handler(event: Any, context: Any) -> dict[str, object]:
    del context
    return _runner(event)
