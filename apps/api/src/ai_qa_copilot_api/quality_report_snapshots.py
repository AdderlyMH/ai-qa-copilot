"""Deterministic assembly of immutable, redacted QA evidence snapshots."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
from typing import Final
from uuid import UUID, uuid4, uuid5

from ai_qa_copilot_api.citations import Citation
from ai_qa_copilot_api.execution_evidence import ExecutionEvidenceView
from ai_qa_copilot_api.failure_analysis import ExecutionFailureAnalysis
from ai_qa_copilot_api.generated_tests import (
    GeneratedTestCaseV1,
    validate_generated_test_case,
)
from ai_qa_copilot_api.quality_reports import (
    QualityReportClaimKind,
    QualityReportClaimV1,
    QualityReportEvidenceKind,
    QualityReportEvidenceReference,
    QualityReportProvenanceV1,
    QualityReportSectionName,
    QualityReportSectionState,
    QualityReportSectionV1,
    QualityReportV1,
    validate_quality_report,
)
from ai_qa_copilot_api.requirements_analysis import RequirementAnalysisRun
from ai_qa_copilot_api.findings import RequirementFindingV1


QUALITY_REPORT_SNAPSHOT_GENERATOR_VERSION: Final = "quality-report-snapshot/v1"
_CLAIM_NAMESPACE: Final = UUID("d45a176e-0c7c-4c9b-8f0e-61994dc505d3")
_SNAPSHOT_FIELDS: Final = frozenset({"report", "summary"})
_SUMMARY_FIELDS: Final = frozenset(
    {
        "source_document_version_count",
        "requirement_analysis_run_count",
        "finding_count",
        "finding_counts",
        "generated_test_case_count",
        "execution_count",
        "succeeded_execution_count",
        "failed_execution_count",
        "cancelled_execution_count",
        "failure_analysis_count",
    }
)
_FINDING_COUNT_FIELDS: Final = frozenset({"severity", "category", "count"})


class QualityReportSnapshotRejected(ValueError):
    """Raised when an immutable report snapshot cannot be assembled safely."""


class SnapshotExecutionEvidenceState(StrEnum):
    """The explicit collection state for execution evidence in one snapshot."""

    COMPLETE = "complete"
    NOT_RUN = "not_run"
    NOT_AVAILABLE = "not_available"


@dataclass(frozen=True)
class ScopedExecutionEvidence:
    """One already redacted execution result bound to its owning project."""

    project_id: UUID
    evidence: ExecutionEvidenceView


@dataclass(frozen=True)
class QualityReportFindingCount:
    """One deterministic severity/category total for the executive summary."""

    severity: str
    category: str
    count: int


@dataclass(frozen=True)
class QualityReportSnapshotSummary:
    """Counts derived from the exact records frozen into one report snapshot."""

    source_document_version_count: int
    requirement_analysis_run_count: int
    finding_count: int
    finding_counts: tuple[QualityReportFindingCount, ...]
    generated_test_case_count: int
    execution_count: int
    succeeded_execution_count: int
    failed_execution_count: int
    cancelled_execution_count: int
    failure_analysis_count: int

    def statement(self) -> str:
        """Return a bounded deterministic metrics statement."""

        return (
            "Snapshot counts: "
            f"{self.source_document_version_count} source document version(s), "
            f"{self.requirement_analysis_run_count} requirement analysis run(s), "
            f"{self.finding_count} finding(s), "
            f"{self.generated_test_case_count} generated test case(s), "
            f"{self.execution_count} execution result(s), "
            f"{self.succeeded_execution_count} succeeded, "
            f"{self.failed_execution_count} failed, "
            f"{self.cancelled_execution_count} cancelled, and "
            f"{self.failure_analysis_count} failure analysis record(s)."
        )

    def as_payload(self) -> dict[str, object]:
        """Render the immutable summary included in the snapshot content hash."""

        return {
            "source_document_version_count": self.source_document_version_count,
            "requirement_analysis_run_count": self.requirement_analysis_run_count,
            "finding_count": self.finding_count,
            "finding_counts": [
                {
                    "severity": item.severity,
                    "category": item.category,
                    "count": item.count,
                }
                for item in self.finding_counts
            ],
            "generated_test_case_count": self.generated_test_case_count,
            "execution_count": self.execution_count,
            "succeeded_execution_count": self.succeeded_execution_count,
            "failed_execution_count": self.failed_execution_count,
            "cancelled_execution_count": self.cancelled_execution_count,
            "failure_analysis_count": self.failure_analysis_count,
        }


@dataclass(frozen=True)
class QualityReportSnapshotInput:
    """Validated, project-scoped inputs from which one report is assembled."""

    project_id: UUID
    source_document_version_ids: tuple[UUID, ...]
    citations: tuple[Citation, ...]
    requirement_analysis_runs: tuple[RequirementAnalysisRun, ...]
    generated_test_cases: tuple[GeneratedTestCaseV1, ...]
    execution_evidence: tuple[ScopedExecutionEvidence, ...]
    failure_analyses: tuple[ExecutionFailureAnalysis, ...]
    execution_evidence_state: SnapshotExecutionEvidenceState
    created_at: datetime
    generator_version: str = QUALITY_REPORT_SNAPSHOT_GENERATOR_VERSION


@dataclass(frozen=True)
class QualityReportEvidenceSnapshot:
    """One immutable report plus summary values reconciled to its input records."""

    report: QualityReportV1
    summary: QualityReportSnapshotSummary

    def as_payload(self) -> dict[str, object]:
        """Return the complete immutable snapshot payload."""

        return {
            "report": self.report.as_payload(),
            "summary": self.summary.as_payload(),
        }

    def canonical_json(self) -> str:
        """Return stable JSON for the complete report-and-summary snapshot."""

        return json.dumps(
            self.as_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    def content_sha256(self) -> str:
        """Hash the complete report snapshot, including reconciled summary counts."""

        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


def validate_quality_report_evidence_snapshot(
    payload: Mapping[str, object],
) -> QualityReportEvidenceSnapshot:
    """Validate one stored immutable report-and-summary snapshot."""

    _require_exact_snapshot_fields(
        payload,
        _SNAPSHOT_FIELDS,
        "Quality report evidence snapshot",
    )
    report = validate_quality_report(
        _snapshot_mapping(payload["report"], "Quality report snapshot report")
    )
    summary = _snapshot_summary(payload["summary"])
    _validate_metrics_reconciliation(report, summary)

    return QualityReportEvidenceSnapshot(
        report=report,
        summary=summary,
    )


def _snapshot_summary(value: object) -> QualityReportSnapshotSummary:
    payload = _snapshot_mapping(value, "Quality report snapshot summary")
    _require_exact_snapshot_fields(
        payload,
        _SUMMARY_FIELDS,
        "Quality report snapshot summary",
    )

    finding_counts_value = payload["finding_counts"]
    if not isinstance(finding_counts_value, list):
        raise QualityReportSnapshotRejected(
            "Quality report snapshot finding counts must be a list"
        )

    finding_counts: list[QualityReportFindingCount] = []
    for item in finding_counts_value:
        count_payload = _snapshot_mapping(
            item,
            "Quality report snapshot finding count",
        )
        _require_exact_snapshot_fields(
            count_payload,
            _FINDING_COUNT_FIELDS,
            "Quality report snapshot finding count",
        )
        severity = _snapshot_text(
            count_payload["severity"],
            "Quality report snapshot finding count severity",
        )
        category = _snapshot_text(
            count_payload["category"],
            "Quality report snapshot finding count category",
        )
        count = _snapshot_nonnegative_int(
            count_payload["count"],
            "Quality report snapshot finding count",
        )
        finding_counts.append(
            QualityReportFindingCount(
                severity=severity,
                category=category,
                count=count,
            )
        )

    if len({(item.severity, item.category) for item in finding_counts}) != len(
        finding_counts
    ):
        raise QualityReportSnapshotRejected(
            "Quality report snapshot finding counts must not repeat categories"
        )

    summary = QualityReportSnapshotSummary(
        source_document_version_count=_snapshot_nonnegative_int(
            payload["source_document_version_count"],
            "Quality report snapshot source document version count",
        ),
        requirement_analysis_run_count=_snapshot_nonnegative_int(
            payload["requirement_analysis_run_count"],
            "Quality report snapshot requirement analysis run count",
        ),
        finding_count=_snapshot_nonnegative_int(
            payload["finding_count"],
            "Quality report snapshot finding count",
        ),
        finding_counts=tuple(
            sorted(
                finding_counts,
                key=lambda item: (item.severity, item.category),
            )
        ),
        generated_test_case_count=_snapshot_nonnegative_int(
            payload["generated_test_case_count"],
            "Quality report snapshot generated test case count",
        ),
        execution_count=_snapshot_nonnegative_int(
            payload["execution_count"],
            "Quality report snapshot execution count",
        ),
        succeeded_execution_count=_snapshot_nonnegative_int(
            payload["succeeded_execution_count"],
            "Quality report snapshot succeeded execution count",
        ),
        failed_execution_count=_snapshot_nonnegative_int(
            payload["failed_execution_count"],
            "Quality report snapshot failed execution count",
        ),
        cancelled_execution_count=_snapshot_nonnegative_int(
            payload["cancelled_execution_count"],
            "Quality report snapshot cancelled execution count",
        ),
        failure_analysis_count=_snapshot_nonnegative_int(
            payload["failure_analysis_count"],
            "Quality report snapshot failure analysis count",
        ),
    )

    if sum(item.count for item in summary.finding_counts) != summary.finding_count:
        raise QualityReportSnapshotRejected(
            "Quality report snapshot finding totals must reconcile"
        )

    if (
        summary.succeeded_execution_count
        + summary.failed_execution_count
        + summary.cancelled_execution_count
        != summary.execution_count
    ):
        raise QualityReportSnapshotRejected(
            "Quality report snapshot execution totals must reconcile"
        )

    if summary.failure_analysis_count > (
        summary.failed_execution_count + summary.cancelled_execution_count
    ):
        raise QualityReportSnapshotRejected(
            "Quality report snapshot cannot analyze more failures than it records"
        )

    return summary


def _validate_metrics_reconciliation(
    report: QualityReportV1,
    summary: QualityReportSnapshotSummary,
) -> None:
    metrics_section = next(
        section
        for section in report.sections
        if section.name is QualityReportSectionName.METRICS
    )

    if not report.evidence_catalog:
        if metrics_section.claims:
            raise QualityReportSnapshotRejected(
                "An empty evidence catalog cannot support metrics claims"
            )
        return

    if len(metrics_section.claims) != 1:
        raise QualityReportSnapshotRejected(
            "A report snapshot with evidence requires exactly one metrics claim"
        )

    if metrics_section.claims[0].statement != summary.statement():
        raise QualityReportSnapshotRejected(
            "Quality report snapshot metrics must reconcile with its summary"
        )


def _snapshot_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise QualityReportSnapshotRejected(f"{label} must be an object")
    return value


def _require_exact_snapshot_fields(
    payload: Mapping[str, object],
    expected: frozenset[str],
    label: str,
) -> None:
    if set(payload) != expected:
        raise QualityReportSnapshotRejected(
            f"{label} fields must exactly match the versioned schema"
        )


def _snapshot_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise QualityReportSnapshotRejected(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > 4_000:
        raise QualityReportSnapshotRejected(f"{label} must be bounded non-empty text")
    return normalized


def _snapshot_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise QualityReportSnapshotRejected(f"{label} must be a non-negative integer")
    return value


def build_quality_report_snapshot(
    *,
    snapshot_input: QualityReportSnapshotInput,
    id_factory: Callable[[], UUID] = uuid4,
) -> QualityReportEvidenceSnapshot:
    """Assemble one canonical report from validated, project-scoped evidence."""

    _validate_input(snapshot_input)
    report_id = id_factory()

    citations = tuple(sorted(snapshot_input.citations, key=lambda item: str(item.id)))
    analysis_runs = tuple(
        sorted(snapshot_input.requirement_analysis_runs, key=lambda item: str(item.id))
    )
    findings = tuple(
        sorted(
            (
                finding
                for analysis_run in analysis_runs
                for finding in analysis_run.findings
            ),
            key=lambda item: str(item.id),
        )
    )
    test_cases = tuple(
        sorted(snapshot_input.generated_test_cases, key=lambda item: str(item.id))
    )
    executions = tuple(
        sorted(
            (item.evidence for item in snapshot_input.execution_evidence),
            key=lambda item: str(item.id),
        )
    )
    analyses = tuple(
        sorted(
            snapshot_input.failure_analyses, key=lambda item: str(item.execution_job_id)
        )
    )

    evidence_catalog = _evidence_catalog(
        citations=citations,
        findings=findings,
        test_cases=test_cases,
        executions=executions,
        analyses=analyses,
    )
    summary = _summary(
        source_document_version_ids=snapshot_input.source_document_version_ids,
        analysis_runs=analysis_runs,
        findings=findings,
        test_cases=test_cases,
        executions=executions,
        analyses=analyses,
    )

    catalog_by_kind = {
        kind: tuple(item for item in evidence_catalog if item.kind is kind)
        for kind in QualityReportEvidenceKind
    }

    sections = (
        _scope_section(
            report_id=report_id,
            citation_evidence=catalog_by_kind[QualityReportEvidenceKind.CITATION],
        ),
        _source_inventory_section(
            source_document_version_ids=snapshot_input.source_document_version_ids,
        ),
        _findings_section(
            report_id=report_id,
            analysis_runs=analysis_runs,
            findings=findings,
        ),
        _generated_tests_section(
            report_id=report_id,
            test_cases=test_cases,
        ),
        _unavailable_section(
            QualityReportSectionName.REVIEWED_TESTS,
            "Immutable reviewed-test revision snapshots are not available yet.",
        ),
        _unavailable_section(
            QualityReportSectionName.TRACEABILITY,
            "Immutable traceability-link revisions are not available yet.",
        ),
        _execution_section(
            report_id=report_id,
            executions=executions,
            execution_evidence_state=snapshot_input.execution_evidence_state,
        ),
        _failure_analysis_section(
            report_id=report_id,
            executions=executions,
            analyses=analyses,
            execution_evidence_state=snapshot_input.execution_evidence_state,
        ),
        _metrics_section(
            report_id=report_id,
            summary=summary,
            evidence_catalog=evidence_catalog,
        ),
        _provenance_section(
            report_id=report_id,
            evidence_catalog=evidence_catalog,
        ),
        _limitations_section(report_id=report_id),
    )

    report = QualityReportV1(
        id=report_id,
        project_id=snapshot_input.project_id,
        created_at=snapshot_input.created_at.astimezone(timezone.utc),
        generator_version=snapshot_input.generator_version,
        evidence_catalog=evidence_catalog,
        provenance=QualityReportProvenanceV1(
            source_document_version_ids=tuple(
                sorted(snapshot_input.source_document_version_ids, key=str)
            ),
            requirement_analysis_run_ids=tuple(item.id for item in analysis_runs),
            generated_test_case_ids=tuple(item.id for item in test_cases),
            execution_job_ids=tuple(item.execution_job_id for item in executions),
        ),
        sections=sections,
    )

    try:
        validated_report = validate_quality_report(report.as_payload())
    except ValueError as error:
        raise QualityReportSnapshotRejected(
            "Quality report snapshot violates the canonical report contract"
        ) from error

    return QualityReportEvidenceSnapshot(
        report=validated_report,
        summary=summary,
    )


def _validate_input(snapshot_input: QualityReportSnapshotInput) -> None:
    if not isinstance(snapshot_input.project_id, UUID):
        raise QualityReportSnapshotRejected("Snapshot project id must be a UUID")
    if (
        not isinstance(snapshot_input.created_at, datetime)
        or snapshot_input.created_at.tzinfo is None
        or snapshot_input.created_at.utcoffset() is None
    ):
        raise QualityReportSnapshotRejected(
            "Snapshot creation time must be timezone-aware"
        )

    if (
        not isinstance(snapshot_input.generator_version, str)
        or not snapshot_input.generator_version.strip()
        or len(snapshot_input.generator_version.strip()) > 120
    ):
        raise QualityReportSnapshotRejected(
            "Snapshot generator version must be bounded non-empty text"
        )

    _require_unique(
        snapshot_input.source_document_version_ids,
        "Source document version ids",
    )

    _require_unique(
        (citation.id for citation in snapshot_input.citations),
        "Citation ids",
    )
    citation_ids = {citation.id for citation in snapshot_input.citations}

    for citation in snapshot_input.citations:
        if citation.project_id != snapshot_input.project_id:
            raise QualityReportSnapshotRejected(
                "Citations must belong to the snapshot project"
            )
        if (
            citation.document_version_id
            not in snapshot_input.source_document_version_ids
        ):
            raise QualityReportSnapshotRejected(
                "Snapshot source versions must include every cited document version"
            )

    _require_unique(
        (analysis_run.id for analysis_run in snapshot_input.requirement_analysis_runs),
        "Requirement analysis run ids",
    )

    finding_ids: set[UUID] = set()
    for analysis_run in snapshot_input.requirement_analysis_runs:
        if analysis_run.project_id != snapshot_input.project_id:
            raise QualityReportSnapshotRejected(
                "Requirement analysis runs must belong to the snapshot project"
            )
        if not set(analysis_run.citation_ids).issubset(citation_ids):
            raise QualityReportSnapshotRejected(
                "Requirement analysis runs must reference collected citations"
            )

        for finding in analysis_run.findings:
            if finding.id in finding_ids:
                raise QualityReportSnapshotRejected("Finding ids must not repeat")
            finding_ids.add(finding.id)

            if not {evidence.citation_id for evidence in finding.evidence}.issubset(
                citation_ids
            ):
                raise QualityReportSnapshotRejected(
                    "Findings must reference collected citations"
                )

    _require_unique(
        (test_case.id for test_case in snapshot_input.generated_test_cases),
        "Generated test case ids",
    )

    for test_case in snapshot_input.generated_test_cases:
        try:
            validated_test_case = validate_generated_test_case(test_case.as_payload())
        except ValueError as error:
            raise QualityReportSnapshotRejected(
                "Generated test cases must satisfy the strict generated-test contract"
            ) from error

        if validated_test_case.source_finding_id not in finding_ids:
            raise QualityReportSnapshotRejected(
                "Generated test cases must reference collected findings"
            )
        if not set(validated_test_case.citation_ids).issubset(citation_ids):
            raise QualityReportSnapshotRejected(
                "Generated test cases must reference collected citations"
            )

    if not isinstance(
        snapshot_input.execution_evidence_state,
        SnapshotExecutionEvidenceState,
    ):
        raise QualityReportSnapshotRejected(
            "Execution evidence collection state is not allowed"
        )

    if snapshot_input.execution_evidence:
        if (
            snapshot_input.execution_evidence_state
            is not SnapshotExecutionEvidenceState.COMPLETE
        ):
            raise QualityReportSnapshotRejected(
                "Collected execution evidence requires the complete state"
            )
    elif (
        snapshot_input.execution_evidence_state
        is SnapshotExecutionEvidenceState.COMPLETE
    ):
        raise QualityReportSnapshotRejected(
            "The complete execution-evidence state requires collected evidence"
        )

    execution_ids: set[UUID] = set()
    execution_job_ids: set[UUID] = set()
    failed_execution_by_job: dict[UUID, ExecutionEvidenceView] = {}

    for scoped_execution in snapshot_input.execution_evidence:
        if scoped_execution.project_id != snapshot_input.project_id:
            raise QualityReportSnapshotRejected(
                "Execution evidence must belong to the snapshot project"
            )

        evidence = scoped_execution.evidence
        if (
            evidence.id in execution_ids
            or evidence.execution_job_id in execution_job_ids
        ):
            raise QualityReportSnapshotRejected(
                "Execution result and execution job ids must not repeat"
            )
        execution_ids.add(evidence.id)
        execution_job_ids.add(evidence.execution_job_id)

        if evidence.outcome not in {"succeeded", "failed", "cancelled"}:
            raise QualityReportSnapshotRejected(
                "Execution evidence has an unsupported terminal outcome"
            )

        if evidence.outcome in {"failed", "cancelled"}:
            failed_execution_by_job[evidence.execution_job_id] = evidence

    analysis_job_ids: set[UUID] = set()
    for analysis in snapshot_input.failure_analyses:
        if analysis.execution_job_id in analysis_job_ids:
            raise QualityReportSnapshotRejected(
                "Failure analyses must not repeat execution jobs"
            )
        analysis_job_ids.add(analysis.execution_job_id)

        execution = failed_execution_by_job.get(analysis.execution_job_id)
        if execution is None:
            raise QualityReportSnapshotRejected(
                "Failure analyses require a collected failed or cancelled execution"
            )
        if analysis.outcome != execution.outcome:
            raise QualityReportSnapshotRejected(
                "Failure analysis outcome must match its execution evidence"
            )
        if analysis.failure_code.value != execution.failure_code:
            raise QualityReportSnapshotRejected(
                "Failure analysis code must match its execution evidence"
            )
        if analysis.root_cause is not None:
            raise QualityReportSnapshotRejected(
                "Failure analysis must not assert a root cause from one execution"
            )

    if analysis_job_ids != set(failed_execution_by_job):
        raise QualityReportSnapshotRejected(
            "Every failed or cancelled execution requires one failure analysis"
        )


def _evidence_catalog(
    *,
    citations: tuple[Citation, ...],
    findings: tuple[RequirementFindingV1, ...],
    test_cases: tuple[GeneratedTestCaseV1, ...],
    executions: tuple[ExecutionEvidenceView, ...],
    analyses: tuple[ExecutionFailureAnalysis, ...],
) -> tuple[QualityReportEvidenceReference, ...]:
    references = [
        *(
            QualityReportEvidenceReference(
                kind=QualityReportEvidenceKind.CITATION,
                id=citation.id,
            )
            for citation in citations
        ),
        *(
            QualityReportEvidenceReference(
                kind=QualityReportEvidenceKind.FINDING,
                id=finding.id,
            )
            for finding in findings
        ),
        *(
            QualityReportEvidenceReference(
                kind=QualityReportEvidenceKind.TEST_CASE,
                id=test_case.id,
            )
            for test_case in test_cases
        ),
        *(
            QualityReportEvidenceReference(
                kind=QualityReportEvidenceKind.EXECUTION_RESULT,
                id=execution.id,
            )
            for execution in executions
        ),
        *(
            QualityReportEvidenceReference(
                kind=QualityReportEvidenceKind.FAILURE_ANALYSIS,
                id=next(
                    execution.id
                    for execution in executions
                    if execution.execution_job_id == analysis.execution_job_id
                ),
            )
            for analysis in analyses
        ),
    ]
    return tuple(sorted(references, key=lambda item: (item.kind.value, str(item.id))))


def _summary(
    *,
    source_document_version_ids: tuple[UUID, ...],
    analysis_runs: tuple[RequirementAnalysisRun, ...],
    findings: tuple[RequirementFindingV1, ...],
    test_cases: tuple[GeneratedTestCaseV1, ...],
    executions: tuple[ExecutionEvidenceView, ...],
    analyses: tuple[ExecutionFailureAnalysis, ...],
) -> QualityReportSnapshotSummary:
    counts = Counter(
        (finding.severity.value, finding.category.value) for finding in findings
    )

    return QualityReportSnapshotSummary(
        source_document_version_count=len(source_document_version_ids),
        requirement_analysis_run_count=len(analysis_runs),
        finding_count=len(findings),
        finding_counts=tuple(
            QualityReportFindingCount(
                severity=severity,
                category=category,
                count=count,
            )
            for (severity, category), count in sorted(counts.items())
        ),
        generated_test_case_count=len(test_cases),
        execution_count=len(executions),
        succeeded_execution_count=sum(
            execution.outcome == "succeeded" for execution in executions
        ),
        failed_execution_count=sum(
            execution.outcome == "failed" for execution in executions
        ),
        cancelled_execution_count=sum(
            execution.outcome == "cancelled" for execution in executions
        ),
        failure_analysis_count=len(analyses),
    )


def _scope_section(
    *,
    report_id: UUID,
    citation_evidence: tuple[QualityReportEvidenceReference, ...],
) -> QualityReportSectionV1:
    claims = (
        (
            _supported_claim(
                report_id=report_id,
                section=QualityReportSectionName.SCOPE,
                index=0,
                kind=QualityReportClaimKind.OBSERVATION,
                statement="The report snapshot is scoped to its catalogued project evidence.",
                evidence=citation_evidence,
            ),
        )
        if citation_evidence
        else ()
    )
    return _complete_section(QualityReportSectionName.SCOPE, claims)


def _source_inventory_section(
    *,
    source_document_version_ids: tuple[UUID, ...],
) -> QualityReportSectionV1:
    if not source_document_version_ids:
        return _unavailable_section(
            QualityReportSectionName.SOURCE_INVENTORY,
            "No immutable source document versions were selected for this snapshot.",
        )
    return _complete_section(QualityReportSectionName.SOURCE_INVENTORY, ())


def _findings_section(
    *,
    report_id: UUID,
    analysis_runs: tuple[RequirementAnalysisRun, ...],
    findings: tuple[RequirementFindingV1, ...],
) -> QualityReportSectionV1:
    if not analysis_runs:
        return _not_run_section(
            QualityReportSectionName.FINDINGS,
            "Requirement analysis was not run for this snapshot.",
        )

    claims: list[QualityReportClaimV1] = []
    for index, finding in enumerate(findings):
        if finding.unsupported:
            claims.append(
                _unsupported_claim(
                    report_id=report_id,
                    section=QualityReportSectionName.FINDINGS,
                    index=index,
                    statement="A persisted finding is explicitly marked unsupported.",
                    reason="The finding record does not establish a supported claim.",
                )
            )
            continue

        evidence = (
            QualityReportEvidenceReference(
                kind=QualityReportEvidenceKind.FINDING,
                id=finding.id,
            ),
            *(
                QualityReportEvidenceReference(
                    kind=QualityReportEvidenceKind.CITATION,
                    id=item.citation_id,
                )
                for item in finding.evidence
            ),
        )
        claims.append(
            _supported_claim(
                report_id=report_id,
                section=QualityReportSectionName.FINDINGS,
                index=index,
                kind=QualityReportClaimKind.ANALYSIS,
                statement=(
                    f"A {finding.severity.value} {finding.category.value} "
                    "finding is recorded."
                ),
                evidence=evidence,
            )
        )

    return _complete_section(QualityReportSectionName.FINDINGS, tuple(claims))


def _generated_tests_section(
    *,
    report_id: UUID,
    test_cases: tuple[GeneratedTestCaseV1, ...],
) -> QualityReportSectionV1:
    if not test_cases:
        return _not_run_section(
            QualityReportSectionName.GENERATED_TESTS,
            "Generated test design was not run for this snapshot.",
        )

    claims = tuple(
        _supported_claim(
            report_id=report_id,
            section=QualityReportSectionName.GENERATED_TESTS,
            index=index,
            kind=QualityReportClaimKind.RECOMMENDATION,
            statement="A generated test proposal is linked to its finding and citations.",
            evidence=(
                QualityReportEvidenceReference(
                    kind=QualityReportEvidenceKind.TEST_CASE,
                    id=test_case.id,
                ),
                QualityReportEvidenceReference(
                    kind=QualityReportEvidenceKind.FINDING,
                    id=test_case.source_finding_id,
                ),
                *(
                    QualityReportEvidenceReference(
                        kind=QualityReportEvidenceKind.CITATION,
                        id=citation_id,
                    )
                    for citation_id in test_case.citation_ids
                ),
            ),
        )
        for index, test_case in enumerate(test_cases)
    )
    return _complete_section(QualityReportSectionName.GENERATED_TESTS, claims)


def _execution_section(
    *,
    report_id: UUID,
    executions: tuple[ExecutionEvidenceView, ...],
    execution_evidence_state: SnapshotExecutionEvidenceState,
) -> QualityReportSectionV1:
    if not executions:
        if execution_evidence_state is SnapshotExecutionEvidenceState.NOT_RUN:
            return _not_run_section(
                QualityReportSectionName.EXECUTION_EVIDENCE,
                "No approved execution was run for this snapshot.",
            )

        return _unavailable_section(
            QualityReportSectionName.EXECUTION_EVIDENCE,
            "Execution evidence was not available when this snapshot was assembled.",
        )

    claims = tuple(
        _supported_claim(
            report_id=report_id,
            section=QualityReportSectionName.EXECUTION_EVIDENCE,
            index=index,
            kind=QualityReportClaimKind.OBSERVATION,
            statement=f"An execution result was recorded as {execution.outcome}.",
            evidence=(
                QualityReportEvidenceReference(
                    kind=QualityReportEvidenceKind.EXECUTION_RESULT,
                    id=execution.id,
                ),
            ),
        )
        for index, execution in enumerate(executions)
    )
    return _complete_section(QualityReportSectionName.EXECUTION_EVIDENCE, claims)


def _failure_analysis_section(
    *,
    report_id: UUID,
    executions: tuple[ExecutionEvidenceView, ...],
    analyses: tuple[ExecutionFailureAnalysis, ...],
    execution_evidence_state: SnapshotExecutionEvidenceState,
) -> QualityReportSectionV1:
    if not analyses:
        if executions:
            return QualityReportSectionV1(
                name=QualityReportSectionName.FAILURE_ANALYSIS,
                state=QualityReportSectionState.NOT_APPLICABLE,
                state_reason=(
                    "No failed or cancelled execution requires failure analysis."
                ),
                claims=(),
            )

        if execution_evidence_state is SnapshotExecutionEvidenceState.NOT_RUN:
            return _not_run_section(
                QualityReportSectionName.FAILURE_ANALYSIS,
                "No execution was run for this snapshot.",
            )

        return _unavailable_section(
            QualityReportSectionName.FAILURE_ANALYSIS,
            "Failure analysis is unavailable because execution evidence was unavailable.",
        )

    execution_ids_by_job = {
        execution.execution_job_id: execution.id for execution in executions
    }
    claims = tuple(
        _supported_claim(
            report_id=report_id,
            section=QualityReportSectionName.FAILURE_ANALYSIS,
            index=index,
            kind=QualityReportClaimKind.HYPOTHESIS,
            statement=(
                "Failure analysis preserves observations and hypotheses without "
                "asserting a root cause."
            ),
            evidence=(
                QualityReportEvidenceReference(
                    kind=QualityReportEvidenceKind.EXECUTION_RESULT,
                    id=execution_ids_by_job[analysis.execution_job_id],
                ),
                QualityReportEvidenceReference(
                    kind=QualityReportEvidenceKind.FAILURE_ANALYSIS,
                    id=execution_ids_by_job[analysis.execution_job_id],
                ),
            ),
        )
        for index, analysis in enumerate(analyses)
    )
    return _complete_section(QualityReportSectionName.FAILURE_ANALYSIS, claims)


def _metrics_section(
    *,
    report_id: UUID,
    summary: QualityReportSnapshotSummary,
    evidence_catalog: tuple[QualityReportEvidenceReference, ...],
) -> QualityReportSectionV1:
    claims = (
        (
            _supported_claim(
                report_id=report_id,
                section=QualityReportSectionName.METRICS,
                index=0,
                kind=QualityReportClaimKind.OBSERVATION,
                statement=summary.statement(),
                evidence=evidence_catalog,
            ),
        )
        if evidence_catalog
        else ()
    )
    return _complete_section(QualityReportSectionName.METRICS, claims)


def _provenance_section(
    *,
    report_id: UUID,
    evidence_catalog: tuple[QualityReportEvidenceReference, ...],
) -> QualityReportSectionV1:
    claims = (
        (
            _supported_claim(
                report_id=report_id,
                section=QualityReportSectionName.PROVENANCE,
                index=0,
                kind=QualityReportClaimKind.OBSERVATION,
                statement=(
                    "This report pins immutable provenance identifiers for every "
                    "selected source, analysis, test, and execution."
                ),
                evidence=evidence_catalog,
            ),
        )
        if evidence_catalog
        else ()
    )
    return _complete_section(QualityReportSectionName.PROVENANCE, claims)


def _limitations_section(*, report_id: UUID) -> QualityReportSectionV1:
    return _complete_section(
        QualityReportSectionName.LIMITATIONS,
        (
            _unsupported_claim(
                report_id=report_id,
                section=QualityReportSectionName.LIMITATIONS,
                index=0,
                statement=(
                    "This evidence snapshot is not an autonomous release decision."
                ),
                reason=(
                    "A report snapshot preserves evidence and limitations but cannot "
                    "approve a release."
                ),
            ),
        ),
    )


def _complete_section(
    name: QualityReportSectionName,
    claims: tuple[QualityReportClaimV1, ...],
) -> QualityReportSectionV1:
    return QualityReportSectionV1(
        name=name,
        state=QualityReportSectionState.COMPLETE,
        state_reason=None,
        claims=claims,
    )


def _not_run_section(
    name: QualityReportSectionName,
    reason: str,
) -> QualityReportSectionV1:
    return QualityReportSectionV1(
        name=name,
        state=QualityReportSectionState.NOT_RUN,
        state_reason=reason,
        claims=(),
    )


def _unavailable_section(
    name: QualityReportSectionName,
    reason: str,
) -> QualityReportSectionV1:
    return QualityReportSectionV1(
        name=name,
        state=QualityReportSectionState.NOT_AVAILABLE,
        state_reason=reason,
        claims=(),
    )


def _supported_claim(
    *,
    report_id: UUID,
    section: QualityReportSectionName,
    index: int,
    kind: QualityReportClaimKind,
    statement: str,
    evidence: tuple[QualityReportEvidenceReference, ...],
) -> QualityReportClaimV1:
    return QualityReportClaimV1(
        id=_claim_id(report_id, section, index),
        kind=kind,
        statement=statement,
        evidence=evidence,
        unsupported=False,
        unsupported_reason=None,
    )


def _unsupported_claim(
    *,
    report_id: UUID,
    section: QualityReportSectionName,
    index: int,
    statement: str,
    reason: str,
) -> QualityReportClaimV1:
    return QualityReportClaimV1(
        id=_claim_id(report_id, section, index),
        kind=QualityReportClaimKind.UNSUPPORTED,
        statement=statement,
        evidence=(),
        unsupported=True,
        unsupported_reason=reason,
    )


def _claim_id(
    report_id: UUID,
    section: QualityReportSectionName,
    index: int,
) -> UUID:
    return uuid5(_CLAIM_NAMESPACE, f"{report_id}:{section.value}:{index}")


def _require_unique(values: Iterable[UUID], label: str) -> None:
    materialized = tuple(values)
    if len(set(materialized)) != len(materialized):
        raise QualityReportSnapshotRejected(f"{label} must not repeat")
