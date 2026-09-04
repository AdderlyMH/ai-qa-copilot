from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from ai_qa_copilot_api.auth import (
    CognitoOwnerPrincipal,
    LocalDevelopmentOwnerPrincipal,
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
    FindingFeedbackNotFound,
    FindingFeedbackService,
    FindingFeedbackUnavailable,
    FindingFeedbackValidationError,
    reviewer_provenance,
)
from ai_qa_copilot_api.requirements_analysis import (
    ANALYZER_VERSION,
    RequirementAnalysisRun,
    RequirementAnalysisUnavailable,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000401")
RUN_ID = UUID("00000000-0000-0000-0000-000000000402")
FINDING_ID = UUID("00000000-0000-0000-0000-000000000403")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000404")


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
        analysis="Fast is not a measurable response-time target.",
        confidence=1.0,
        recommendation="Specify a percentile and response-time limit.",
        unsupported=False,
        unsupported_reason=None,
    )


def analysis_run(
    *,
    project_id: UUID = PROJECT_ID,
    run_id: UUID = RUN_ID,
    findings: tuple[RequirementFindingV1, ...] = (finding(),),
) -> RequirementAnalysisRun:
    return RequirementAnalysisRun(
        id=run_id,
        project_id=project_id,
        analyzer_version=ANALYZER_VERSION,
        citation_ids=(CITATION_ID,),
        findings=findings,
        created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )


class FakeRequirementAnalysisRepository:
    def __init__(self, runs: tuple[RequirementAnalysisRun, ...]) -> None:
        self._runs = {(run.project_id, run.id): run for run in runs}

    def create(
        self,
        *,
        project_id: UUID,
        citation_ids: tuple[UUID, ...],
        findings: tuple[RequirementFindingV1, ...],
    ) -> RequirementAnalysisRun:
        raise AssertionError("ANA-005 must not create analysis runs")

    def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RequirementAnalysisRun | None:
        return self._runs.get((project_id, run_id))


class UnavailableRequirementAnalysisRepository:
    def create(
        self,
        *,
        project_id: UUID,
        citation_ids: tuple[UUID, ...],
        findings: tuple[RequirementFindingV1, ...],
    ) -> RequirementAnalysisRun:
        raise RequirementAnalysisUnavailable

    def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RequirementAnalysisRun | None:
        raise RequirementAnalysisUnavailable


class FakeFindingFeedbackRepository:
    def __init__(self) -> None:
        self.created: list[FindingFeedback] = []

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
        feedback = FindingFeedback(
            id=UUID(int=len(self.created) + 1),
            project_id=project_id,
            requirement_analysis_run_id=requirement_analysis_run_id,
            requirement_finding_id=requirement_finding_id,
            citation_ids=citation_ids,
            action=action,
            annotation=annotation,
            reviewer_id=reviewer_id,
            reviewer_authentication_source=reviewer_authentication_source,
            created_at=datetime(2026, 9, 4, tzinfo=timezone.utc)
            + timedelta(seconds=len(self.created)),
        )
        self.created.append(feedback)
        return feedback

    def list_for_finding(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
    ) -> tuple[FindingFeedback, ...]:
        return tuple(
            feedback
            for feedback in self.created
            if (
                feedback.project_id == project_id
                and feedback.requirement_analysis_run_id == requirement_analysis_run_id
                and feedback.requirement_finding_id == requirement_finding_id
            )
        )


def service(
    *,
    runs: tuple[RequirementAnalysisRun, ...] = (analysis_run(),),
    feedback_repository: FakeFindingFeedbackRepository | None = None,
) -> tuple[FindingFeedbackService, FakeFindingFeedbackRepository]:
    repository = feedback_repository or FakeFindingFeedbackRepository()
    return (
        FindingFeedbackService(
            requirement_analysis_repository=FakeRequirementAnalysisRepository(runs),
            repository=repository,
        ),
        repository,
    )


def test_accept_reject_and_annotate_events_retain_full_provenance() -> None:
    feedback_service, repository = service()
    reviewer = LocalDevelopmentOwnerPrincipal()

    accepted = feedback_service.record(
        project_id=PROJECT_ID,
        requirement_analysis_run_id=RUN_ID,
        requirement_finding_id=FINDING_ID,
        action=FindingFeedbackAction.ACCEPT,
        annotation=None,
        reviewer=reviewer,
    )
    rejected = feedback_service.record(
        project_id=PROJECT_ID,
        requirement_analysis_run_id=RUN_ID,
        requirement_finding_id=FINDING_ID,
        action=FindingFeedbackAction.REJECT,
        annotation=None,
        reviewer=reviewer,
    )
    annotated = feedback_service.record(
        project_id=PROJECT_ID,
        requirement_analysis_run_id=RUN_ID,
        requirement_finding_id=FINDING_ID,
        action=FindingFeedbackAction.ANNOTATE,
        annotation="Needs a concrete 95th-percentile threshold.",
        reviewer=reviewer,
    )

    assert [feedback.action for feedback in repository.created] == [
        FindingFeedbackAction.ACCEPT,
        FindingFeedbackAction.REJECT,
        FindingFeedbackAction.ANNOTATE,
    ]
    assert annotated.annotation == "Needs a concrete 95th-percentile threshold."
    assert all(feedback.project_id == PROJECT_ID for feedback in repository.created)
    assert all(
        feedback.requirement_analysis_run_id == RUN_ID
        for feedback in repository.created
    )
    assert all(
        feedback.requirement_finding_id == FINDING_ID for feedback in repository.created
    )
    assert all(
        feedback.citation_ids == (CITATION_ID,) for feedback in repository.created
    )
    assert accepted.reviewer_id == "local-development-owner"
    assert rejected.reviewer_authentication_source == "local_bypass"


