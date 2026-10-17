"""Migration runner Lambda (INFRA-012): fakes and Stubber only, no network."""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping, Sequence
import json
import logging
from pathlib import Path
import re
import traceback
from typing import Any

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.stub import Stubber
from psycopg import sql
import pytest
from sqlalchemy.engine import make_url

from ai_qa_copilot_api import lambda_migrate
from ai_qa_copilot_api.lambda_migrate import (
    APPEND_ONLY_TABLES,
    MUTABLE_TABLES,
    MasterCredentials,
    MigrationRunner,
    MigrationRunnerError,
    RunnerSettings,
    app_user_statements,
    application_database_url,
    head_revision,
    scram_sha256_verifier,
)


ROOT = Path(__file__).resolve().parents[3]
MASTER_ARN = (
    "arn:aws:secretsmanager:us-east-1:000000000000:secret:rds!db-ArnSuffixMaster"
)
URL_ARN = (
    "arn:aws:secretsmanager:us-east-1:000000000000:secret:"
    "ai-qa-copilot-production/database-url-ArnSuffixUrl"
)
MASTER_PASSWORD = "unit-test-master-sentinel"
APP_PASSWORD = "unit-test-app-password-sentinel-0123456789"
HOST = "database.invalid"
SENSITIVE = (MASTER_PASSWORD, APP_PASSWORD, "ArnSuffixMaster", "ArnSuffixUrl", HOST)
HEAD = "0021_analysis_run_provider"
ENVIRONMENT = {
    "APP_ENV": "production",
    "MASTER_SECRET_ARN": MASTER_ARN,
    "DATABASE_URL_SECRET_ARN": URL_ARN,
    "DB_HOST": HOST,
    "DB_PORT": "5432",
    "DB_NAME": "ai_qa_copilot",
    "APP_DB_USER": "ai_qa_copilot_app",
}
TABLES = sorted(MUTABLE_TABLES | APPEND_ONLY_TABLES)


class FakeSecrets:
    def __init__(self, master: Any = None, put_error: Exception | None = None) -> None:
        self.master: Any = (
            {
                "SecretString": json.dumps(
                    {"username": "copilot_master", "password": MASTER_PASSWORD}
                )
            }
            if master is None
            else master
        )
        self.put_error = put_error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_secret_value(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("get", kwargs))
        if isinstance(self.master, Exception):
            raise self.master
        result: Mapping[str, Any] = self.master
        return result

    def put_secret_value(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("put", kwargs))
        if self.put_error is not None:
            raise self.put_error
        return {"VersionId": "v1"}


class FakeDatabase:
    def __init__(
        self,
        *,
        revision: str | None = HEAD,
        locked: bool = False,
        role: bool = False,
        tables: Sequence[str] = TABLES,
        execute_error: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.revision = revision
        self.locked = locked
        self.role = role
        self.tables = list(tables)
        self.execute_error = execute_error
        self.events = events if events is not None else []
        self.statements: list[sql.Composable] = []

    def try_lock(self) -> bool:
        self.events.append("lock")
        return not self.locked

    def unlock(self) -> None:
        self.events.append("unlock")

    def current_revision(self) -> str | None:
        return self.revision

    def role_exists(self, role: str) -> bool:
        return self.role

    def public_tables(self) -> list[str]:
        return list(self.tables)

    def execute_in_transaction(self, statements: Sequence[sql.Composable]) -> None:
        self.events.append("execute")
        if self.execute_error is not None:
            raise self.execute_error
        self.statements = list(statements)
        self.role = True

    def close(self) -> None:
        self.events.append("close")


def runner(
    database: FakeDatabase,
    secrets: FakeSecrets | None = None,
    *,
    upgrade: Any = None,
    environ: Mapping[str, str] = ENVIRONMENT,
) -> tuple[MigrationRunner, FakeSecrets]:
    client = secrets or FakeSecrets()

    def default_upgrade(url: str) -> None:
        database.revision = HEAD

    return (
        MigrationRunner(
            environ=environ,
            client_factory=lambda: client,
            connect=lambda settings, credentials: database,
            upgrade=upgrade or default_upgrade,
            head=lambda: HEAD,
            generate_password=lambda: APP_PASSWORD,
        ),
        client,
    )


def failure(run: MigrationRunner, event: object) -> MigrationRunnerError:
    with pytest.raises(MigrationRunnerError) as raised:
        run(event)
    error = raised.value
    rendered = "".join(traceback.format_exception(error))
    for sensitive in SENSITIVE:
        assert sensitive not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__
    return error


def assert_clean(value: object) -> None:
    text = json.dumps(value)
    for sensitive in SENSITIVE:
        assert sensitive not in text


# --- Event handling -------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "message"),
    [
        ({"action": "drop_everything"}, "Unknown action"),
        ({"action": 7}, "Unknown action"),
        ([], "The event must be a JSON object"),
        ({"action": "migrate", "extra": 1}, "The event has unknown fields"),
        (
            {"action": "migrate", "rotate": True},
            "rotate applies to create_app_user only",
        ),
        (
            {"action": "create_app_user", "rotate": "yes"},
            "rotate must be true or false",
        ),
    ],
)
def test_invalid_events_fail_closed_before_any_call(
    event: object, message: str
) -> None:
    database = FakeDatabase()
    run, client = runner(database)

    assert str(failure(run, event)) == message
    assert client.calls == []
    assert database.events == []


