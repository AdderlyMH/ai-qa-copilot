from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import Base, Project, ProjectRecord
from ai_qa_copilot_api.quality_report_generation import (
    QualityReportGenerationService,
    UnavailableQualityReportGenerationService,
)
from ai_qa_copilot_api.quality_report_revisions import (
    SqlAlchemyQualityReportRevisionRepository,
    UnavailableQualityReportRevisionRepository,
)
from ai_qa_copilot_api.quality_report_snapshots import (
    QualityReportSnapshotInput,
    SnapshotExecutionEvidenceState,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-00000000e001")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-00000000e002")
REPORT_ID = UUID("00000000-0000-0000-0000-00000000e003")
NOW = datetime(2026, 9, 10, 22, 0, tzinfo=timezone.utc)


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


class FakeProjectRepository:
    def __init__(self) -> None:
        self._projects = {
            PROJECT_ID: Project(
                id=PROJECT_ID,
                name="Report project",
                description=None,
                created_at=NOW,
                archived_at=None,
            ),
            OTHER_PROJECT_ID: Project(
                id=OTHER_PROJECT_ID,
                name="Other project",
                description=None,
                created_at=NOW,
                archived_at=None,
            ),
        }

    def create(self, *, name: str, description: str | None) -> Project:
        del name, description
        raise AssertionError("Quality-report API tests do not create projects")

    def list_active(self) -> list[Project]:
        return list(self._projects.values())

    def get(self, project_id: UUID) -> Project | None:
        return self._projects.get(project_id)

    def archive(self, project_id: UUID) -> Project | None:
        del project_id
        raise AssertionError("Quality-report API tests do not archive projects")


class StaticEvidenceCollector:
    def __init__(self, collected: QualityReportSnapshotInput) -> None:
        self.collected = collected
        self.calls: list[UUID] = []

    def collect(
        self,
        *,
        project_id: UUID,
    ) -> QualityReportSnapshotInput:
        self.calls.append(project_id)
        return self.collected


def collected_input() -> QualityReportSnapshotInput:
    return QualityReportSnapshotInput(
        project_id=PROJECT_ID,
        source_document_version_ids=(),
        citations=(),
        requirement_analysis_runs=(),
        generated_test_cases=(),
        execution_evidence=(),
        failure_analyses=(),
        execution_evidence_state=SnapshotExecutionEvidenceState.NOT_RUN,
        created_at=NOW,
    )


def client(tmp_path: Path) -> tuple[TestClient, Engine, StaticEvidenceCollector]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'quality-reports.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)

    with sessions.begin() as session:
        session.add_all(
            (
                ProjectRecord(
                    id=PROJECT_ID,
                    name="Report project",
                    description=None,
                    created_at=NOW,
                    archived_at=None,
                ),
                ProjectRecord(
                    id=OTHER_PROJECT_ID,
                    name="Other project",
                    description=None,
                    created_at=NOW,
                    archived_at=None,
                ),
            )
        )

    collector = StaticEvidenceCollector(collected_input())
    revisions = SqlAlchemyQualityReportRevisionRepository(sessions)
    generation = QualityReportGenerationService(
        evidence_collector=collector,
        revision_repository=revisions,
        clock=lambda: NOW,
        id_factory=lambda: REPORT_ID,
    )
    app = create_app(
        local_bypass_settings(),
        project_repository=FakeProjectRepository(),
        quality_report_revision_repository=revisions,
        quality_report_generation_service=generation,
    )
    return TestClient(app), engine, collector


def test_owner_can_generate_list_and_read_an_immutable_quality_report(
    tmp_path: Path,
) -> None:
    api_client, engine, collector = client(tmp_path)
    reports_path = f"/projects/{PROJECT_ID}/quality-reports"

    try:
        with api_client as http:
            created = http.post(reports_path)
            listed = http.get(reports_path)
            fetched = http.get(f"{reports_path}/{REPORT_ID}")

        assert created.status_code == 201
        created_body = created.json()
        assert created_body["id"] == str(REPORT_ID)
        assert created_body["project_id"] == str(PROJECT_ID)
        assert created_body["snapshot"]["report"]["id"] == str(REPORT_ID)
        assert created_body["snapshot"]["report"]["project_id"] == str(PROJECT_ID)
        assert UUID(created.headers["X-Correlation-ID"])
        assert collector.calls == [PROJECT_ID]

        assert listed.status_code == 200
        assert listed.json() == [created_body]
        assert UUID(listed.headers["X-Correlation-ID"])

        assert fetched.status_code == 200
        assert fetched.json() == created_body
        assert UUID(fetched.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_quality_report_route_does_not_leak_revisions_across_projects(
    tmp_path: Path,
) -> None:
    api_client, engine, _ = client(tmp_path)
    reports_path = f"/projects/{PROJECT_ID}/quality-reports"

    try:
        with api_client as http:
            created = http.post(reports_path)
            foreign = http.get(
                f"/projects/{OTHER_PROJECT_ID}/quality-reports/{REPORT_ID}"
            )

        assert created.status_code == 201
        assert foreign.status_code == 404
        assert foreign.json() == {"detail": "Quality report revision not found"}
        assert UUID(foreign.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_quality_report_routes_fail_closed_without_durable_configuration() -> None:
    app = create_app(
        local_bypass_settings(),
        project_repository=FakeProjectRepository(),
        quality_report_revision_repository=UnavailableQualityReportRevisionRepository(),
        quality_report_generation_service=UnavailableQualityReportGenerationService(),
    )
    reports_path = f"/projects/{PROJECT_ID}/quality-reports"

    with TestClient(app) as http:
        generated = http.post(reports_path)
        listed = http.get(reports_path)

    expected = {"detail": "Quality report service is temporarily unavailable"}
    assert generated.status_code == 503
    assert generated.json() == expected
    assert UUID(generated.headers["X-Correlation-ID"])
    assert listed.status_code == 503
    assert listed.json() == expected
    assert UUID(listed.headers["X-Correlation-ID"])
