from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from ai_qa_copilot_api.auth import (
    AppEnvironment,
    AuthSettings,
    CognitoIdentity,
    CognitoSettings,
)
from ai_qa_copilot_api.findings import (
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    RequirementFindingV1,
)
from ai_qa_copilot_api.finding_feedback import (
    FindingFeedback,
    FindingFeedbackAction,
    FindingFeedbackUnavailable,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import Project
from ai_qa_copilot_api.requirements_analysis import (
    ANALYZER_VERSION,
    RequirementAnalysisRun,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000501")
RUN_ID = UUID("00000000-0000-0000-0000-000000000502")
FINDING_ID = UUID("00000000-0000-0000-0000-000000000503")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000504")
ISSUER = "https://cognito-idp.example.com/us-east-1_example"
CLIENT_ID = "example-client"
OWNER_SUBJECT = "owner-subject"
FEEDBACK_PATH = (
    f"/projects/{PROJECT_ID}/requirement-analysis-runs/{RUN_ID}/findings/"
    f"{FINDING_ID}/feedback"
)


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


def finding() -> RequirementFindingV1:
    return RequirementFindingV1(
        id=FINDING_ID,
        category=FindingCategory.AMBIGUITY,
        severity=FindingSeverity.MEDIUM,
        evidence=(
            FindingEvidence(
                citation_id=CITATION_ID,
                observed_fact="The requirement says the response must be fast.",
            ),
        ),
        analysis="Fast is not measurable.",
        confidence=1.0,
        recommendation="Specify a response-time threshold.",
        unsupported=False,
        unsupported_reason=None,
    )


def analysis_run() -> RequirementAnalysisRun:
    return RequirementAnalysisRun(
        id=RUN_ID,
        project_id=PROJECT_ID,
        analyzer_version=ANALYZER_VERSION,
        citation_ids=(CITATION_ID,),
        findings=(finding(),),
        created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )


class FakeProjectRepository:
    def __init__(self) -> None:
        self.project = Project(
            id=PROJECT_ID,
            name="Feedback project",
            description=None,
            created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
            archived_at=None,
        )

    def create(self, *, name: str, description: str | None) -> Project:
        del name, description
        raise AssertionError("ANA-005 must not create projects")

    def list_active(self) -> list[Project]:
        return [self.project]

    def get(self, project_id: UUID) -> Project | None:
        return self.project if project_id == PROJECT_ID else None

    def archive(self, project_id: UUID) -> Project | None:
        del project_id
        raise AssertionError("ANA-005 must not archive projects")


class FakeRequirementAnalysisRepository:
    def create(
        self,
        *,
        project_id: UUID,
        citation_ids: tuple[UUID, ...],
        findings: tuple[RequirementFindingV1, ...],
    ) -> RequirementAnalysisRun:
        del project_id, citation_ids, findings
        raise AssertionError("ANA-005 must not create analysis runs")

    def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RequirementAnalysisRun | None:
        return analysis_run() if project_id == PROJECT_ID and run_id == RUN_ID else None


class FakeFindingFeedbackRepository:
    def __init__(self) -> None:
        self.events: list[FindingFeedback] = []

    def create(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
        citation_ids: tuple[UUID, ...],
        action: FindingFeedbackAction,
        annotation: str | None,
        reviewer_id: str,
        reviewer_authentication_source: str,
    ) -> FindingFeedback:
        event = FindingFeedback(
            id=UUID(int=len(self.events) + 1),
            project_id=project_id,
            requirement_analysis_run_id=requirement_analysis_run_id,
            requirement_finding_id=requirement_finding_id,
            citation_ids=citation_ids,
            action=action,
            annotation=annotation,
            reviewer_id=reviewer_id,
            reviewer_authentication_source=reviewer_authentication_source,
            created_at=datetime(2026, 9, 4, 12, len(self.events), tzinfo=timezone.utc),
        )
        self.events.append(event)
        return event

    def list_for_finding(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
    ) -> tuple[FindingFeedback, ...]:
        return tuple(
            event
            for event in self.events
            if (
                event.project_id == project_id
                and event.requirement_analysis_run_id == requirement_analysis_run_id
                and event.requirement_finding_id == requirement_finding_id
            )
        )


class UnavailableFindingFeedbackRepository:
    def create(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
        citation_ids: tuple[UUID, ...],
        action: FindingFeedbackAction,
        annotation: str | None,
        reviewer_id: str,
        reviewer_authentication_source: str,
    ) -> FindingFeedback:
        del (
            project_id,
            requirement_analysis_run_id,
            requirement_finding_id,
            citation_ids,
            action,
            annotation,
            reviewer_id,
            reviewer_authentication_source,
        )
        raise FindingFeedbackUnavailable

    def list_for_finding(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
    ) -> tuple[FindingFeedback, ...]:
        del project_id, requirement_analysis_run_id, requirement_finding_id
        raise FindingFeedbackUnavailable


class StaticTokenValidator:
    def __init__(self, identity: CognitoIdentity) -> None:
        self._identity = identity

    def validate(self, token: str) -> CognitoIdentity:
        del token
        return self._identity


def client(
    *,
    auth_settings: AuthSettings | None = None,
    token_validator: StaticTokenValidator | None = None,
    feedback_repository: FakeFindingFeedbackRepository
    | UnavailableFindingFeedbackRepository
    | None = None,
) -> tuple[TestClient, FakeFindingFeedbackRepository]:
    repository = (
        feedback_repository
        if feedback_repository is not None
        else FakeFindingFeedbackRepository()
    )
    app = create_app(
        auth_settings or local_bypass_settings(),
        token_validator=token_validator,
        project_repository=FakeProjectRepository(),
        requirement_analysis_repository=FakeRequirementAnalysisRepository(),
        finding_feedback_repository=repository,
    )
    if not isinstance(repository, FakeFindingFeedbackRepository):
        return TestClient(app), FakeFindingFeedbackRepository()
    return TestClient(app), repository


def test_owner_can_create_and_list_immutable_feedback_with_provenance() -> None:
    api_client, repository = client()

    with api_client as http:
        accepted = http.post(
            FEEDBACK_PATH,
            json={"action": "accept", "annotation": None},
        )
        annotated = http.post(
            FEEDBACK_PATH,
            json={
                "action": "annotate",
                "annotation": "Need an observable latency target.",
            },
        )
        history = http.get(FEEDBACK_PATH)

    assert accepted.status_code == 201
    assert accepted.json()["project_id"] == str(PROJECT_ID)
    assert accepted.json()["requirement_analysis_run_id"] == str(RUN_ID)
    assert accepted.json()["requirement_finding_id"] == str(FINDING_ID)
    assert accepted.json()["citation_ids"] == [str(CITATION_ID)]
    assert accepted.json()["reviewer_id"] == "local-development-owner"
    assert accepted.json()["reviewer_authentication_source"] == "local_bypass"
    assert UUID(accepted.headers["X-Correlation-ID"])

    assert annotated.status_code == 201
    assert annotated.json()["annotation"] == "Need an observable latency target."

    assert history.status_code == 200
    assert [event["action"] for event in history.json()] == ["accept", "annotate"]
    assert len(repository.events) == 2


def test_invalid_or_client_supplied_provenance_is_rejected_without_side_effects() -> (
    None
):
    api_client, repository = client()

    with api_client as http:
        blank_annotation = http.post(
            FEEDBACK_PATH,
            json={"action": "annotate", "annotation": "   "},
        )
        supplied_reviewer = http.post(
            FEEDBACK_PATH,
            json={
                "action": "accept",
                "annotation": None,
                "reviewer_id": "attacker-controlled",
            },
        )

    assert blank_annotation.status_code == 400
    assert supplied_reviewer.status_code == 422
    assert repository.events == []


def test_missing_run_or_finding_returns_the_same_safe_not_found_response() -> None:
    api_client, _ = client()
    missing_run_path = FEEDBACK_PATH.replace(str(RUN_ID), str(UUID(int=999)))
    missing_finding_path = FEEDBACK_PATH.replace(
        str(FINDING_ID),
        str(UUID(int=998)),
    )

    with api_client as http:
        missing_run = http.post(
            missing_run_path,
            json={"action": "accept", "annotation": None},
        )
        missing_finding = http.get(missing_finding_path)

    assert missing_run.status_code == 404
    assert missing_run.json() == {"detail": "Finding not found"}
    assert missing_finding.status_code == 404
    assert missing_finding.json() == {"detail": "Finding not found"}


def test_feedback_persistence_unavailability_returns_503() -> None:
    api_client, _ = client(
        feedback_repository=UnavailableFindingFeedbackRepository(),
    )

    with api_client as http:
        response = http.post(
            FEEDBACK_PATH,
            json={"action": "accept", "annotation": None},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Finding feedback service is temporarily unavailable"
    }
    assert UUID(response.headers["X-Correlation-ID"])


def test_feedback_create_requires_owner_authentication() -> None:
    api_client, _ = client(
        auth_settings=AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=None,
        )
    )

    with api_client as http:
        response = http.post(
            FEEDBACK_PATH,
            json={"action": "accept", "annotation": None},
        )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_feedback_create_rejects_a_valid_non_owner_identity() -> None:
    api_client, _ = client(
        auth_settings=AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=CognitoSettings(
                issuer=ISSUER,
                client_id=CLIENT_ID,
                owner_subject=OWNER_SUBJECT,
            ),
        ),
        token_validator=StaticTokenValidator(
            CognitoIdentity(
                issuer=ISSUER,
                subject="non-owner-subject",
            )
        ),
    )

    with api_client as http:
        response = http.post(
            FEEDBACK_PATH,
            json={"action": "accept", "annotation": None},
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Owner access required"}