def test_annotation_contract_rejects_blank_or_wrong_action_notes() -> None:
    feedback_service, _ = service()
    reviewer = LocalDevelopmentOwnerPrincipal()

    with pytest.raises(
        FindingFeedbackValidationError,
        match="requires a non-empty annotation",
    ):
        feedback_service.record(
            project_id=PROJECT_ID,
            requirement_analysis_run_id=RUN_ID,
            requirement_finding_id=FINDING_ID,
            action=FindingFeedbackAction.ANNOTATE,
            annotation=None,
            reviewer=reviewer,
        )

    with pytest.raises(
        FindingFeedbackValidationError,
        match="bounded, non-empty text",
    ):
        feedback_service.record(
            project_id=PROJECT_ID,
            requirement_analysis_run_id=RUN_ID,
            requirement_finding_id=FINDING_ID,
            action=FindingFeedbackAction.ANNOTATE,
            annotation="   ",
            reviewer=reviewer,
        )

    with pytest.raises(
        FindingFeedbackValidationError,
        match="Only annotate feedback",
    ):
        feedback_service.record(
            project_id=PROJECT_ID,
            requirement_analysis_run_id=RUN_ID,
            requirement_finding_id=FINDING_ID,
            action=FindingFeedbackAction.ACCEPT,
            annotation="A client must not add a note to accept.",
            reviewer=reviewer,
        )


def test_feedback_history_is_append_only_and_stably_ordered() -> None:
    feedback_service, _ = service()
    reviewer = LocalDevelopmentOwnerPrincipal()

    for action, annotation in (
        (FindingFeedbackAction.ACCEPT, None),
        (FindingFeedbackAction.REJECT, None),
        (FindingFeedbackAction.ANNOTATE, "Retain this as a review note."),
    ):
        feedback_service.record(
            project_id=PROJECT_ID,
            requirement_analysis_run_id=RUN_ID,
            requirement_finding_id=FINDING_ID,
            action=action,
            annotation=annotation,
            reviewer=reviewer,
        )

    history = feedback_service.list_for_finding(
        project_id=PROJECT_ID,
        requirement_analysis_run_id=RUN_ID,
        requirement_finding_id=FINDING_ID,
    )

    assert [feedback.action for feedback in history] == [
        FindingFeedbackAction.ACCEPT,
        FindingFeedbackAction.REJECT,
        FindingFeedbackAction.ANNOTATE,
    ]
    assert len(history) == 3


def test_missing_or_foreign_run_or_finding_is_not_reviewable() -> None:
    foreign_run = replace(
        analysis_run(),
        project_id=UUID("00000000-0000-0000-0000-000000000499"),
    )
    feedback_service, _ = service(runs=(foreign_run,))
    reviewer = LocalDevelopmentOwnerPrincipal()

    with pytest.raises(FindingFeedbackNotFound, match="Finding not found"):
        feedback_service.record(
            project_id=PROJECT_ID,
            requirement_analysis_run_id=RUN_ID,
            requirement_finding_id=FINDING_ID,
            action=FindingFeedbackAction.ACCEPT,
            annotation=None,
            reviewer=reviewer,
        )

    with pytest.raises(FindingFeedbackNotFound, match="Finding not found"):
        feedback_service.record(
            project_id=foreign_run.project_id,
            requirement_analysis_run_id=foreign_run.id,
            requirement_finding_id=UUID("00000000-0000-0000-0000-000000000498"),
            action=FindingFeedbackAction.ACCEPT,
            annotation=None,
            reviewer=reviewer,
        )


def test_unavailable_requirement_analysis_state_fails_closed() -> None:
    feedback_service = FindingFeedbackService(
        requirement_analysis_repository=UnavailableRequirementAnalysisRepository(),
        repository=FakeFindingFeedbackRepository(),
    )

    with pytest.raises(FindingFeedbackUnavailable):
        feedback_service.record(
            project_id=PROJECT_ID,
            requirement_analysis_run_id=RUN_ID,
            requirement_finding_id=FINDING_ID,
            action=FindingFeedbackAction.ACCEPT,
            annotation=None,
            reviewer=LocalDevelopmentOwnerPrincipal(),
        )


def test_cognito_reviewer_identity_is_server_derived() -> None:
    reviewer_id, source = reviewer_provenance(
        CognitoOwnerPrincipal(
            issuer="https://cognito-idp.example.com/example",
            subject="owner-subject",
        )
    )

    assert reviewer_id == "https://cognito-idp.example.com/example|owner-subject"
    assert source == "cognito"
