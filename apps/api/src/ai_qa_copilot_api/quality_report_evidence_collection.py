"""Read-only collection of durable, project-scoped QA-report evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Final
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.citations import _citation_from_row, _citation_statement
from ai_qa_copilot_api.documents import (
    CitationRecord,
    ExecutionJobRecord,
    ExecutionResultRecord,
    RequirementAnalysisRunRecord,
    RequirementFindingRecord,
)
from ai_qa_copilot_api.execution_evidence import (
    ExecutionEvidenceViewRejected,
    execution_evidence_view_from_result,
)
from ai_qa_copilot_api.execution_results import _stored_result_from_record
from ai_qa_copilot_api.failure_analysis import (
    ExecutionFailureAnalysis,
    ExecutionFailureAnalysisRejected,
    analyze_execution_failure,
)
from ai_qa_copilot_api.quality_report_generation import (
    QualityReportEvidenceCollectionUnavailable,
)
from ai_qa_copilot_api.quality_report_snapshots import (
    QualityReportSnapshotInput,
    ScopedExecutionEvidence,
    SnapshotExecutionEvidenceState,
)
from ai_qa_copilot_api.requirements_analysis import (
    RequirementAnalysisRun,
    finding_from_record,
    utc_datetime,
)


_COLLECTOR_GENERATOR_VERSION: Final = "quality-report-collection/v1"


class SqlAlchemyQualityReportEvidenceCollector:
    """Collect only immutable project evidence needed for one report revision."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
    ) -> SqlAlchemyQualityReportEvidenceCollector:
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def collect(
        self,
        *,
        project_id: UUID,
    ) -> QualityReportSnapshotInput:
        if not isinstance(project_id, UUID):
            raise QualityReportEvidenceCollectionUnavailable

        try:
            with self._session_factory() as session:
                citations = tuple(
                    _citation_from_row(row)
                    for row in session.execute(
                        _citation_statement()
                        .where(CitationRecord.project_id == project_id)
                        .order_by(CitationRecord.id.asc())
                    )
                )
                analysis_runs = tuple(
                    _analysis_run_from_record(session, record)
                    for record in session.scalars(
                        select(RequirementAnalysisRunRecord)
                        .where(RequirementAnalysisRunRecord.project_id == project_id)
                        .order_by(
                            RequirementAnalysisRunRecord.created_at.asc(),
                            RequirementAnalysisRunRecord.id.asc(),
                        )
                    )
                )
                jobs = tuple(
                    session.scalars(
                        select(ExecutionJobRecord)
                        .where(ExecutionJobRecord.project_id == project_id)
                        .order_by(
                            ExecutionJobRecord.created_at.asc(),
                            ExecutionJobRecord.id.asc(),
                        )
                    )
                )
                results = tuple(
                    _stored_result_from_record(record)
                    for record in session.scalars(
                        select(ExecutionResultRecord)
                        .join(
                            ExecutionJobRecord,
                            ExecutionResultRecord.execution_job_id
                            == ExecutionJobRecord.id,
                        )
                        .where(ExecutionJobRecord.project_id == project_id)
                        .order_by(
                            ExecutionResultRecord.recorded_at.asc(),
                            ExecutionResultRecord.id.asc(),
                        )
                    )
                )
        except (
            ExecutionEvidenceViewRejected,
            ExecutionFailureAnalysisRejected,
            SQLAlchemyError,
            TypeError,
            ValueError,
        ) as error:
            raise QualityReportEvidenceCollectionUnavailable from error

        result_job_ids = {result.execution_job_id for result in results}
        job_ids = {job.id for job in jobs}
        execution_evidence: tuple[ScopedExecutionEvidence, ...]
        failure_analyses: tuple[ExecutionFailureAnalysis, ...]

        try:
            if not jobs:
                execution_evidence_state = SnapshotExecutionEvidenceState.NOT_RUN
                execution_evidence = ()
                failure_analyses = ()
            elif job_ids != result_job_ids:
                execution_evidence_state = SnapshotExecutionEvidenceState.NOT_AVAILABLE
                execution_evidence = ()
                failure_analyses = ()
            else:
                execution_evidence_state = SnapshotExecutionEvidenceState.COMPLETE
                execution_evidence = tuple(
                    ScopedExecutionEvidence(
                        project_id=project_id,
                        evidence=execution_evidence_view_from_result(result),
                    )
                    for result in results
                )
                failure_analyses = tuple(
                    analyze_execution_failure(item.evidence)
                    for item in execution_evidence
                    if item.evidence.outcome in {"failed", "cancelled"}
                )
        except (
            ExecutionEvidenceViewRejected,
            ExecutionFailureAnalysisRejected,
        ) as error:
            raise QualityReportEvidenceCollectionUnavailable from error

        return QualityReportSnapshotInput(
            project_id=project_id,
            source_document_version_ids=tuple(
                sorted(
                    {citation.document_version_id for citation in citations},
                    key=str,
                )
            ),
            citations=citations,
            requirement_analysis_runs=analysis_runs,
            generated_test_cases=(),
            execution_evidence=execution_evidence,
            failure_analyses=failure_analyses,
            execution_evidence_state=execution_evidence_state,
            created_at=_collection_time(self._clock()),
            generator_version=_COLLECTOR_GENERATOR_VERSION,
        )


def _analysis_run_from_record(
    session: Session,
    record: RequirementAnalysisRunRecord,
) -> RequirementAnalysisRun:
    finding_records = tuple(
        session.scalars(
            select(RequirementFindingRecord)
            .where(
                RequirementFindingRecord.requirement_analysis_run_id == record.id,
                RequirementFindingRecord.project_id == record.project_id,
            )
            .order_by(RequirementFindingRecord.id.asc())
        )
    )
    return RequirementAnalysisRun(
        id=record.id,
        project_id=record.project_id,
        analyzer_version=record.analyzer_version,
        citation_ids=tuple(UUID(value) for value in record.citation_ids),
        findings=tuple(finding_from_record(item) for item in finding_records),
        created_at=utc_datetime(record.created_at),
    )


def _collection_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise QualityReportEvidenceCollectionUnavailable
    return value.astimezone(timezone.utc)