def test_an_empty_event_means_migrate() -> None:
    database = FakeDatabase(revision=None)
    run, _ = runner(database)

    assert run({})["action"] == "migrate"
    assert run(None)["action"] == "migrate"


# --- Settings -------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["MASTER_SECRET_ARN", "DATABASE_URL_SECRET_ARN", "DB_HOST", "DB_PORT", "DB_NAME"],
)
def test_missing_environment_variables_fail_closed(name: str) -> None:
    run, client = runner(FakeDatabase(), environ={**ENVIRONMENT, name: ""})

    assert str(failure(run, {"action": "status"})) == f"{name} must be configured"
    assert client.calls == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"MASTER_SECRET_ARN": "rds!db-ArnSuffixMaster"},
            "MASTER_SECRET_ARN is not a Secrets Manager secret ARN",
        ),
        ({"DB_HOST": "database.invalid/x"}, "DB_HOST is not a host name"),
        ({"DB_PORT": "five"}, "DB_PORT must be an integer"),
        ({"DB_PORT": "70000"}, "DB_PORT is out of range"),
        ({"DB_NAME": "ai-qa"}, "DB_NAME is not a lower-case SQL identifier"),
        (
            {"APP_DB_USER": 'app"; DROP ROLE x'},
            "APP_DB_USER is not a lower-case SQL identifier",
        ),
    ],
)
def test_invalid_settings_fail_closed(overrides: dict[str, str], message: str) -> None:
    run, client = runner(FakeDatabase(), environ={**ENVIRONMENT, **overrides})

    assert str(failure(run, {"action": "status"})) == message
    assert client.calls == []


def test_the_application_user_defaults_to_ai_qa_copilot_app() -> None:
    settings = RunnerSettings.from_environment({**ENVIRONMENT, "APP_DB_USER": ""})

    assert settings.app_user == "ai_qa_copilot_app"


# --- Master secret --------------------------------------------------------------


@pytest.mark.parametrize(
    ("master", "message"),
    [
        (
            ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": MASTER_ARN}},
                "GetSecretValue",
            ),
            "Reading the master-user secret failed (ResourceNotFoundException)",
        ),
        (
            ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": MASTER_ARN}},
                "GetSecretValue",
            ),
            "Reading the master-user secret failed (AccessDeniedException)",
        ),
        (
            EndpointConnectionError(endpoint_url=f"https://{HOST}"),
            "Reading the master-user secret failed (EndpointConnectionError)",
        ),
        ({}, "The master-user secret has no string value"),
        ({"SecretString": "  "}, "The master-user secret has no string value"),
        (
            {"SecretString": f"not json {MASTER_PASSWORD}"},
            "The master-user secret is not JSON",
        ),
        (
            {"SecretString": json.dumps([MASTER_PASSWORD])},
            "The master-user secret is not a JSON object",
        ),
        (
            {"SecretString": json.dumps({"password": MASTER_PASSWORD})},
            "The master-user secret has no usable username",
        ),
        (
            {"SecretString": json.dumps({"username": "copilot_master"})},
            "The master-user secret has no password",
        ),
        (
            {
                "SecretString": json.dumps(
                    {"username": "copilot_master", "password": ""}
                )
            },
            "The master-user secret has no password",
        ),
    ],
)
def test_master_secret_failures_fail_closed(master: Any, message: str) -> None:
    database = FakeDatabase()
    run, _ = runner(database, FakeSecrets(master=master))

    assert str(failure(run, {"action": "status"})) == message
    assert database.events == []


