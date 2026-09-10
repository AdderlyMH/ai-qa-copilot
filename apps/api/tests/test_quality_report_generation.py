from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import pytest

from ai_qa_copilot_api.quality_report_generation import (
    QualityReportEvidenceCollectionUnavailable,
    QualityReportGenerationRejected,
    QualityReportGenerationService,
    QualityReportGenerationUnavailable,
)
from ai_qa_copilot_api.quality_report_revisions import (
    StoredQualityReportRevision,
)
from ai_qa_copilot_api.quality_report_snapshots import (
    QualityReportEvidenceSnapshot,
    QualityReportSnapshotInput,
    SnapshotExecutionEvidenceState,
)
from ai_qa_copilot_api.quality_reports import QUALITY_REPORT_SCHEMA_VERSION


PROJECT_ID = UUID("00000000-0000-0000-0000-00000000c001")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-00000000c002")
FIRST_REPORT_ID = UUID("00000000-0000-0000-0000-00000000c003")
SECOND_REPORT_ID = UUID("00000000-0000-0000-0000-00000000c004")

COLLECTED_AT = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)
FIRST_GENERATED_AT = datetime(2026, 9, 10, 20, 1, tzinfo=timezone.utc)
SECOND_GENERATED_AT = datetime(2026, 9, 10, 20, 2, tzinfo=timezone.utc)


def snapshot_input(*, project_id: UUID = PROJECT_ID) -> QualityReportSnapshotInput:
    return QualityReportSnapshotInput(
        project_id=project_id,
        source_document_version_ids=(),
        citations=(),
        requirement_analysis_runs=(),
        generated_test_cases=(),
        execution_evidence=(),
        failure_analyses=(),
        execution_evidence_state=SnapshotExecutionEvidenceState.NOT_RUN,
        created_at=COLLECTED_AT,
    )


@dataclass
class StaticEvidenceCollector:
    collected: QualityReportSnapshotInput
    calls: list[UUID] = field(default_factory=list)

    def collect(
        self,
        *,
        project_id: UUID,
    ) -> QualityReportSnapshotInput:
        self.calls.append(project_id)
        return self.collected


@dataclass
class RecordingRevisionRepository:
    created: list[QualityReportEvidenceSnapshot] = field(default_factory=list)

    def create(
        self,
        *,
        project_id: UUID,
        snapshot: QualityReportEvidenceSnapshot,
    ) -> StoredQualityReportRevision:
        assert project_id == snapshot.report.project_id
        self.created.append(snapshot)
        return StoredQualityReportRevision(
            id=snapshot.report.id,
            project_id=project_id,
            schema_version=QUALITY_REPORT_SCHEMA_VERSION,
            snapshot=snapshot,
            report_sha256=snapshot.report.content_sha256(),
            snapshot_sha256=snapshot.content_sha256(),
            created_at=snapshot.report.created_at,
        )

    def get(
        self,
        *,
        project_id: UUID,
        revision_id: UUID,
    ) -> StoredQualityReportRevision | None:
        del project_id, revision_id
        return None

    def list_for_project(
        self,
        *,
        project_id: UUID,
    ) -> tuple[StoredQualityReportRevision, ...]:
        del project_id
        return ()


class UnavailableEvidenceCollector:
    def collect(
        self,
        *,
        project_id: UUID,
    ) -> QualityReportSnapshotInput:
        del project_id
        raise QualityReportEvidenceCollectionUnavailable


def test_generation_retimestamps_and_persists_collected_project_evidence() -> None:
    collector = StaticEvidenceCollector(snapshot_input())
    repository = RecordingRevisionRepository()
    service = QualityReportGenerationService(
        evidence_collector=collector,
        revision_repository=repository,
        clock=lambda: FIRST_GENERATED_AT,
        id_factory=lambda: FIRST_REPORT_ID,
    )

    stored = service.generate(project_id=PROJECT_ID)

    assert collector.calls == [PROJECT_ID]
    assert len(repository.created) == 1
    assert stored.id == FIRST_REPORT_ID
    assert stored.project_id == PROJECT_ID
    assert stored.created_at == FIRST_GENERATED_AT
    assert stored.snapshot.report.created_at == FIRST_GENERATED_AT
    assert collector.collected.created_at == COLLECTED_AT


def test_generation_rejects_collector_evidence_from_another_project() -> None:
    collector = StaticEvidenceCollector(snapshot_input(project_id=OTHER_PROJECT_ID))
    repository = RecordingRevisionRepository()
    service = QualityReportGenerationService(
        evidence_collector=collector,
        revision_repository=repository,
        clock=lambda: FIRST_GENERATED_AT,
        id_factory=lambda: FIRST_REPORT_ID,
    )

    with pytest.raises(
        QualityReportGenerationRejected,
        match="does not belong to the supplied project",
    ):
        service.generate(project_id=PROJECT_ID)

    assert repository.created == []


def test_generation_fails_closed_when_evidence_collection_is_unavailable() -> None:
    service = QualityReportGenerationService(
        evidence_collector=UnavailableEvidenceCollector(),
        revision_repository=RecordingRevisionRepository(),
        clock=lambda: FIRST_GENERATED_AT,
        id_factory=lambda: FIRST_REPORT_ID,
    )

    with pytest.raises(QualityReportGenerationUnavailable):
        service.generate(project_id=PROJECT_ID)


def test_regeneration_creates_distinct_report_revisions_from_same_evidence() -> None:
    collector = StaticEvidenceCollector(snapshot_input())
    repository = RecordingRevisionRepository()
    report_ids = iter((FIRST_REPORT_ID, SECOND_REPORT_ID))
    generation_times = iter((FIRST_GENERATED_AT, SECOND_GENERATED_AT))
    service = QualityReportGenerationService(
        evidence_collector=collector,
        revision_repository=repository,
        clock=lambda: next(generation_times),
        id_factory=lambda: next(report_ids),
    )

    first = service.generate(project_id=PROJECT_ID)
    second = service.generate(project_id=PROJECT_ID)

    assert collector.calls == [PROJECT_ID, PROJECT_ID]
    assert first.id == FIRST_REPORT_ID
    assert second.id == SECOND_REPORT_ID
    assert first.created_at == FIRST_GENERATED_AT
    assert second.created_at == SECOND_GENERATED_AT
    assert first.snapshot_sha256 != second.snapshot_sha256
