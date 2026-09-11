from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID
from copy import deepcopy

import pytest

from ai_qa_copilot_api.citations import Citation, SourceLocation
from ai_qa_copilot_api.execution_evidence import ExecutionEvidenceView
from ai_qa_copilot_api.failure_analysis import analyze_execution_failure
from ai_qa_copilot_api.generated_tests import (
    GeneratedTestCaseV1,
    validate_generated_test_case,
)
from ai_qa_copilot_api.quality_report_snapshots import (
    QualityReportSnapshotInput,
    QualityReportSnapshotRejected,
    ScopedExecutionEvidence,
    build_quality_report_snapshot,
    SnapshotExecutionEvidenceState,
    validate_quality_report_evidence_snapshot,
)
from ai_qa_copilot_api.quality_reports import (
    QualityReportSectionName,
    QualityReportSectionState,
    validate_quality_report,
)
from ai_qa_copilot_api.requirements_analysis import RequirementAnalysisRun
from ai_qa_copilot_api.findings import (
    RequirementFindingV1,
    validate_requirement_finding,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-00000000a001")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-00000000a002")
DOCUMENT_VERSION_ID = UUID("00000000-0000-0000-0000-00000000a003")
CITATION_ID = UUID("00000000-0000-0000-0000-00000000a004")
ANALYSIS_RUN_ID = UUID("00000000-0000-0000-0000-00000000a005")
FINDING_ID = UUID("00000000-0000-0000-0000-00000000a006")
TEST_CASE_ID = UUID("00000000-0000-0000-0000-00000000a007")
EXECUTION_RESULT_ID = UUID("00000000-0000-0000-0000-00000000a008")
EXECUTION_JOB_ID = UUID("00000000-0000-0000-0000-00000000a009")
REPORT_ID = UUID("00000000-0000-0000-0000-00000000a010")


def citation() -> Citation:
    return Citation(
        id=CITATION_ID,
        project_id=PROJECT_ID,
        retrieval_trace_id=UUID("00000000-0000-0000-0000-00000000a011"),
        document_chunk_id=UUID("00000000-0000-0000-0000-00000000a012"),
        document_version_id=DOCUMENT_VERSION_ID,
        source_location=SourceLocation(
            id=UUID("00000000-0000-0000-0000-00000000a013"),
            location_kind="markdown",
            heading="Orders",
            line_start=4,
            line_end=4,
            page_start=None,
            page_end=None,
            json_pointer=None,
        ),
        document_type="markdown",
        display_name="requirements.md",
        passage="Orders must include observable acceptance criteria.",
        created_at=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc),
    )


def finding() -> RequirementFindingV1:
    return validate_requirement_finding(
        {
            "schema_version": "requirement-finding/v1",
            "id": str(FINDING_ID),
            "category": "missing_acceptance_criteria",
            "severity": "medium",
            "evidence": [
                {
                    "citation_id": str(CITATION_ID),
                    "observed_fact": "The cited requirement has no acceptance criteria.",
                }
            ],
            "analysis": "The requirement is not consistently verifiable.",
            "confidence": 0.8,
            "recommendation": "Add observable acceptance criteria.",
            "unsupported": False,
            "unsupported_reason": None,
        }
    )


def generated_case() -> GeneratedTestCaseV1:
    return validate_generated_test_case(
        {
            "schema_version": "generated-test-case/v1",
            "id": str(TEST_CASE_ID),
            "title": "Reject an order without required criteria",
            "kind": "negative",
            "source_finding_id": str(FINDING_ID),
            "citation_ids": [str(CITATION_ID)],
            "request": {
                "method": "POST",
                "path": "/api/orders",
                "query": [],
                "headers": [],
                "json_body": {"product_id": "demo"},
            },
            "assertions": [
                {
                    "target": "status_code",
                    "selector": None,
                    "operator": "equals",
                    "expected_value": 400,
                }
            ],
        }
    )


def successful_execution() -> ExecutionEvidenceView:
    return ExecutionEvidenceView(
        id=EXECUTION_RESULT_ID,
        execution_job_id=EXECUTION_JOB_ID,
        outcome="succeeded",
        failure_code=None,
        assertion_results=({"target": "status_code", "passed": True},),
        request_evidence={"method": "POST"},
        response_evidence={"status_code": 201, "elapsed_ms": 15},
        response_status_code=201,
        response_elapsed_ms=15,
        transport_send_count=1,
        recorded_at=datetime(2026, 9, 10, 12, 1, tzinfo=timezone.utc),
    )


