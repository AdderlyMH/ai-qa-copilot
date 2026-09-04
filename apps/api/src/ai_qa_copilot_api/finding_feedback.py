"""Immutable owner feedback for persisted requirement-analysis findings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import os
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.auth import (
    CognitoOwnerPrincipal,
    LocalDevelopmentOwnerPrincipal,
    OwnerPrincipal,
)
from ai_qa_copilot_api.documents import FindingFeedbackRecord
from ai_qa_copilot_api.requirements_analysis import (
    RequirementAnalysisRepository,
    RequirementAnalysisRun,
    RequirementAnalysisUnavailable,
)
from ai_qa_copilot_api.findings import RequirementFindingV1


MAX_FINDING_FEEDBACK_ANNOTATION_LENGTH = 4_000
LOCAL_DEVELOPMENT_REVIEWER_ID = "local-development-owner"


class FindingFeedbackAction(StrEnum):
    """Closed set of immutable reviewer actions."""

    ACCEPT = "accept"
    REJECT = "reject"
    ANNOTATE = "annotate"


class FindingFeedbackUnavailable(RuntimeError):
    """Raised when durable finding-feedback state is unavailable."""


class FindingFeedbackNotFound(ValueError):
    """Raised when a project-scoped run or finding does not exist."""


class FindingFeedbackValidationError(ValueError):
    """Raised when an immutable feedback event violates its contract."""


@dataclass(frozen=True)
class FindingFeedback:
    """One immutable owner decision or annotation for one persisted finding."""

    id: UUID
    project_id: UUID
    requirement_analysis_run_id: UUID
    requirement_finding_id: UUID
    citation_ids: tuple[UUID, ...]
    action: FindingFeedbackAction
    annotation: str | None
    reviewer_id: str
    reviewer_authentication_source: str
    created_at: datetime


class FindingFeedbackRepository(Protocol):
    """Persistence boundary for immutable project-scoped feedback events."""

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
    ) -> FindingFeedback: ...

    def list_for_finding(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
    ) -> tuple[FindingFeedback, ...]: ...


class UnavailableFindingFeedbackRepository:
    """Fail closed until a durable database is configured."""

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
        raise FindingFeedbackUnavailable

    def list_for_finding(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
    ) -> tuple[FindingFeedback, ...]:
        raise FindingFeedbackUnavailable


class SqlAlchemyFindingFeedbackRepository:
    """Persist and load immutable feedback without mutable review state."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_database_url(
        cls, database_url: str
    ) -> SqlAlchemyFindingFeedbackRepository:
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

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
        record = FindingFeedbackRecord(
            id=self._id_factory(),
            project_id=project_id,
            requirement_analysis_run_id=requirement_analysis_run_id,
            requirement_finding_id=requirement_finding_id,
            citation_ids=[str(citation_id) for citation_id in citation_ids],
            action=action.value,
            annotation=annotation,
            reviewer_id=reviewer_id,
            reviewer_authentication_source=reviewer_authentication_source,
            created_at=self._clock(),
        )

        try:
            with self._session_factory.begin() as session:
                session.add(record)
        except SQLAlchemyError as error:
            raise FindingFeedbackUnavailable from error

        return _feedback_from_record(record)

    def list_for_finding(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
    ) -> tuple[FindingFeedback, ...]:
        try:
            with self._session_factory() as session:
                records = tuple(
                    session.execute(
                        select(FindingFeedbackRecord)
                        .where(
                            FindingFeedbackRecord.project_id == project_id,
                            FindingFeedbackRecord.requirement_analysis_run_id
                            == requirement_analysis_run_id,
                            FindingFeedbackRecord.requirement_finding_id
                            == requirement_finding_id,
                        )
                        .order_by(
                            FindingFeedbackRecord.created_at.asc(),
                            FindingFeedbackRecord.id.asc(),
                        )
                    ).scalars()
                )
        except SQLAlchemyError as error:
            raise FindingFeedbackUnavailable from error

        try:
            return tuple(_feedback_from_record(record) for record in records)
        except (TypeError, ValueError) as error:
            raise FindingFeedbackUnavailable from error


