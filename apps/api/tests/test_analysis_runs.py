from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import overload
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.analysis_runs import (
    AnalysisRunRepository,
    AnalysisRunService,
    SqlAlchemyAnalysisRunRepository,
    UnavailableAnalysisRunService,
    analysis_run_service_from_environment,
)
from ai_qa_copilot_api.audit import AuthorizationAuditEvent, AuthorizationAuditSink
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.model_gateway import (
    B1_MODEL_ID,
    C1_CONFIGURATION_VERSION,
    C1_MODEL_ID,
    AnthropicMessagesAdapter,
    ModelGateway,
    ModelGatewayRefusal,
    ModelGatewayTimeout,
    OpenAIResponsesAdapter,
    ModelUsage,
    StructuredModelRequest,
    StructuredModelResponse,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import (
    Base,
    ProjectRepository,
    SqlAlchemyProjectRepository,
)


class RecordingAuditSink(AuthorizationAuditSink):
    def __init__(self) -> None:
        self.events: list[AuthorizationAuditEvent] = []

    def record(self, event: AuthorizationAuditEvent) -> None:
        self.events.append(event)


class EchoFakeAdapter:
    def __init__(self) -> None:
        self.requests: list[StructuredModelRequest] = []

    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.requests.append(request)
        return StructuredModelResponse(
            correlation_id=request.correlation_id,
            response_id="fake-response-001",
            model_id=B1_MODEL_ID,
            output_json={"summary": f"Synthetic: {request.user_input}"},
            usage=ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7),
        )


class FailingFakeAdapter:
    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        del request
        raise ModelGatewayTimeout("Model provider timed out")


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


@pytest.fixture
def repositories(
    tmp_path: Path,
) -> Generator[tuple[ProjectRepository, AnalysisRunRepository]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'analysis-runs.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    yield (
        SqlAlchemyProjectRepository(sessions),
        SqlAlchemyAnalysisRunRepository(sessions),
    )
    engine.dispose()


@overload
def app_client(
    *,
    project_repository: ProjectRepository,
    analysis_run_repository: AnalysisRunRepository,
    adapter: None = None,
) -> tuple[TestClient, EchoFakeAdapter]: ...


@overload
def app_client(
    *,
    project_repository: ProjectRepository,
    analysis_run_repository: AnalysisRunRepository,
    adapter: EchoFakeAdapter,
) -> tuple[TestClient, EchoFakeAdapter]: ...


@overload
def app_client(
    *,
    project_repository: ProjectRepository,
    analysis_run_repository: AnalysisRunRepository,
    adapter: FailingFakeAdapter,
) -> tuple[TestClient, FailingFakeAdapter]: ...


def app_client(
    *,
    project_repository: ProjectRepository,
    analysis_run_repository: AnalysisRunRepository,
    adapter: EchoFakeAdapter | FailingFakeAdapter | None = None,
) -> tuple[TestClient, EchoFakeAdapter | FailingFakeAdapter]:
    selected_adapter = adapter or EchoFakeAdapter()
    return (
        TestClient(
            create_app(
                local_bypass_settings(),
                project_repository=project_repository,
                analysis_run_service=AnalysisRunService(
                    analysis_run_repository,
                    ModelGateway(selected_adapter),
                ),
            )
        ),
        selected_adapter,
    )


def create_project(client: TestClient) -> UUID:
    response = client.post("/projects", json={"name": "Synthetic analysis project"})
    assert response.status_code == 201
    return UUID(response.json()["id"])


def test_owner_can_persist_and_reload_one_synthetic_analysis_run(
    repositories: tuple[ProjectRepository, AnalysisRunRepository],
) -> None:
    project_repository, analysis_run_repository = repositories
    client, adapter = app_client(
        project_repository=project_repository,
        analysis_run_repository=analysis_run_repository,
    )
    with client:
        project_id = create_project(client)
        created = client.post(
            f"/projects/{project_id}/analysis-runs",
            json={"synthetic_text": "Checkout validation must reject blank cart IDs."},
        )

    with app_client(
        project_repository=project_repository,
        analysis_run_repository=analysis_run_repository,
    )[0] as refreshed_client:
        reloaded = refreshed_client.get(f"/projects/{project_id}/analysis-runs")

    assert created.status_code == 201
    assert UUID(created.headers["X-Correlation-ID"])
    assert created.json()["project_id"] == str(project_id)
    assert created.json()["output_json"] == {
        "summary": "Synthetic: Checkout validation must reject blank cart IDs."
    }
    assert created.json()["model_id"] == B1_MODEL_ID
    assert created.json()["configuration_version"] == "B1/v1"
    assert created.json()["prompt_version"] == "synthetic-analysis-v1"
    assert created.json()["schema_name"] == "synthetic_analysis_v1"
    assert created.json()["total_tokens"] == 7
    assert reloaded.status_code == 200
    assert UUID(reloaded.headers["X-Correlation-ID"])
    assert reloaded.json() == [created.json()]
    assert len(adapter.requests) == 1
    assert adapter.requests[0].user_input == created.json()["synthetic_text"]


