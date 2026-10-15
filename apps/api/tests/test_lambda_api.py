from __future__ import annotations

import base64
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from mangum import Mangum
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api import lambda_api
from ai_qa_copilot_api import main as main_module
from ai_qa_copilot_api import s3_quarantine
from ai_qa_copilot_api.auth import (
    AppEnvironment,
    AuthConfigurationError,
    AuthSettings,
    CognitoSettings,
)
from ai_qa_copilot_api.database_engine import create_shared_engine
from ai_qa_copilot_api.ingestion import (
    InMemoryQuarantineStorage,
    SqlAlchemyDocumentIntakeRepository,
    UploadPolicy,
    UploadPolicyConfigurationError,
)
from ai_qa_copilot_api.lambda_api import API_GATEWAY_BASE_PATH, LambdaApiHandler
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.parser_queue import InMemoryParserJobQueue
from ai_qa_copilot_api.projects import Base, SqlAlchemyProjectRepository
from ai_qa_copilot_api.s3_quarantine import S3QuarantineStorage


CONTEXT = SimpleNamespace(function_name="api", aws_request_id="request-1")
SECRET_PASSWORD = "env-secret-password-7f3a"
SECRET_BUCKET = "env-secret-bucket-91c2"
ENVIRONMENT_NAMES = (
    "APP_ENV",
    "LOCAL_AUTH_BYPASS_ENABLED",
    "COGNITO_ISSUER",
    "COGNITO_CLIENT_ID",
    "COGNITO_OWNER_SUBJECT",
    "DATABASE_URL",
    "DATA_BUCKET_NAME",
    "DOCUMENT_UPLOAD_MAX_BYTES",
    "MODEL_PROVIDER",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL, local_auth_bypass_enabled=True, cognito=None
    )


def http_event(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    base64_body: bool = False,
    query: str = "",
) -> dict[str, Any]:
    """A minimal API Gateway HTTP API payload format 2.0 event."""

    encoded: str | None
    if body is None:
        encoded = None
    elif base64_body:
        encoded = base64.b64encode(body).decode("ascii")
    else:
        encoded = body.decode("utf-8")
    event: dict[str, Any] = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": query,
        "headers": {
            "host": "abc123.execute-api.us-east-1.amazonaws.com",
            "x-forwarded-proto": "https",
            **{name.lower(): value for name, value in (headers or {}).items()},
        },
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "abc123",
            "domainName": "abc123.execute-api.us-east-1.amazonaws.com",
            "domainPrefix": "abc123",
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "192.0.2.10",
                "userAgent": "pytest",
            },
            "requestId": "request-1",
            "routeKey": "$default",
            "stage": "$default",
            "time": "15/Oct/2026:12:00:00 +0000",
            "timeEpoch": 1792065600000,
        },
        "isBase64Encoded": base64_body,
    }
    if encoded is not None:
        event["body"] = encoded
    return event


def response_body(response: dict[str, Any]) -> Any:
    body = response.get("body", "")
    if response.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body) if body else None


@pytest.fixture
def sessions(tmp_path: Path) -> Any:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lambda.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    engine.dispose()


def intake_handler(
    sessions: Any, storage: InMemoryQuarantineStorage, policy: UploadPolicy
) -> LambdaApiHandler:
    return LambdaApiHandler(
        create_app(
            local_bypass_settings(),
            project_repository=SqlAlchemyProjectRepository(sessions),
            document_intake_repository=SqlAlchemyDocumentIntakeRepository(sessions),
            quarantine_storage=storage,
            parser_job_queue=InMemoryParserJobQueue(),
            document_intake_policy=policy,
        )
    )


# --- Module wiring ------------------------------------------------------------


def test_module_handler_wraps_the_module_app_and_starts_nothing_at_import() -> None:
    assert isinstance(lambda_api.handler, LambdaApiHandler)
    assert lambda_api.handler.application is main_module.app
    assert API_GATEWAY_BASE_PATH == "/"


