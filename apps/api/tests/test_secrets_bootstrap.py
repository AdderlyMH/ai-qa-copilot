"""Cold-start secret bootstrap (INFRA-008 Stage A); fakes and Stubber only."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import traceback
from types import SimpleNamespace
from typing import Any

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.stub import Stubber
from fastapi import FastAPI
import pytest

from ai_qa_copilot_api import lambda_workers
from ai_qa_copilot_api.lambda_api import LambdaApiHandler
from ai_qa_copilot_api.lambda_workers import SqsWorkerHandler, WorkerComposition
from ai_qa_copilot_api.secrets_bootstrap import (
    DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE,
    OPENAI_API_KEY_SECRET_ARN_ENVIRONMENT_VARIABLE,
    ColdStartSecrets,
    SecretBootstrapError,
    cold_start_secrets,
    default_secrets_manager_client,
    load_secrets_into_environment,
)


# Obvious test-only values; the assertions check they never leak.
DATABASE_ARN = (
    "arn:aws:secretsmanager:us-east-1:000000000000:secret:"
    "ai-qa-copilot-production/database-url-ArnSuffixDb"
)
API_KEY_ARN = (
    "arn:aws:secretsmanager:us-east-1:000000000000:secret:"
    "ai-qa-copilot-production/openai-api-key-ArnSuffixKey"
)
DATABASE_PASSWORD = "unit-test-database-sentinel"
DATABASE_URL = (
    f"postgresql+psycopg://copilot_app:{DATABASE_PASSWORD}"
    "@database.invalid:5432/ai_qa_copilot"
)
API_KEY = "unit-test-model-key-sentinel"
SENSITIVE = (DATABASE_PASSWORD, API_KEY, "ArnSuffixDb", "ArnSuffixKey", DATABASE_ARN)


class FakeClient:
    """Answers GetSecretValue from a table of responses or exceptions."""

    def __init__(self, answers: Mapping[str, Any]) -> None:
        self._answers = answers
        self.calls: list[str] = []

    def get_secret_value(self, **kwargs: Any) -> Mapping[str, Any]:
        secret_id = kwargs["SecretId"]
        self.calls.append(secret_id)
        answer = self._answers[secret_id]
        if isinstance(answer, Exception):
            raise answer
        result: Mapping[str, Any] = answer
        return result


def client_error(code: str) -> ClientError:
    # The service message echoes identifiers, as AWS does.
    return ClientError(
        {
            "Error": {
                "Code": code,
                "Message": f"denied for {DATABASE_ARN} value {DATABASE_PASSWORD}",
            }
        },
        "GetSecretValue",
    )


def production_environment(**overrides: str) -> dict[str, str]:
    environ = {
        "APP_ENV": "production",
        DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE: DATABASE_ARN,
        OPENAI_API_KEY_SECRET_ARN_ENVIRONMENT_VARIABLE: API_KEY_ARN,
    }
    environ.update(overrides)
    return environ


def answers(**overrides: Any) -> dict[str, Any]:
    table: dict[str, Any] = {
        DATABASE_ARN: {"SecretString": DATABASE_URL},
        API_KEY_ARN: {"SecretString": API_KEY},
    }
    table.update(overrides)
    return table


def factory(client: FakeClient) -> Callable[[], FakeClient]:
    return lambda: client


def assert_sanitized(error: BaseException) -> None:
    rendered = "".join(traceback.format_exception(error))
    for sensitive in SENSITIVE:
        assert sensitive not in rendered
        assert sensitive not in repr(error)
    # No chained AWS exception may appear in a traceback.
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__


def load_failure(environ: dict[str, str], client: FakeClient) -> SecretBootstrapError:
    with pytest.raises(SecretBootstrapError) as raised:
        load_secrets_into_environment(environ, client_factory=factory(client))
    assert_sanitized(raised.value)
    return raised.value


# --- Success and the unchanged local path ---------------------------------------


def test_production_loads_both_secrets_into_the_environment() -> None:
    environ = production_environment()
    client = FakeClient(answers())

    assert load_secrets_into_environment(environ, client_factory=factory(client))

    assert environ["DATABASE_URL"] == DATABASE_URL
    assert environ["OPENAI_API_KEY"] == API_KEY
    assert client.calls == [DATABASE_ARN, API_KEY_ARN]


def test_surrounding_whitespace_in_a_secret_value_is_removed() -> None:
    environ = production_environment()
    client = FakeClient(answers(**{API_KEY_ARN: {"SecretString": f"  {API_KEY}\n"}}))

    load_secrets_into_environment(environ, client_factory=factory(client))

    assert environ["OPENAI_API_KEY"] == API_KEY


@pytest.mark.parametrize("app_env", ["", "local", "preview"])
def test_local_and_test_runs_without_arns_are_unchanged(app_env: str) -> None:
    environ = {"APP_ENV": app_env, "DATABASE_URL": "sqlite://", "OPENAI_API_KEY": "x"}
    before = dict(environ)

    def no_client() -> FakeClient:
        raise AssertionError("no client may be created")

    assert load_secrets_into_environment(environ, client_factory=no_client) is False
    assert environ == before


def test_success_logs_no_value(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    environ = production_environment()

    load_secrets_into_environment(
        environ, client_factory=factory(FakeClient(answers()))
    )

    for sensitive in SENSITIVE:
        assert sensitive not in caplog.text
    assert "secrets.loaded count=2" in caplog.text


# --- Fail closed ----------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    [
        DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE,
        OPENAI_API_KEY_SECRET_ARN_ENVIRONMENT_VARIABLE,
    ],
)
def test_production_requires_both_arn_variables(missing: str) -> None:
    environ = production_environment(**{missing: ""})
    client = FakeClient(answers())

    error = load_failure(environ, client)

    assert missing in str(error)
    assert client.calls == []
    assert "DATABASE_URL" not in environ and "OPENAI_API_KEY" not in environ


def test_one_arn_outside_production_still_requires_both() -> None:
    environ = {
        "APP_ENV": "local",
        DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE: DATABASE_ARN,
    }

    error = load_failure(environ, FakeClient(answers()))

    assert OPENAI_API_KEY_SECRET_ARN_ENVIRONMENT_VARIABLE in str(error)


def test_a_value_that_is_not_a_secret_arn_is_refused() -> None:
    environ = production_environment(
        **{DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE: "database-url-ArnSuffixDb"}
    )

    error = load_failure(environ, FakeClient(answers()))

    assert "is not a Secrets Manager secret ARN" in str(error)


@pytest.mark.parametrize("variable", ["DATABASE_URL", "OPENAI_API_KEY"])
def test_a_plain_value_already_in_the_environment_is_refused(variable: str) -> None:
    environ = production_environment(**{variable: "configured-elsewhere"})

    error = load_failure(environ, FakeClient(answers()))

    assert variable in str(error)
    assert environ[variable] == "configured-elsewhere"


@pytest.mark.parametrize(
    "code",
    ["ResourceNotFoundException", "AccessDeniedException", "DecryptionFailure"],
)
def test_aws_errors_fail_closed_with_the_code_only(code: str) -> None:
    environ = production_environment()
    client = FakeClient(answers(**{DATABASE_ARN: client_error(code)}))

    error = load_failure(environ, client)

    assert str(error) == f"Secret database-url could not be read ({code})"
    assert "DATABASE_URL" not in environ and "OPENAI_API_KEY" not in environ


def test_an_unsafe_error_code_is_not_echoed() -> None:
    environ = production_environment()
    client = FakeClient(answers(**{API_KEY_ARN: client_error(f"Bad {API_KEY}")}))

    error = load_failure(environ, client)

    assert str(error) == "Secret openai-api-key could not be read (ClientError)"


def test_transport_errors_fail_closed_with_the_type_only() -> None:
    environ = production_environment()
    transport = EndpointConnectionError(endpoint_url=f"https://{DATABASE_ARN}")
    client = FakeClient(answers(**{API_KEY_ARN: transport}))

    error = load_failure(environ, client)

    assert str(error) == (
        "Secret openai-api-key could not be read (EndpointConnectionError)"
    )
    # Nothing is written when the second secret fails.
    assert "DATABASE_URL" not in environ


def test_client_creation_errors_fail_closed() -> None:
    def broken() -> FakeClient:
        raise RuntimeError(f"no region for {DATABASE_ARN}")

    with pytest.raises(SecretBootstrapError) as raised:
        load_secrets_into_environment(production_environment(), client_factory=broken)

    assert str(raised.value) == (
        "Secrets Manager client could not be created (RuntimeError)"
    )
    assert_sanitized(raised.value)


@pytest.mark.parametrize(
    "response",
    [{}, {"SecretString": ""}, {"SecretString": "   \n"}, {"SecretBinary": b"x"}],
)
def test_missing_or_empty_values_fail_closed(response: Mapping[str, Any]) -> None:
    environ = production_environment()

    error = load_failure(environ, FakeClient(answers(**{API_KEY_ARN: response})))

    assert str(error) == "Secret openai-api-key has no string value"


@pytest.mark.parametrize(
    "value",
    [
        "not a url",
        f"mysql://copilot_app:{DATABASE_PASSWORD}@database.invalid/ai_qa_copilot",
        "postgresql+psycopg://database.invalid:5432/ai_qa_copilot",
        f"postgresql+psycopg://copilot_app:{DATABASE_PASSWORD}@database.invalid:5432",
        f"postgresql+psycopg://copilot_app@{DATABASE_PASSWORD}.invalid/ai_qa_copilot",
    ],
)
def test_malformed_database_urls_fail_closed(value: str) -> None:
    environ = production_environment()

    error = load_failure(
        environ, FakeClient(answers(**{DATABASE_ARN: {"SecretString": value}}))
    )

    assert str(error).startswith("Secret database-url ")
    assert value not in str(error)
    assert "DATABASE_URL" not in environ


@pytest.mark.parametrize("value", [f"{API_KEY} extra", f"{API_KEY}é"])
def test_unusable_api_keys_fail_closed(value: str) -> None:
    environ = production_environment()

    error = load_failure(
        environ, FakeClient(answers(**{API_KEY_ARN: {"SecretString": value}}))
    )

    assert str(error) == (
        "Secret openai-api-key must be one token of printable characters"
    )


def test_failures_log_no_value(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client = FakeClient(
        answers(**{DATABASE_ARN: client_error("AccessDeniedException")})
    )

    with pytest.raises(SecretBootstrapError):
        load_secrets_into_environment(
            production_environment(), client_factory=factory(client)
        )

    for sensitive in SENSITIVE:
        assert sensitive not in caplog.text


# --- Real client shape (Stubber, unsigned, no network) --------------------------


@pytest.fixture
def isolated_aws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "missing-aws-config"))
    monkeypatch.setenv(
        "AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "missing-aws-credentials")
    )
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def stubbed(isolated_aws: None) -> Iterator[tuple[Any, Stubber]]:
    client = boto3.session.Session().client(
        "secretsmanager",
        region_name="us-east-1",
        config=Config(signature_version=UNSIGNED),
    )
    with Stubber(client) as stubber:
        yield client, stubber


def test_botocore_stubbed_success_and_access_denied(
    stubbed: tuple[Any, Stubber],
) -> None:
    client, stubber = stubbed
    stubber.add_response(
        "get_secret_value",
        {"SecretString": DATABASE_URL, "ARN": DATABASE_ARN, "Name": "database-url"},
        {"SecretId": DATABASE_ARN},
    )
    stubber.add_client_error(
        "get_secret_value",
        service_error_code="AccessDeniedException",
        service_message=f"not allowed on {API_KEY_ARN}",
        http_status_code=400,
        expected_params={"SecretId": API_KEY_ARN},
    )
    environ = production_environment()

    with pytest.raises(SecretBootstrapError) as raised:
        load_secrets_into_environment(environ, client_factory=lambda: client)

    assert str(raised.value) == (
        "Secret openai-api-key could not be read (AccessDeniedException)"
    )
    assert_sanitized(raised.value)
    assert "DATABASE_URL" not in environ
    stubber.assert_no_pending_responses()


def test_default_client_uses_three_standard_attempts_and_short_timeouts(
    isolated_aws: None,
) -> None:
    client: Any = default_secrets_manager_client()

    assert client.meta.service_model.service_name == "secretsmanager"
    assert client.meta.config.retries == {"mode": "standard", "total_max_attempts": 3}
    assert client.meta.config.connect_timeout == 5
    assert client.meta.config.read_timeout == 5


# --- Once per process -----------------------------------------------------------


def test_cold_start_secrets_loads_once_and_retries_after_a_failure() -> None:
    results: list[bool | Exception] = [SecretBootstrapError("first"), True]
    calls: list[int] = []

    def load() -> bool:
        calls.append(1)
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    bootstrap = ColdStartSecrets(load)

    with pytest.raises(SecretBootstrapError):
        bootstrap()
    assert not bootstrap.loaded
    bootstrap()
    bootstrap()

    assert bootstrap.loaded
    assert len(calls) == 2


# --- Handler wiring -------------------------------------------------------------


def test_api_handler_runs_the_bootstrap_before_startup_and_fails_closed() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        events.append("startup")  # pragma: no cover - must not run
        yield

    application = FastAPI(lifespan=lifespan)

    def failing_bootstrap() -> None:
        events.append("bootstrap")
        raise SecretBootstrapError("Secret database-url could not be read (X)")

    handler = LambdaApiHandler(application, bootstrap=failing_bootstrap)

    with pytest.raises(SecretBootstrapError):
        handler({"version": "2.0"}, SimpleNamespace())

    assert events == ["bootstrap"]
    assert not handler.started


def test_worker_handler_runs_the_bootstrap_before_building() -> None:
    events: list[str] = []

    def build() -> WorkerComposition:  # pragma: no cover - must not run
        events.append("build")
        raise AssertionError("must not build")

    def failing_bootstrap() -> None:
        events.append("bootstrap")
        raise SecretBootstrapError("Secret openai-api-key could not be read (X)")

    handler = SqsWorkerHandler("general", build, bootstrap=failing_bootstrap)

    with pytest.raises(SecretBootstrapError):
        handler({"Records": [{"messageId": "m-1"}]}, None)

    assert events == ["bootstrap"]
    assert handler.composition is None


def test_only_the_api_and_general_handlers_load_secrets() -> None:
    from ai_qa_copilot_api import lambda_api

    assert lambda_api.handler._bootstrap is cold_start_secrets
    assert lambda_workers.general_handler._bootstrap is cold_start_secrets
    assert lambda_workers.parser_handler._bootstrap is None
    assert lambda_workers.executor_handler._bootstrap is None