def test_master_credentials_never_show_the_password_in_repr() -> None:
    assert MASTER_PASSWORD not in repr(
        MasterCredentials("copilot_master", MASTER_PASSWORD)
    )


@pytest.fixture
def stubbed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[Any, Stubber]]:
    for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "missing-aws-config"))
    monkeypatch.setenv(
        "AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "missing-credentials")
    )
    client = boto3.session.Session().client(
        "secretsmanager",
        region_name="us-east-1",
        config=Config(signature_version=UNSIGNED),
    )
    with Stubber(client) as stubber:
        yield client, stubber


def test_botocore_stubbed_access_denied_on_the_master_secret(
    stubbed: tuple[Any, Stubber],
) -> None:
    client, stubber = stubbed
    stubber.add_client_error(
        "get_secret_value",
        service_error_code="AccessDeniedException",
        service_message=f"not allowed on {MASTER_ARN}",
        http_status_code=400,
        expected_params={"SecretId": MASTER_ARN},
    )
    run = MigrationRunner(
        environ=ENVIRONMENT,
        client_factory=lambda: client,
        connect=lambda settings, credentials: FakeDatabase(),
        head=lambda: HEAD,
    )

    error = failure(run, {"action": "status"})

    assert str(error) == "Reading the master-user secret failed (AccessDeniedException)"
    stubber.assert_no_pending_responses()


def test_default_client_uses_three_total_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "missing-aws-config"))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    client: Any = lambda_migrate.default_secrets_manager_client()

    assert client.meta.config.retries == {"mode": "standard", "total_max_attempts": 3}
    assert (
        client.meta.config.connect_timeout == 5 and client.meta.config.read_timeout == 5
    )


# --- status and migrate ---------------------------------------------------------


def test_status_reads_the_revision_without_locking() -> None:
    database = FakeDatabase(revision="0020_review_packet_binding")
    run, _ = runner(database)

    result = run({"action": "status"})

    assert result == {
        "action": "status",
        "revision": "0020_review_packet_binding",
        "head": HEAD,
        "at_head": False,
    }
    assert database.events == ["close"]
    assert_clean(result)


def test_migrate_upgrades_under_the_lock_and_reads_the_revision_back() -> None:
    database = FakeDatabase(revision=None)
    urls: list[str] = []

    def upgrade(url: str) -> None:
        urls.append(url)
        database.revision = HEAD

    run, _ = runner(database, upgrade=upgrade)

    result = run({"action": "migrate"})

    assert result == {
        "action": "migrate",
        "revision_before": None,
        "revision": HEAD,
        "head": HEAD,
        "at_head": True,
        "upgraded": True,
    }
    assert database.events == ["lock", "unlock", "close"]
    url = make_url(urls[0])
    assert url.drivername == "postgresql+psycopg"
    assert url.password == MASTER_PASSWORD
    assert url.query == {"sslmode": "require", "connect_timeout": "10"}
    assert_clean(result)


