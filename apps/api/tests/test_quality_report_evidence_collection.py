from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    ExecutionJobRecord,
    ExecutionJobState,
    ExecutionResultOutcome,
    ExecutionResultRecord,
)
from ai_qa_copilot_api.projects import Base, ProjectRecord
from ai_qa_copilot_api.quality_report_evidence_collection import (
    SqlAlchemyQualityReportEvidenceCollector,
)
from ai_qa_copilot_api.quality_report_snapshots import (
    SnapshotExecutionEvidenceState,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-00000000d001")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-00000000d002")
JOB_ID = UUID("00000000-0000-0000-0000-00000000d003")
RESULT_ID = UUID("00000000-0000-0000-0000-00000000d004")
NOW = datetime(2026, 9, 10, 21, 0, tzinfo=timezone.utc)


def sessions() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_collector_marks_projects_without_jobs_as_not_run() -> None:
    session_factory = sessions()
    with session_factory.begin() as session:
        session.add(
            ProjectRecord(
                id=PROJECT_ID,
                name="Report project",
                description=None,
                created_at=NOW,
                archived_at=None,
            )
        )

    collected = SqlAlchemyQualityReportEvidenceCollector(
        session_factory,
        clock=lambda: NOW,
    ).collect(project_id=PROJECT_ID)

    assert collected.project_id == PROJECT_ID
    assert collected.created_at == NOW
    assert collected.source_document_version_ids == ()
    assert collected.citations == ()
    assert collected.requirement_analysis_runs == ()
    assert collected.generated_test_cases == ()
    assert collected.execution_evidence == ()
    assert collected.failure_analyses == ()
    assert collected.execution_evidence_state is SnapshotExecutionEvidenceState.NOT_RUN


def test_collector_scopes_and_re_redacts_terminal_execution_evidence() -> None:
    session_factory = sessions()
    canary = "rep-003-collector-canary"

    with session_factory.begin() as session:
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
                ExecutionJobRecord(
                    id=JOB_ID,
                    project_id=OTHER_PROJECT_ID,
                    execution_approval_id=UUID("00000000-0000-0000-0000-00000000d005"),
                    plan_id=UUID("00000000-0000-0000-0000-00000000d006"),
                    plan_hash="a" * 64,
                    state=ExecutionJobState.SUCCEEDED.value,
                    created_at=NOW,
                    started_at=NOW,
                    finished_at=NOW,
                    cancel_requested_at=None,
                    cancelled_at=None,
                ),
                ExecutionResultRecord(
                    id=RESULT_ID,
                    execution_job_id=JOB_ID,
                    outcome=ExecutionResultOutcome.SUCCEEDED.value,
                    failure_code=None,
                    assertion_results=[
                        {
                            "passed": True,
                            "token": canary,
                        }
                    ],
                    request_evidence={
                        "headers": [["Authorization", canary]],
                        "method": "POST",
                    },
                    response_evidence={"status_code": 201},
                    transport_send_count=1,
                    recorded_at=NOW,
                ),
            )
        )

    collector = SqlAlchemyQualityReportEvidenceCollector(
        session_factory,
        clock=lambda: NOW,
    )

    own = collector.collect(project_id=PROJECT_ID)
    foreign = collector.collect(project_id=OTHER_PROJECT_ID)

    assert own.execution_evidence_state is SnapshotExecutionEvidenceState.NOT_RUN
    assert own.execution_evidence == ()
    assert foreign.execution_evidence_state is SnapshotExecutionEvidenceState.COMPLETE
    assert len(foreign.execution_evidence) == 1
    assert canary not in repr(foreign)
    assert foreign.execution_evidence[0].evidence.assertion_results[0]["token"] == (
        "[REDACTED]"
    )
    assert foreign.execution_evidence[0].evidence.request_evidence == {
        "headers": [["Authorization", "[REDACTED]"]],
        "method": "POST",
    }