def snapshot_input(
    *,
    execution_evidence_state: SnapshotExecutionEvidenceState,
    executions: tuple[ScopedExecutionEvidence, ...] | None = None,
) -> QualityReportSnapshotInput:
    requirement_analysis_run = RequirementAnalysisRun(
        id=ANALYSIS_RUN_ID,
        project_id=PROJECT_ID,
        analyzer_version="requirement-quality-rules/v1",
        citation_ids=(CITATION_ID,),
        findings=(finding(),),
        created_at=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc),
    )

    return QualityReportSnapshotInput(
        project_id=PROJECT_ID,
        source_document_version_ids=(DOCUMENT_VERSION_ID,),
        citations=(citation(),),
        requirement_analysis_runs=(requirement_analysis_run,),
        generated_test_cases=(generated_case(),),
        execution_evidence=(
            executions
            if executions is not None
            else (
                ScopedExecutionEvidence(
                    project_id=PROJECT_ID,
                    evidence=successful_execution(),
                ),
            )
        ),
        failure_analyses=(),
        execution_evidence_state=execution_evidence_state,
        created_at=datetime(2026, 9, 10, 12, 2, tzinfo=timezone.utc),
    )


def test_snapshot_reconciles_summary_with_exact_detailed_records() -> None:
    snapshot = build_quality_report_snapshot(
        snapshot_input=snapshot_input(
            execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
        ),
        id_factory=lambda: REPORT_ID,
    )

    assert validate_quality_report(snapshot.report.as_payload()) == snapshot.report
    assert snapshot.summary.source_document_version_count == 1
    assert snapshot.summary.requirement_analysis_run_count == 1
    assert snapshot.summary.finding_count == 1
    assert snapshot.summary.finding_counts[0].severity == "medium"
    assert snapshot.summary.finding_counts[0].category == "missing_acceptance_criteria"
    assert snapshot.summary.finding_counts[0].count == 1
    assert snapshot.summary.generated_test_case_count == 1
    assert snapshot.summary.execution_count == 1
    assert snapshot.summary.succeeded_execution_count == 1
    assert snapshot.summary.failed_execution_count == 0
    assert snapshot.summary.cancelled_execution_count == 0
    assert snapshot.summary.failure_analysis_count == 0

    sections = {section.name: section for section in snapshot.report.sections}
    assert (
        sections[QualityReportSectionName.EXECUTION_EVIDENCE].state
        is QualityReportSectionState.COMPLETE
    )
    assert (
        sections[QualityReportSectionName.FAILURE_ANALYSIS].state
        is QualityReportSectionState.NOT_APPLICABLE
    )


def test_snapshot_marks_no_execution_and_no_failure_analysis_explicitly() -> None:
    snapshot = build_quality_report_snapshot(
        snapshot_input=snapshot_input(
            execution_evidence_state=SnapshotExecutionEvidenceState.NOT_RUN,
            executions=(),
        ),
        id_factory=lambda: REPORT_ID,
    )

    sections = {section.name: section for section in snapshot.report.sections}

    assert (
        sections[QualityReportSectionName.EXECUTION_EVIDENCE].state
        is QualityReportSectionState.NOT_RUN
    )
    assert (
        sections[QualityReportSectionName.FAILURE_ANALYSIS].state
        is QualityReportSectionState.NOT_RUN
    )
    assert (
        sections[QualityReportSectionName.REVIEWED_TESTS].state
        is QualityReportSectionState.NOT_AVAILABLE
    )
    assert (
        sections[QualityReportSectionName.TRACEABILITY].state
        is QualityReportSectionState.NOT_AVAILABLE
    )


def test_snapshot_rejects_cross_project_execution_evidence() -> None:
    invalid_input = snapshot_input(
        execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
        executions=(
            ScopedExecutionEvidence(
                project_id=OTHER_PROJECT_ID,
                evidence=successful_execution(),
            ),
        ),
    )

    with pytest.raises(
        QualityReportSnapshotRejected,
        match="must belong to the snapshot project",
    ):
        build_quality_report_snapshot(
            snapshot_input=invalid_input,
            id_factory=lambda: REPORT_ID,
        )


def test_snapshot_rejects_cross_project_citations() -> None:
    original = snapshot_input(
        execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
    )
    foreign_citation = replace(
        original.citations[0],
        project_id=OTHER_PROJECT_ID,
    )
    invalid_input = replace(
        original,
        citations=(foreign_citation,),
    )

    with pytest.raises(
        QualityReportSnapshotRejected,
        match="Citations must belong to the snapshot project",
    ):
        build_quality_report_snapshot(
            snapshot_input=invalid_input,
            id_factory=lambda: REPORT_ID,
        )


def test_snapshot_requires_analysis_for_each_failed_execution() -> None:
    failed_execution = replace(
        successful_execution(),
        outcome="failed",
        failure_code="transport_timeout",
    )
    invalid_input = snapshot_input(
        execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
        executions=(
            ScopedExecutionEvidence(
                project_id=PROJECT_ID,
                evidence=failed_execution,
            ),
        ),
    )

    with pytest.raises(
        QualityReportSnapshotRejected,
        match="requires one failure analysis",
    ):
        build_quality_report_snapshot(
            snapshot_input=invalid_input,
            id_factory=lambda: REPORT_ID,
        )

    valid_input = replace(
        invalid_input,
        failure_analyses=(analyze_execution_failure(failed_execution),),
    )
    snapshot = build_quality_report_snapshot(
        snapshot_input=valid_input,
        id_factory=lambda: REPORT_ID,
    )

    assert snapshot.summary.failed_execution_count == 1
    assert snapshot.summary.failure_analysis_count == 1

    section = next(
        item
        for item in snapshot.report.sections
        if item.name is QualityReportSectionName.FAILURE_ANALYSIS
    )
    assert section.state is QualityReportSectionState.COMPLETE