def test_module_source_has_no_secret_like_strings() -> None:
    source = Path(lambda_api.__file__).read_text(encoding="utf-8")

    assert re.search(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b", source) is None
    for forbidden in (
        "aws_access_key_id",
        "aws_secret_access_key",
        "password",
        "Bearer ",
        "sk-",
        "print(",
        "logging",
        "logger",
    ):
        assert forbidden not in source


# --- Requests through simulated HTTP API v2 events ----------------------------


def test_health_matches_the_plain_asgi_response() -> None:
    application = create_app(local_bypass_settings())
    handler = LambdaApiHandler(application)

    response = handler(http_event("GET", "/health"), CONTEXT)
    with TestClient(create_app(local_bypass_settings())) as http:
        expected = http.get("/health")

    assert response["statusCode"] == 200
    assert response_body(response) == expected.json()
    assert UUID(response["headers"]["x-correlation-id"])


def test_unauthenticated_owner_route_matches_the_plain_asgi_401() -> None:
    settings = AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=False,
        cognito=CognitoSettings(
            issuer="https://cognito-idp.example.com/us-east-1_example",
            client_id="example-client",
            owner_subject="owner-subject",
        ),
    )
    handler = LambdaApiHandler(create_app(settings))

    response = handler(http_event("GET", "/projects"), CONTEXT)
    with TestClient(create_app(settings)) as http:
        expected = http.get("/projects")

    assert response["statusCode"] == expected.status_code == 401
    assert response_body(response) == expected.json()
    assert response["headers"]["www-authenticate"] == "Bearer"


def test_json_body_route(sessions: Any) -> None:
    handler = LambdaApiHandler(
        create_app(
            local_bypass_settings(),
            project_repository=SqlAlchemyProjectRepository(sessions),
        )
    )

    created = handler(
        http_event(
            "POST",
            "/projects",
            headers={"content-type": "application/json"},
            body=json.dumps({"name": "Lambda", "description": None}).encode(),
        ),
        CONTEXT,
    )
    listed = handler(http_event("GET", "/projects"), CONTEXT)

    assert created["statusCode"] == 201
    assert response_body(created)["name"] == "Lambda"
    assert [item["name"] for item in response_body(listed)] == ["Lambda"]


def test_base64_upload_reaches_the_route_intact(sessions: Any) -> None:
    storage = InMemoryQuarantineStorage()
    project_id = (
        SqlAlchemyProjectRepository(sessions).create(name="Docs", description=None).id
    )
    handler = intake_handler(sessions, storage, UploadPolicy())
    line = b"- The API must reject unauthenticated requests with 401.\n"
    content = b"# Requirements\n\n" + line * 2000
    assert len(content) > 64 * 1024

    response = handler(
        http_event(
            "POST",
            f"/projects/{project_id}/documents",
            headers={
                "X-Upload-Filename": "requirements.md",
                "Content-Type": "text/markdown",
                "Content-Length": str(len(content)),
            },
            body=content,
            base64_body=True,
        ),
        CONTEXT,
    )

    assert response["statusCode"] == 202
    assert response_body(response)["byte_size"] == len(content)
    [(stored, content_type)] = storage.objects.values()
    assert stored == content
    assert content_type == "text/markdown"


@pytest.mark.parametrize("declare_length", [True, False])
def test_over_cap_upload_is_rejected_through_the_handler(
    sessions: Any, declare_length: bool
) -> None:
    storage = InMemoryQuarantineStorage()
    project_id = (
        SqlAlchemyProjectRepository(sessions).create(name="Docs", description=None).id
    )
    handler = intake_handler(sessions, storage, UploadPolicy(max_raw_bytes=1024))
    content = b"a" * 1025
    headers = {"X-Upload-Filename": "big.md", "Content-Type": "text/markdown"}
    if declare_length:
        headers["Content-Length"] = str(len(content))

    response = handler(
        http_event(
            "POST",
            f"/projects/{project_id}/documents",
            headers=headers,
            body=content,
            base64_body=True,
        ),
        CONTEXT,
    )

    assert response["statusCode"] == 413
    assert response_body(response)["detail"]["code"] == "UPLOAD_SIZE_LIMIT"
    assert storage.objects == {}


# --- Lifespan once per process ------------------------------------------------


def _create_tables(database_url: str) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()


def _configure_production_like_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[str, list[Any]]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'env.db'}"
    _create_tables(database_url)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("LOCAL_AUTH_BYPASS_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATA_BUCKET_NAME", SECRET_BUCKET)
    fake_clients: list[Any] = []

    def fake_bucket_client() -> Any:
        client = SimpleNamespace(name="fake-s3-client")
        fake_clients.append(client)
        return client

    monkeypatch.setattr(s3_quarantine, "default_s3_client", fake_bucket_client)
    engines: list[Any] = []

    def counting_engine(url: str) -> Any:
        engine = create_shared_engine(url)
        engines.append(engine)
        return engine

    monkeypatch.setattr(main_module, "create_shared_engine", counting_engine)
    return database_url, engines