class FindingFeedbackService:
    """Authorize provenance through an immutable ANA-003 run before feedback."""

    def __init__(
        self,
        *,
        requirement_analysis_repository: RequirementAnalysisRepository,
        repository: FindingFeedbackRepository,
    ) -> None:
        self._requirement_analysis_repository = requirement_analysis_repository
        self._repository = repository

    def record(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
        action: FindingFeedbackAction,
        annotation: str | None,
        reviewer: OwnerPrincipal,
    ) -> FindingFeedback:
        normalized_annotation = _validate_annotation(action, annotation)
        finding = self._finding_for_project_run(
            project_id=project_id,
            requirement_analysis_run_id=requirement_analysis_run_id,
            requirement_finding_id=requirement_finding_id,
        )
        citation_ids = tuple(evidence.citation_id for evidence in finding.evidence)
        if not citation_ids:
            raise FindingFeedbackNotFound("Finding has no cited provenance")

        reviewer_id, reviewer_source = reviewer_provenance(reviewer)
        return self._repository.create(
            project_id=project_id,
            requirement_analysis_run_id=requirement_analysis_run_id,
            requirement_finding_id=requirement_finding_id,
            citation_ids=citation_ids,
            action=action,
            annotation=normalized_annotation,
            reviewer_id=reviewer_id,
            reviewer_authentication_source=reviewer_source,
        )

    def list_for_finding(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
    ) -> tuple[FindingFeedback, ...]:
        self._finding_for_project_run(
            project_id=project_id,
            requirement_analysis_run_id=requirement_analysis_run_id,
            requirement_finding_id=requirement_finding_id,
        )
        return self._repository.list_for_finding(
            project_id=project_id,
            requirement_analysis_run_id=requirement_analysis_run_id,
            requirement_finding_id=requirement_finding_id,
        )

    def _finding_for_project_run(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
        requirement_finding_id: UUID,
    ) -> RequirementFindingV1:
        run = self._run_for_project(
            project_id=project_id,
            requirement_analysis_run_id=requirement_analysis_run_id,
        )
        for finding in run.findings:
            if finding.id == requirement_finding_id:
                return finding
        raise FindingFeedbackNotFound("Finding not found")

    def _run_for_project(
        self,
        *,
        project_id: UUID,
        requirement_analysis_run_id: UUID,
    ) -> RequirementAnalysisRun:
        try:
            run = self._requirement_analysis_repository.get_for_project(
                project_id=project_id,
                run_id=requirement_analysis_run_id,
            )
        except RequirementAnalysisUnavailable as error:
            raise FindingFeedbackUnavailable from error

        if run is None:
            raise FindingFeedbackNotFound("Finding not found")
        return run


def finding_feedback_repository_from_environment() -> FindingFeedbackRepository:
    """Build durable feedback persistence only with an explicit database URL."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableFindingFeedbackRepository()
    return SqlAlchemyFindingFeedbackRepository.from_database_url(database_url)


def reviewer_provenance(reviewer: OwnerPrincipal) -> tuple[str, str]:
    """Render only trusted server-resolved owner identity into durable feedback."""

    if isinstance(reviewer, CognitoOwnerPrincipal):
        return (
            f"{reviewer.issuer}|{reviewer.subject}",
            reviewer.authentication_source,
        )
    if isinstance(reviewer, LocalDevelopmentOwnerPrincipal):
        return (
            LOCAL_DEVELOPMENT_REVIEWER_ID,
            reviewer.authentication_source,
        )
    raise FindingFeedbackValidationError("Unsupported reviewer principal")


def _validate_annotation(
    action: FindingFeedbackAction,
    annotation: str | None,
) -> str | None:
    if annotation is None:
        if action is FindingFeedbackAction.ANNOTATE:
            raise FindingFeedbackValidationError(
                "Annotate feedback requires a non-empty annotation"
            )
        return None

    normalized = annotation.strip()
    if not normalized or len(normalized) > MAX_FINDING_FEEDBACK_ANNOTATION_LENGTH:
        raise FindingFeedbackValidationError(
            "Feedback annotation must be bounded, non-empty text"
        )
    if action is not FindingFeedbackAction.ANNOTATE:
        raise FindingFeedbackValidationError(
            "Only annotate feedback may include an annotation"
        )
    return normalized


def _feedback_from_record(record: FindingFeedbackRecord) -> FindingFeedback:
    return FindingFeedback(
        id=record.id,
        project_id=record.project_id,
        requirement_analysis_run_id=record.requirement_analysis_run_id,
        requirement_finding_id=record.requirement_finding_id,
        citation_ids=tuple(UUID(value) for value in record.citation_ids),
        action=FindingFeedbackAction(record.action),
        annotation=record.annotation,
        reviewer_id=record.reviewer_id,
        reviewer_authentication_source=record.reviewer_authentication_source,
        created_at=_utc_datetime(record.created_at),
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