def test_snapshot_is_deterministic_for_identical_frozen_inputs() -> None:
    first = build_quality_report_snapshot(
        snapshot_input=snapshot_input(
            execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
        ),
        id_factory=lambda: REPORT_ID,
    )
    second = build_quality_report_snapshot(
        snapshot_input=snapshot_input(
            execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
        ),
        id_factory=lambda: REPORT_ID,
    )

    assert first.report.canonical_json() == second.report.canonical_json()
    assert first.report.content_sha256() == second.report.content_sha256()


def test_snapshot_rejects_duplicate_citation_ids() -> None:
    original = snapshot_input(
        execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
    )
    invalid_input = replace(
        original,
        citations=(original.citations[0], original.citations[0]),
    )

    with pytest.raises(
        QualityReportSnapshotRejected,
        match="Citation ids must not repeat",
    ):
        build_quality_report_snapshot(
            snapshot_input=invalid_input,
            id_factory=lambda: REPORT_ID,
        )


def test_snapshot_marks_missing_execution_evidence_as_not_available() -> None:
    snapshot = build_quality_report_snapshot(
        snapshot_input=snapshot_input(
            execution_evidence_state=SnapshotExecutionEvidenceState.NOT_AVAILABLE,
            executions=(),
        ),
        id_factory=lambda: REPORT_ID,
    )
    sections = {section.name: section for section in snapshot.report.sections}

    assert (
        sections[QualityReportSectionName.EXECUTION_EVIDENCE].state
        is QualityReportSectionState.NOT_AVAILABLE
    )
    assert (
        sections[QualityReportSectionName.FAILURE_ANALYSIS].state
        is QualityReportSectionState.NOT_AVAILABLE
    )


def test_snapshot_rejects_complete_execution_state_without_evidence() -> None:
    with pytest.raises(
        QualityReportSnapshotRejected,
        match="requires collected evidence",
    ):
        build_quality_report_snapshot(
            snapshot_input=snapshot_input(
                execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
                executions=(),
            ),
            id_factory=lambda: REPORT_ID,
        )


def test_snapshot_hash_includes_reconciled_summary_counts() -> None:
    snapshot = build_quality_report_snapshot(
        snapshot_input=snapshot_input(
            execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
        ),
        id_factory=lambda: REPORT_ID,
    )
    altered = replace(
        snapshot,
        summary=replace(snapshot.summary, execution_count=999),
    )

    assert snapshot.report.content_sha256() == altered.report.content_sha256()
    assert snapshot.content_sha256() != altered.content_sha256()


def test_snapshot_payload_round_trips_with_hashable_summary() -> None:
    snapshot = build_quality_report_snapshot(
        snapshot_input=snapshot_input(
            execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
        ),
        id_factory=lambda: REPORT_ID,
    )

    restored = validate_quality_report_evidence_snapshot(snapshot.as_payload())

    assert restored.canonical_json() == snapshot.canonical_json()
    assert restored.content_sha256() == snapshot.content_sha256()
    assert restored.report.content_sha256() == snapshot.report.content_sha256()


def test_snapshot_payload_rejects_non_reconciling_summary_totals() -> None:
    snapshot = build_quality_report_snapshot(
        snapshot_input=snapshot_input(
            execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
        ),
        id_factory=lambda: REPORT_ID,
    )
    payload = deepcopy(snapshot.as_payload())
    summary = payload["summary"]
    assert isinstance(summary, dict)
    summary["execution_count"] = 2

    with pytest.raises(
        QualityReportSnapshotRejected,
        match="execution totals must reconcile",
    ):
        validate_quality_report_evidence_snapshot(payload)


def test_snapshot_payload_rejects_metrics_statement_that_differs_from_summary() -> None:
    snapshot = build_quality_report_snapshot(
        snapshot_input=snapshot_input(
            execution_evidence_state=SnapshotExecutionEvidenceState.COMPLETE,
        ),
        id_factory=lambda: REPORT_ID,
    )
    payload = deepcopy(snapshot.as_payload())
    report = payload["report"]
    assert isinstance(report, dict)
    sections = report["sections"]
    assert isinstance(sections, list)

    metrics_section = next(
        section
        for section in sections
        if isinstance(section, dict) and section["name"] == "metrics"
    )
    assert isinstance(metrics_section, dict)
    claims = metrics_section["claims"]
    assert isinstance(claims, list)
    claim = claims[0]
    assert isinstance(claim, dict)
    claim["statement"] = "This modified statement must be rejected."

    with pytest.raises(
        QualityReportSnapshotRejected,
        match="metrics must reconcile",
    ):
        validate_quality_report_evidence_snapshot(payload)