def test_a_failed_upgrade_reports_the_unchanged_revision_and_releases_the_lock(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    database = FakeDatabase(revision="0020_review_packet_binding")

    def upgrade(url: str) -> None:
        # Driver errors can echo the URL; the runner must not.
        raise RuntimeError(f"connection to {url} failed")

    run, _ = runner(database, upgrade=upgrade)

    error = failure(run, {"action": "migrate"})

    assert str(error) == (
        "Upgrade failed (RuntimeError); revision before 0020_review_packet_binding, "
        "after 0020_review_packet_binding"
    )
    assert database.events == ["lock", "unlock", "close"]
    for sensitive in SENSITIVE:
        assert sensitive not in caplog.text


def test_a_held_advisory_lock_stops_the_run_before_upgrading() -> None:
    database = FakeDatabase(locked=True)
    upgrades: list[str] = []
    run, _ = runner(database, upgrade=upgrades.append)

    error = failure(run, {"action": "migrate"})

    assert str(error) == "Another runner holds the migration lock"
    assert upgrades == []
    assert database.events == ["lock", "close"]


def test_head_revision_matches_the_last_migration() -> None:
    assert head_revision() == HEAD


# --- create_app_user ------------------------------------------------------------


def statement_texts(statements: Sequence[sql.Composable]) -> list[str]:
    return [statement.as_string() for statement in statements]


def test_create_app_user_creates_the_role_then_writes_the_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    events: list[str] = []
    database = FakeDatabase(events=events)
    secrets_client = FakeSecrets()
    original_put = secrets_client.put_secret_value

    def put(**kwargs: Any) -> Mapping[str, Any]:
        events.append("put")
        return original_put(**kwargs)

    secrets_client.put_secret_value = put  # type: ignore[method-assign]
    run, _ = runner(database, secrets_client)

    result = run({"action": "create_app_user"})

    assert result == {
        "action": "create_app_user",
        "role_created": True,
        "password_rotated": False,
        "secret_written": True,
        "tables_granted": len(TABLES),
        "append_only_tables": len(APPEND_ONLY_TABLES),
    }
    assert events == ["lock", "execute", "put", "unlock", "close"]
    texts = statement_texts(database.statements)
    assert texts[0].startswith('CREATE ROLE "ai_qa_copilot_app" WITH LOGIN NOSUPERUSER')
    put_calls = [kwargs for kind, kwargs in secrets_client.calls if kind == "put"]
    assert put_calls == [
        {
            "SecretId": URL_ARN,
            "SecretString": (
                f"postgresql+psycopg://ai_qa_copilot_app:{APP_PASSWORD}@{HOST}:5432/"
                "ai_qa_copilot?sslmode=require"
            ),
        }
    ]
    assert_clean(result)
    for text in texts:
        assert APP_PASSWORD not in text
    for sensitive in SENSITIVE:
        assert sensitive not in caplog.text


def test_an_existing_role_without_rotate_fails_closed_without_changes() -> None:
    database = FakeDatabase(role=True)
    run, client = runner(database)

    error = failure(run, {"action": "create_app_user"})

    assert str(error) == (
        "The application role already exists; send rotate=true to reset its password"
    )
    assert database.statements == []
    assert [kind for kind, _ in client.calls] == ["get"]
    assert database.events == ["lock", "unlock", "close"]


def test_rotate_resets_the_password_and_rewrites_the_secret() -> None:
    database = FakeDatabase(role=True)
    run, client = runner(database)

    result = run({"action": "create_app_user", "rotate": True})

    assert result["role_created"] is False and result["password_rotated"] is True
    assert statement_texts(database.statements)[0].startswith(
        'ALTER ROLE "ai_qa_copilot_app" WITH PASSWORD \'SCRAM-SHA-256$4096:'
    )
    assert [kind for kind, _ in client.calls] == ["get", "put"]


def test_rotate_without_an_existing_role_fails_closed() -> None:
    database = FakeDatabase(role=False)
    run, client = runner(database)

    error = failure(run, {"action": "create_app_user", "rotate": True})

    assert str(error) == "rotate=true was sent but the application role does not exist"
    assert database.statements == []


def test_create_app_user_requires_a_migrated_database() -> None:
    database = FakeDatabase(revision=None)
    run, _ = runner(database)

    assert str(failure(run, {"action": "create_app_user"})) == (
        "The database is not migrated; run migrate first"
    )


def test_create_app_user_refuses_the_master_user_name() -> None:
    run, _ = runner(
        FakeDatabase(), environ={**ENVIRONMENT, "APP_DB_USER": "copilot_master"}
    )

    assert str(failure(run, {"action": "create_app_user"})) == (
        "APP_DB_USER must differ from the master user"
    )


def test_a_failed_secret_write_comes_after_the_role_change_and_says_how_to_recover() -> (
    None
):
    put_error = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": f"{URL_ARN} {APP_PASSWORD}",
            }
        },
        "PutSecretValue",
    )
    database = FakeDatabase()
    run, client = runner(database, FakeSecrets(put_error=put_error))

    error = failure(run, {"action": "create_app_user"})

    assert str(error) == (
        "Writing the database-url secret failed (AccessDeniedException); the role was "
        "created but the secret was not written, so rerun with rotate=true"
    )
    assert database.events == ["lock", "execute", "unlock", "close"]
    assert [kind for kind, _ in client.calls] == ["get", "put"]


def test_a_failed_role_change_never_writes_the_secret() -> None:
    database = FakeDatabase(execute_error=RuntimeError(f"bad statement {APP_PASSWORD}"))
    run, client = runner(database)

    error = failure(run, {"action": "create_app_user"})

    assert str(error) == "Creating the application role failed (RuntimeError)"
    assert [kind for kind, _ in client.calls] == ["get"]


# --- SQL composition and grants -------------------------------------------------


