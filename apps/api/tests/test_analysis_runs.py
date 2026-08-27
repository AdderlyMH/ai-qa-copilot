from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
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
)
from ai_qa_copilot_api.audit import AuthorizationAuditEvent, AuthorizationAuditSink
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.model_gateway import (
    B1_MODEL_ID,
    ModelGateway,
    ModelGatewayTimeout,
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
