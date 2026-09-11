"""Deterministic orchestration for new immutable QA-report revisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from ai_qa_copilot_api.quality_report_revisions import (
    QualityReportRevisionRejected,
    QualityReportRevisionRepository,
    QualityReportRevisionUnavailable,
    StoredQualityReportRevision,
)
from ai_qa_copilot_api.quality_report_snapshots import (
    QualityReportSnapshotInput,
    QualityReportSnapshotRejected,
    build_quality_report_snapshot,
)


class QualityReportEvidenceCollectionUnavailable(RuntimeError):
    """Raised when durable report evidence cannot be collected safely."""


class QualityReportGenerationRejected(ValueError):
    """Raised when proposed report evidence violates the immutable contract."""


class QualityReportGenerationUnavailable(RuntimeError):
    """Raised when report generation cannot safely access durable state."""


class QualityReportEvidenceCollector(Protocol):
    """Collect one complete, project-scoped input for immutable report assembly."""

    def collect(
        self,
        *,
        project_id: UUID,
    ) -> QualityReportSnapshotInput: ...


class UnavailableQualityReportEvidenceCollector:
    """Fail closed until durable report-evidence collection is configured."""

    def collect(
        self,
        *,
        project_id: UUID,
    ) -> QualityReportSnapshotInput:
        del project_id
        raise QualityReportEvidenceCollectionUnavailable


class UnavailableQualityReportGenerationService:
    """Fail closed until report generation has durable evidence and storage."""

    def generate(
        self,
        *,
        project_id: UUID,
    ) -> StoredQualityReportRevision:
        del project_id
        raise QualityReportGenerationUnavailable


class QualityReportGenerationService:
    """Build and persist a newly timestamped immutable report revision."""

    def __init__(
        self,
        *,
        evidence_collector: QualityReportEvidenceCollector,
        revision_repository: QualityReportRevisionRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._evidence_collector = evidence_collector
        self._revision_repository = revision_repository
        self._clock = clock
        self._id_factory = id_factory

    def generate(
        self,
        *,
        project_id: UUID,
    ) -> StoredQualityReportRevision:
        """Collect owned evidence and persist a distinct immutable revision."""

        if not isinstance(project_id, UUID):
            raise QualityReportGenerationRejected(
                "Quality report project id must be a UUID"
            )

        try:
            collected = self._evidence_collector.collect(project_id=project_id)
        except QualityReportEvidenceCollectionUnavailable as error:
            raise QualityReportGenerationUnavailable from error

        if not isinstance(collected, QualityReportSnapshotInput):
            raise QualityReportGenerationRejected(
                "Quality report evidence collector returned malformed input"
            )
        if collected.project_id != project_id:
            raise QualityReportGenerationRejected(
                "Quality report evidence does not belong to the supplied project"
            )

        snapshot_input = replace(
            collected,
            created_at=_generation_time(self._clock()),
        )

        try:
            snapshot = build_quality_report_snapshot(
                snapshot_input=snapshot_input,
                id_factory=self._id_factory,
            )
        except QualityReportSnapshotRejected as error:
            raise QualityReportGenerationRejected(
                "Quality report evidence violates the immutable snapshot contract"
            ) from error

        try:
            return self._revision_repository.create(
                project_id=project_id,
                snapshot=snapshot,
            )
        except QualityReportRevisionRejected as error:
            raise QualityReportGenerationRejected(
                "Quality report revision violates the immutable persistence contract"
            ) from error
        except QualityReportRevisionUnavailable as error:
            raise QualityReportGenerationUnavailable from error


def _generation_time(value: datetime) -> datetime:
    """Require a trustworthy, timezone-aware revision timestamp."""

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise QualityReportGenerationRejected(
            "Quality report generation time must be timezone-aware"
        )
    return value.astimezone(timezone.utc)