def test_two_invocations_share_one_app_one_lifespan_and_one_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, engines = _configure_production_like_environment(monkeypatch, tmp_path)
    application = create_app()
    handler = LambdaApiHandler(application)

    assert not handler.started
    first = handler(http_event("GET", "/projects"), CONTEXT)
    engine_after_first = application.state.database_engine
    repository_after_first = application.state.project_repository
    second = handler(http_event("GET", "/projects"), CONTEXT)

    assert first["statusCode"] == second["statusCode"] == 200
    assert handler.started
    assert handler.application is application
    assert len(engines) == 1
    assert application.state.database_engine is engine_after_first is engines[0]
    assert application.state.project_repository is repository_after_first
    assert isinstance(repository_after_first, SqlAlchemyProjectRepository)
    storage = application.state.document_intake_service._storage  # noqa: SLF001
    assert isinstance(storage, S3QuarantineStorage)


def test_mangum_lifespan_would_run_startup_per_invocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression evidence for why the handler uses lifespan="off"."""

    _, engines = _configure_production_like_environment(monkeypatch, tmp_path)
    adapter = Mangum(create_app(), lifespan="auto")

    adapter(http_event("GET", "/health"), CONTEXT)
    adapter(http_event("GET", "/health"), CONTEXT)

    assert len(engines) == 2


def test_lifespan_off_without_startup_would_leave_no_boundaries() -> None:
    adapter = Mangum(create_app(local_bypass_settings()), lifespan="off")

    response = adapter(http_event("GET", "/health"), CONTEXT)

    assert response["statusCode"] == 500


def test_no_configuration_fails_closed_with_existing_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("LOCAL_AUTH_BYPASS_ENABLED", "true")
    application = create_app()
    handler = LambdaApiHandler(application)

    projects = handler(http_event("GET", "/projects"), CONTEXT)
    with TestClient(create_app()) as http:
        expected = http.get("/projects")

    assert projects["statusCode"] == expected.status_code == 503
    assert response_body(projects) == expected.json()
    assert application.state.database_engine is None


def test_missing_app_env_fails_the_invocation_like_create_app() -> None:
    handler = LambdaApiHandler(create_app())

    with pytest.raises(AuthConfigurationError):
        handler(http_event("GET", "/health"), CONTEXT)
    assert not handler.started


def test_startup_failure_is_retried_on_the_next_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("LOCAL_AUTH_BYPASS_ENABLED", "true")
    monkeypatch.setenv("DOCUMENT_UPLOAD_MAX_BYTES", "not-a-number")
    handler = LambdaApiHandler(create_app())

    with pytest.raises(UploadPolicyConfigurationError):
        handler(http_event("GET", "/health"), CONTEXT)
    assert not handler.started

    monkeypatch.delenv("DOCUMENT_UPLOAD_MAX_BYTES")
    response = handler(http_event("GET", "/health"), CONTEXT)

    assert response["statusCode"] == 200
    assert handler.started


def test_responses_contain_no_environment_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / SECRET_PASSWORD}.db"
    _create_tables(database_url)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("LOCAL_AUTH_BYPASS_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATA_BUCKET_NAME", SECRET_BUCKET)
    monkeypatch.setattr(
        s3_quarantine, "default_s3_client", lambda: SimpleNamespace(name="fake")
    )
    handler = LambdaApiHandler(create_app())

    responses = [
        handler(http_event("GET", "/health"), CONTEXT),
        handler(http_event("GET", "/projects"), CONTEXT),
        handler(
            http_event("GET", "/projects/00000000-0000-0000-0000-000000000001"),
            CONTEXT,
        ),
        handler(
            http_event(
                "GET",
                "/projects/00000000-0000-0000-0000-000000000001/documents",
            ),
            CONTEXT,
        ),
    ]

    serialized = json.dumps(responses)
    for value in (SECRET_PASSWORD, SECRET_BUCKET, str(tmp_path)):
        assert value not in serialized