def test_model_failure_returns_a_safe_error_with_a_correlation_id(
    repositories: tuple[ProjectRepository, AnalysisRunRepository],
) -> None:
    project_repository, analysis_run_repository = repositories
    client, _ = app_client(
        project_repository=project_repository,
        analysis_run_repository=analysis_run_repository,
        adapter=FailingFakeAdapter(),
    )
    with client:
        project_id = create_project(client)
        response = client.post(
            f"/projects/{project_id}/analysis-runs",
            json={"synthetic_text": "Synthetic provider failure case."},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Analysis service is temporarily unavailable"}
    assert UUID(response.headers["X-Correlation-ID"])
    assert analysis_run_repository.list_for_project(project_id) == []


def test_missing_analysis_configuration_returns_a_safe_error_with_a_correlation_id(
    repositories: tuple[ProjectRepository, AnalysisRunRepository],
) -> None:
    project_repository, analysis_run_repository = repositories
    app = create_app(
        local_bypass_settings(),
        project_repository=project_repository,
        analysis_run_service=UnavailableAnalysisRunService(),
    )
    with TestClient(app) as client:
        project_id = create_project(client)
        response = client.post(
            f"/projects/{project_id}/analysis-runs",
            json={"synthetic_text": "Synthetic unavailable configuration case."},
        )

    assert response.status_code == 503
    assert UUID(response.headers["X-Correlation-ID"])
    assert analysis_run_repository.list_for_project(project_id) == []


def test_unauthenticated_model_request_is_denied_before_the_gateway(
    repositories: tuple[ProjectRepository, AnalysisRunRepository],
) -> None:
    project_repository, analysis_run_repository = repositories
    project = project_repository.create(name="Private project", description=None)
    adapter = EchoFakeAdapter()
    app = create_app(
        AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=None,
        ),
        project_repository=project_repository,
        analysis_run_service=AnalysisRunService(
            analysis_run_repository,
            ModelGateway(adapter),
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/projects/{project.id}/analysis-runs",
            json={"synthetic_text": "Synthetic unauthenticated case."},
        )

    assert response.status_code == 401
    assert UUID(response.headers["X-Correlation-ID"])
    assert adapter.requests == []
    assert analysis_run_repository.list_for_project(project.id) == []


def test_missing_project_is_hidden_before_the_gateway(
    repositories: tuple[ProjectRepository, AnalysisRunRepository],
) -> None:
    project_repository, analysis_run_repository = repositories
    client, adapter = app_client(
        project_repository=project_repository,
        analysis_run_repository=analysis_run_repository,
    )

    with client:
        response = client.post(
            f"/projects/{uuid4()}/analysis-runs",
            json={"synthetic_text": "Synthetic missing project case."},
        )

    assert response.status_code == 404
    assert UUID(response.headers["X-Correlation-ID"])
    assert adapter.requests == []


class ClaudeFakeAdapter:
    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        return StructuredModelResponse(
            correlation_id=request.correlation_id,
            response_id="msg_fake_001",
            model_id=C1_MODEL_ID,
            output_json={"summary": "Synthetic claude summary"},
            usage=ModelUsage(input_tokens=5, output_tokens=6, total_tokens=11),
            configuration_version=C1_CONFIGURATION_VERSION,
            provider="anthropic",
        )


class RefusingFakeAdapter:
    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        del request
        raise ModelGatewayRefusal("Model provider declined the request")


def claude_client(
    project_repository: ProjectRepository,
    analysis_run_repository: AnalysisRunRepository,
    adapter: ClaudeFakeAdapter | RefusingFakeAdapter,
) -> TestClient:
    return TestClient(
        create_app(
            local_bypass_settings(),
            project_repository=project_repository,
            analysis_run_service=AnalysisRunService(
                analysis_run_repository, ModelGateway(adapter)
            ),
        )
    )


def test_openai_run_provenance_records_the_openai_provider(
    repositories: tuple[ProjectRepository, AnalysisRunRepository],
) -> None:
    project_repository, analysis_run_repository = repositories
    client, _ = app_client(
        project_repository=project_repository,
        analysis_run_repository=analysis_run_repository,
    )
    with client:
        project_id = create_project(client)
        created = client.post(
            f"/projects/{project_id}/analysis-runs",
            json={"synthetic_text": "Synthetic openai provenance."},
        )

    assert created.json()["provider"] == "openai"
    assert created.json()["model_id"] == B1_MODEL_ID
    assert created.json()["configuration_version"] == "B1/v1"


def test_claude_run_persists_provider_model_and_configuration_version(
    repositories: tuple[ProjectRepository, AnalysisRunRepository],
) -> None:
    project_repository, analysis_run_repository = repositories
    with claude_client(
        project_repository, analysis_run_repository, ClaudeFakeAdapter()
    ) as client:
        project_id = create_project(client)
        created = client.post(
            f"/projects/{project_id}/analysis-runs",
            json={"synthetic_text": "Synthetic claude provenance."},
        )
        reloaded = client.get(f"/projects/{project_id}/analysis-runs")

    assert created.status_code == 201
    body = created.json()
    assert body["provider"] == "anthropic"
    assert body["model_id"] == "claude-sonnet-5-5"
    assert body["configuration_version"] == "C1/v1"
    assert body["provider_response_id"] == "msg_fake_001"
    assert (body["input_tokens"], body["output_tokens"], body["total_tokens"]) == (
        5,
        6,
        11,
    )
    assert reloaded.json() == [body]


def test_claude_refusal_returns_the_same_safe_error(
    repositories: tuple[ProjectRepository, AnalysisRunRepository],
) -> None:
    project_repository, analysis_run_repository = repositories
    with claude_client(
        project_repository, analysis_run_repository, RefusingFakeAdapter()
    ) as client:
        project_id = create_project(client)
        response = client.post(
            f"/projects/{project_id}/analysis-runs",
            json={"synthetic_text": "Synthetic refusal case."},
        )
        persisted = client.get(f"/projects/{project_id}/analysis-runs")

    assert response.status_code == 503
    assert response.json() == {"detail": "Analysis service is temporarily unavailable"}
    assert "declined" not in response.text
    assert persisted.json() == []


@pytest.fixture
def clean_provider_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> pytest.MonkeyPatch:
    for name in ("MODEL_PROVIDER", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'env.db'}")
    return monkeypatch


def composed_adapter(service: object) -> object:
    assert isinstance(service, AnalysisRunService)
    return service._gateway._adapter  # noqa: SLF001 - composition assertion


def test_default_composition_is_openai(
    clean_provider_environment: pytest.MonkeyPatch,
) -> None:
    clean_provider_environment.setenv("OPENAI_API_KEY", "test-openai")

    assert isinstance(
        composed_adapter(analysis_run_service_from_environment()),
        OpenAIResponsesAdapter,
    )


def test_openai_selection_ignores_an_anthropic_key(
    clean_provider_environment: pytest.MonkeyPatch,
) -> None:
    clean_provider_environment.setenv("ANTHROPIC_API_KEY", "test-anthropic")

    assert isinstance(
        analysis_run_service_from_environment(), UnavailableAnalysisRunService
    )


def test_anthropic_selection_composes_the_claude_adapter(
    clean_provider_environment: pytest.MonkeyPatch,
) -> None:
    clean_provider_environment.setenv("MODEL_PROVIDER", "anthropic")
    clean_provider_environment.setenv("ANTHROPIC_API_KEY", "test-anthropic")

    assert isinstance(
        composed_adapter(analysis_run_service_from_environment()),
        AnthropicMessagesAdapter,
    )


def test_anthropic_selection_never_falls_back_to_openai(
    clean_provider_environment: pytest.MonkeyPatch,
) -> None:
    clean_provider_environment.setenv("MODEL_PROVIDER", "anthropic")
    clean_provider_environment.setenv("OPENAI_API_KEY", "test-openai")

    assert isinstance(
        analysis_run_service_from_environment(), UnavailableAnalysisRunService
    )


@pytest.mark.parametrize("provider", ["claude", "Anthropic", "openai,anthropic"])
def test_unknown_provider_selection_fails_closed(
    clean_provider_environment: pytest.MonkeyPatch, provider: str
) -> None:
    clean_provider_environment.setenv("MODEL_PROVIDER", provider)
    clean_provider_environment.setenv("OPENAI_API_KEY", "test-openai")
    clean_provider_environment.setenv("ANTHROPIC_API_KEY", "test-anthropic")

    assert isinstance(
        analysis_run_service_from_environment(), UnavailableAnalysisRunService
    )


def test_composition_without_a_database_is_unavailable(
    clean_provider_environment: pytest.MonkeyPatch,
) -> None:
    clean_provider_environment.delenv("DATABASE_URL")
    clean_provider_environment.setenv("MODEL_PROVIDER", "anthropic")
    clean_provider_environment.setenv("ANTHROPIC_API_KEY", "test-anthropic")

    assert isinstance(
        analysis_run_service_from_environment(), UnavailableAnalysisRunService
    )
