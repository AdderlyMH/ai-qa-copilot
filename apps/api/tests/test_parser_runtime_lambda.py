"""ADR-018 amendment to ADR-009: the Lambda parser credential relaxation."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from ai_qa_copilot_api import parser_worker
from ai_qa_copilot_api.parser_worker import (
    FORBIDDEN_CREDENTIAL_ENVIRONMENT_VARIABLES,
    PARSER_WORKER_ROLE,
    ParserWorkerConfigurationError,
    ParserWorkerRuntime,
    lambda_parser_credentials_allowed,
    verify_runtime,
)


# Fake, credential-shaped values; each carries a marker that must never
# appear in an error message.
ACCESS_KEY_ID = "ASIAFAKEMARKERKEY001"
SECRET = "fake-secret-marker-002"
TOKEN = "fake-session-token-marker-003"
MARKERS = ("MARKERKEY001", "secret-marker-002", "token-marker-003", "model-marker-004")


def lambda_parser_environment() -> dict[str, str]:
    """What the Lambda runtime plus the Terraform parser settings provide."""

    return {
        "AWS_LAMBDA_FUNCTION_NAME": "ai-qa-copilot-production-parser",
        "AWS_ACCESS_KEY_ID": ACCESS_KEY_ID,
        "AWS_SECRET_ACCESS_KEY": SECRET,
        "AWS_SESSION_TOKEN": TOKEN,
        "AWS_REGION": "us-east-1",
        "PARSER_WORKER_ROLE": PARSER_WORKER_ROLE,
        "PARSER_WORKER_NETWORK": "none",
        "APP_ENV": "production",
        "DATA_BUCKET_NAME": "example-data-bucket",
    }


def assert_rejected(environment: dict[str, str]) -> None:
    with pytest.raises(ParserWorkerConfigurationError) as raised:
        ParserWorkerRuntime.from_environment(environment, uid=993)
    message = str(raised.value)
    for marker in MARKERS:
        assert marker not in message
    assert raised.value.__cause__ is None


# --- Accepted -----------------------------------------------------------------


def test_lambda_parser_environment_is_accepted() -> None:
    runtime = ParserWorkerRuntime.from_environment(lambda_parser_environment(), uid=993)

    assert runtime.role == PARSER_WORKER_ROLE
    assert runtime.network == "none"
    assert lambda_parser_credentials_allowed(lambda_parser_environment())


def test_lambda_parser_environment_is_accepted_through_verify_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_worker, "current_uid", lambda: 993)

    runtime = verify_runtime(lambda_parser_environment())

    assert runtime.role == PARSER_WORKER_ROLE


def test_accepted_with_unrelated_lambda_variables_present() -> None:
    environment = {
        **lambda_parser_environment(),
        "AWS_ACCESS_KEY": ACCESS_KEY_ID,
        "AWS_EXECUTION_ENV": "AWS_Lambda_python3.13",
        "DATABASE_URL": "postgresql+psycopg://parser@db.invalid/app",
    }

    assert ParserWorkerRuntime.from_environment(environment, uid=993).uid == 993


# --- Each condition failing alone ---------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   "])
def test_condition_1_function_name_missing_or_blank(value: str | None) -> None:
    environment = lambda_parser_environment()
    if value is None:
        del environment["AWS_LAMBDA_FUNCTION_NAME"]
    else:
        environment["AWS_LAMBDA_FUNCTION_NAME"] = value

    assert not lambda_parser_credentials_allowed(environment)
    assert_rejected(environment)


@pytest.mark.parametrize(
    "missing", ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]
)
def test_condition_2_partial_credential_sets(missing: str) -> None:
    environment = lambda_parser_environment()
    del environment[missing]

    assert not lambda_parser_credentials_allowed(environment)
    assert_rejected(environment)


@pytest.mark.parametrize(
    "only", ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]
)
def test_condition_2_single_credential_alone(only: str) -> None:
    environment = lambda_parser_environment()
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        if name != only:
            del environment[name]

    assert_rejected(environment)


@pytest.mark.parametrize(
    "access_key_id",
    ["AKIAFAKEMARKERKEY001", "asiaFAKEMARKERKEY001", "XASIAMARKERKEY001", "ASI"],
)
def test_condition_2_long_term_or_malformed_access_key(access_key_id: str) -> None:
    environment = {**lambda_parser_environment(), "AWS_ACCESS_KEY_ID": access_key_id}

    assert not lambda_parser_credentials_allowed(environment)
    assert_rejected(environment)


@pytest.mark.parametrize("token", ["", "   "])
def test_condition_2_empty_session_token(token: str) -> None:
    environment = {**lambda_parser_environment(), "AWS_SESSION_TOKEN": token}

    assert not lambda_parser_credentials_allowed(environment)
    assert_rejected(environment)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PARSER_WORKER_ROLE", "general"),
        ("PARSER_WORKER_ROLE", "restricted-parser "),
        ("PARSER_WORKER_ROLE", ""),
        ("PARSER_WORKER_NETWORK", "default"),
        ("PARSER_WORKER_NETWORK", ""),
    ],
)
def test_condition_3_wrong_role_or_network(name: str, value: str) -> None:
    environment = {**lambda_parser_environment(), name: value}

    assert not lambda_parser_credentials_allowed(environment)
    assert_rejected(environment)


def test_condition_3_non_parser_role_with_lambda_credentials() -> None:
    environment = lambda_parser_environment()
    del environment["PARSER_WORKER_ROLE"]
    del environment["PARSER_WORKER_NETWORK"]

    assert_rejected(environment)


@pytest.mark.parametrize("model_key", ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"])
def test_condition_4_model_keys_stay_forbidden_with_lambda_credentials(
    model_key: str,
) -> None:
    environment = {
        **lambda_parser_environment(),
        model_key: "sk-fake-model-marker-004",
    }

    assert not lambda_parser_credentials_allowed(environment)
    assert_rejected(environment)


def test_all_conditions_failing_together() -> None:
    environment = {
        "AWS_ACCESS_KEY_ID": "AKIAFAKEMARKERKEY001",
        "AWS_SECRET_ACCESS_KEY": SECRET,
        "OPENAI_API_KEY": "sk-fake-model-marker-004",
        "PARSER_WORKER_ROLE": "general",
        "PARSER_WORKER_NETWORK": "default",
    }

    assert not lambda_parser_credentials_allowed(environment)
    assert_rejected(environment)


# --- Local and Compose configurations keep the strict rule --------------------


def compose_environment() -> dict[str, str]:
    return {"PARSER_WORKER_ROLE": PARSER_WORKER_ROLE, "PARSER_WORKER_NETWORK": "none"}


def test_compose_environment_without_credentials_still_passes() -> None:
    assert ParserWorkerRuntime.from_environment(compose_environment(), uid=10001)


@pytest.mark.parametrize("name", sorted(FORBIDDEN_CREDENTIAL_ENVIRONMENT_VARIABLES))
def test_compose_environment_rejects_every_credential_variable(name: str) -> None:
    value = ACCESS_KEY_ID if name == "AWS_ACCESS_KEY_ID" else "fake-secret-marker-002"

    assert_rejected({**compose_environment(), name: value})


def test_compose_environment_rejects_full_sts_credentials_outside_lambda() -> None:
    environment = lambda_parser_environment()
    del environment["AWS_LAMBDA_FUNCTION_NAME"]

    assert_rejected(environment)


def test_root_is_still_rejected_in_lambda() -> None:
    with pytest.raises(ParserWorkerConfigurationError, match="must not run as root"):
        ParserWorkerRuntime.from_environment(lambda_parser_environment(), uid=0)


def test_forbidden_set_is_unchanged() -> None:
    assert FORBIDDEN_CREDENTIAL_ENVIRONMENT_VARIABLES == frozenset(
        {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
        }
    )


def test_no_switch_can_enable_the_relaxation() -> None:
    source = Path(parser_worker.__file__).read_text(encoding="utf-8")
    environment_reads = set(re.findall(r"environment\.get\(\s*\"([A-Z_]+)\"", source))

    assert environment_reads == {
        "AWS_LAMBDA_FUNCTION_NAME",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "PARSER_WORKER_ROLE",
        "PARSER_WORKER_NETWORK",
    }


# --- Through the real parser handler ------------------------------------------


def _handler_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, environment: dict[str, str]
) -> None:
    from sqlalchemy import create_engine

    import ai_qa_copilot_api.documents  # noqa: F401 - registers the job tables
    from ai_qa_copilot_api.projects import Base

    for name in (
        *FORBIDDEN_CREDENTIAL_ENVIRONMENT_VARIABLES,
        "AWS_LAMBDA_FUNCTION_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    url = f"sqlite+pysqlite:///{tmp_path / 'parser.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    for name, value in {**environment, "DATABASE_URL": url}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(parser_worker, "current_uid", lambda: 993)


def _parser_handler() -> object:
    from ai_qa_copilot_api.ingestion import InMemoryQuarantineStorage
    from ai_qa_copilot_api.lambda_workers import (
        SqsWorkerHandler,
        build_parser_composition,
    )

    return SqsWorkerHandler(
        "parser",
        lambda: build_parser_composition(
            reader_factory=lambda bucket: InMemoryQuarantineStorage()
        ),
    )


def _event() -> dict[str, object]:
    return {"Records": [{"messageId": "m1", "body": "wake-up"}]}


def test_parser_handler_runs_with_the_real_check_in_a_lambda_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _handler_environment(monkeypatch, tmp_path, lambda_parser_environment())

    handler = _parser_handler()

    assert handler(_event(), None) == {"batchItemFailures": []}  # type: ignore[operator]


def test_parser_handler_still_fails_closed_outside_lambda(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    environment = lambda_parser_environment()
    del environment["AWS_LAMBDA_FUNCTION_NAME"]
    _handler_environment(monkeypatch, tmp_path, environment)

    handler = _parser_handler()

    with pytest.raises(ParserWorkerConfigurationError):
        handler(_event(), None)  # type: ignore[operator]
