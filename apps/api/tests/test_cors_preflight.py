"""A browser preflight gets a 204 before routing and auth, and nothing else does."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.audit import AuthorizationAuditEvent, AuthorizationAuditSink
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings, CognitoSettings
from ai_qa_copilot_api.documents import DocumentIntakeRecord
from ai_qa_copilot_api.ingestion import (
    InMemoryQuarantineStorage,
    SqlAlchemyDocumentIntakeRepository,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.observability import WorkflowTraceSink, WorkflowTraceSpan
from ai_qa_copilot_api.parser_queue import InMemoryParserJobQueue
from ai_qa_copilot_api.projects import (
    Base,
    ProjectRecord,
    SqlAlchemyProjectRepository,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
JOB_ID = "00000000-0000-0000-0000-000000000002"
ORIGIN = "https://app.example.invalid"
PREFLIGHT_HEADERS = {
    "Origin": ORIGIN,
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,content-type",
}
OWNER_ROUTES = [
    "/projects",
    f"/projects/{PROJECT_ID}",
    f"/projects/{PROJECT_ID}/documents",
    f"/projects/{PROJECT_ID}/execution-jobs/{JOB_ID}",
]


class RecordingAuditSink(AuthorizationAuditSink):
    def __init__(self) -> None:
        self.events: list[AuthorizationAuditEvent] = []

    def record(self, event: AuthorizationAuditEvent) -> None:
        self.events.append(event)


class RecordingTraceSink(WorkflowTraceSink):
    def __init__(self) -> None:
        self.spans: list[WorkflowTraceSpan] = []

    def record(self, span: WorkflowTraceSpan) -> None:
        self.spans.append(span)


@dataclass
class Harness:
    client: TestClient
    sessions: sessionmaker[Session]
    audit: RecordingAuditSink
    traces: RecordingTraceSink
    queue: InMemoryParserJobQueue
    storage: InMemoryQuarantineStorage

    def assert_no_side_effects(self) -> None:
        with self.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ProjectRecord)) == 0
            assert (
                session.scalar(select(func.count()).select_from(DocumentIntakeRecord))
                == 0
            )
        assert self.audit.events == []
        assert self.queue.jobs == []
        assert self.storage.objects == {}


def build_harness(tmp_path: Path, settings: AuthSettings) -> Generator[Harness]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'preflight.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    audit = RecordingAuditSink()
    traces = RecordingTraceSink()
    queue = InMemoryParserJobQueue()
    storage = InMemoryQuarantineStorage()
    application = create_app(
        settings,
        authorization_audit_sink=audit,
        project_repository=SqlAlchemyProjectRepository(sessions),
        document_intake_repository=SqlAlchemyDocumentIntakeRepository(sessions),
        quarantine_storage=storage,
        parser_job_queue=queue,
        workflow_trace_sink=traces,
    )
    with TestClient(application) as client:
        yield Harness(client, sessions, audit, traces, queue, storage)
    engine.dispose()


@pytest.fixture
def harness(tmp_path: Path) -> Generator[Harness]:
    """Real authentication: no bypass and no token sent."""

    yield from build_harness(
        tmp_path,
        AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=CognitoSettings(
                issuer="https://cognito-idp.example.com/us-east-1_example",
                client_id="example-client",
                owner_subject="owner-subject",
            ),
        ),
    )


@pytest.fixture
def bypass_harness(tmp_path: Path) -> Generator[Harness]:
    yield from build_harness(
        tmp_path,
        AuthSettings(
            app_env=AppEnvironment.LOCAL, local_auth_bypass_enabled=True, cognito=None
        ),
    )


# Preflight


@pytest.mark.parametrize("path", [*OWNER_ROUTES, "/health", "/demo", "/", "/missing"])
def test_preflight_returns_204_without_a_token_or_a_body(
    harness: Harness, path: str
) -> None:
    response = harness.client.options(path, headers=PREFLIGHT_HEADERS)

    assert response.status_code == 204
    assert response.content == b""
    assert "www-authenticate" not in response.headers


@pytest.mark.parametrize("path", OWNER_ROUTES)
def test_preflight_sets_correlation_and_never_a_cors_header(
    harness: Harness, path: str
) -> None:
    response = harness.client.options(path, headers=PREFLIGHT_HEADERS)

    assert UUID(response.headers["x-correlation-id"])
    assert not [
        name for name in response.headers if name.lower().startswith("access-control-")
    ]


@pytest.mark.parametrize("path", OWNER_ROUTES)
def test_preflight_has_no_side_effect_beyond_the_request_trace(
    harness: Harness, path: str
) -> None:
    response = harness.client.request(
        "OPTIONS", path, headers=PREFLIGHT_HEADERS, content=b"# ignored body"
    )

    assert response.status_code == 204
    harness.assert_no_side_effects()
    assert [span.name for span in harness.traces.spans] == ["api.request"]
    span = harness.traces.spans[0]
    assert span.trace_id == UUID(response.headers["x-correlation-id"])
    assert span.outcome == "succeeded"
    assert span.attributes == {"http.method": "OPTIONS", "http.path": path}


def test_preflight_ignores_an_invalid_token_without_auditing_it(
    harness: Harness,
) -> None:
    response = harness.client.options(
        "/projects",
        headers={**PREFLIGHT_HEADERS, "Authorization": "Bearer not-a-token"},
    )

    assert response.status_code == 204
    harness.assert_no_side_effects()


@pytest.mark.parametrize("requested", ["GET", "POST", "DELETE", "PUT", "not a method"])
def test_preflight_does_not_depend_on_the_requested_method_or_origin(
    harness: Harness, requested: str
) -> None:
    response = harness.client.options(
        "/projects", headers={"Access-Control-Request-Method": requested}
    )

    assert response.status_code == 204


# Other OPTIONS requests


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": ORIGIN},
        {"Origin": ORIGIN, "Access-Control-Request-Headers": "authorization"},
    ],
    ids=["no-headers", "origin-only", "request-headers-only"],
)
@pytest.mark.parametrize("path", ["/projects", "/health"])
def test_options_without_the_request_method_header_still_returns_405(
    harness: Harness, path: str, headers: dict[str, str]
) -> None:
    response = harness.client.options(path, headers=headers)

    assert response.status_code == 405
    assert "allow" in response.headers
    assert UUID(response.headers["x-correlation-id"])
    harness.assert_no_side_effects()


# Other methods


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/projects"),
        ("POST", "/projects"),
        ("GET", f"/projects/{PROJECT_ID}/documents"),
        ("POST", f"/projects/{PROJECT_ID}/documents"),
        ("DELETE", f"/projects/{PROJECT_ID}/execution-jobs/{JOB_ID}"),
    ],
)
@pytest.mark.parametrize(
    "headers", [{}, PREFLIGHT_HEADERS], ids=["plain", "with-preflight-headers"]
)
def test_other_methods_still_require_a_token_and_are_audited(
    harness: Harness, method: str, path: str, headers: dict[str, str]
) -> None:
    response = harness.client.request(
        method, path, headers=headers, json={"name": "x"} if method == "POST" else None
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert UUID(response.headers["x-correlation-id"])
    assert len(harness.audit.events) == 1
    assert harness.audit.events[0].reason == "invalid_or_missing_credentials"
    assert harness.queue.jobs == []
    assert harness.storage.objects == {}


def test_a_post_with_a_preflight_header_still_runs_the_route(
    bypass_harness: Harness,
) -> None:
    response = bypass_harness.client.post(
        "/projects", headers=PREFLIGHT_HEADERS, json={"name": "Real"}
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Real"


def test_a_preflight_after_a_create_changes_nothing(bypass_harness: Harness) -> None:
    created = bypass_harness.client.post("/projects", json={"name": "Only"})
    assert created.status_code == 201
    events = len(bypass_harness.audit.events)

    response = bypass_harness.client.options("/projects", headers=PREFLIGHT_HEADERS)

    assert response.status_code == 204
    assert len(bypass_harness.audit.events) == events
    listed = bypass_harness.client.get("/projects").json()
    assert [project["name"] for project in listed] == ["Only"]