def test_grants_follow_the_append_only_split() -> None:
    texts = statement_texts(
        app_user_statements(
            role="ai_qa_copilot_app",
            password_verifier="SCRAM-SHA-256$4096:c2FsdA==$a2V5:a2V5",
            database="ai_qa_copilot",
            master_role="copilot_master",
            tables=["parser_jobs", "analysis_runs"],
            create=True,
        )
    )

    assert texts[1:] == [
        'GRANT CONNECT ON DATABASE "ai_qa_copilot" TO "ai_qa_copilot_app"',
        'GRANT USAGE ON SCHEMA public TO "ai_qa_copilot_app"',
        'REVOKE CREATE ON SCHEMA public FROM "ai_qa_copilot_app"',
        'REVOKE ALL ON TABLE "public"."analysis_runs" FROM "ai_qa_copilot_app"',
        'GRANT SELECT, INSERT ON TABLE "public"."analysis_runs" TO "ai_qa_copilot_app"',
        'REVOKE ALL ON TABLE "public"."parser_jobs" FROM "ai_qa_copilot_app"',
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "public"."parser_jobs" TO "ai_qa_copilot_app"',
        'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "ai_qa_copilot_app"',
        'ALTER DEFAULT PRIVILEGES FOR ROLE "copilot_master" IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "ai_qa_copilot_app"',
        'ALTER DEFAULT PRIVILEGES FOR ROLE "copilot_master" IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "ai_qa_copilot_app"',
    ]
    assert texts[0] == (
        'CREATE ROLE "ai_qa_copilot_app" WITH LOGIN NOSUPERUSER NOCREATEDB '
        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD "
        "'SCRAM-SHA-256$4096:c2FsdA==$a2V5:a2V5'"
    )
    # No statement grants schema CREATE, extension or role rights.
    assert not any(
        re.search(
            r"\bGRANT\b.*\b(CREATE|TRIGGER|TRUNCATE|REFERENCES|ALL PRIVILEGES)\b", t
        )
        for t in texts
    )


def test_every_migrated_table_is_classified() -> None:
    created: set[str] = set()
    for path in (ROOT / "apps/api/alembic/versions").glob("0*.py"):
        created.update(
            re.findall(
                r'op\.create_table\(\s*"([a-z_]+)"', path.read_text(encoding="utf-8")
            )
        )

    assert created == MUTABLE_TABLES | APPEND_ONLY_TABLES
    assert not MUTABLE_TABLES & APPEND_ONLY_TABLES


def test_sql_is_composed_without_string_interpolation() -> None:
    tree = ast.parse(Path(lambda_migrate.__file__).read_text(encoding="utf-8"))
    sql_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "SQL"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sql"
    ]

    assert sql_calls
    for call in sql_calls:
        assert len(call.args) == 1
        argument = call.args[0]
        assert isinstance(argument, ast.Constant) and isinstance(argument.value, str), (
            ast.unparse(call)
        )
        assert "%(" not in argument.value


def test_scram_verifier_has_the_postgresql_format_and_never_contains_the_password() -> (
    None
):
    verifier = scram_sha256_verifier(APP_PASSWORD, salt=b"0123456789abcdef")

    assert re.fullmatch(
        r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/]{22}==\$[A-Za-z0-9+/]{43}=:[A-Za-z0-9+/]{43}=",
        verifier,
    )
    assert APP_PASSWORD not in verifier
    assert verifier != scram_sha256_verifier(APP_PASSWORD)  # random salt


def test_scram_verifier_refuses_non_ascii_passwords() -> None:
    with pytest.raises(MigrationRunnerError):
        scram_sha256_verifier("pässword")


def test_application_url_is_accepted_by_the_secrets_bootstrap() -> None:
    from ai_qa_copilot_api.secrets_bootstrap import load_secrets_into_environment

    settings = RunnerSettings.from_environment(ENVIRONMENT)
    url = application_database_url(settings, APP_PASSWORD)
    environ = {
        "APP_ENV": "production",
        "DATABASE_URL_SECRET_ARN": URL_ARN,
        "OPENAI_API_KEY_SECRET_ARN": URL_ARN.replace("database-url", "openai-api-key"),
    }

    class Client:
        def get_secret_value(self, **kwargs: Any) -> Mapping[str, Any]:
            value = url if kwargs["SecretId"] == URL_ARN else "unit-test-model-key"
            return {"SecretString": value}

    assert load_secrets_into_environment(environ, client_factory=Client)
    assert environ["DATABASE_URL"] == url
    assert make_url(url).query == {"sslmode": "require"}
