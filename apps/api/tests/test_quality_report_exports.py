from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from ai_qa_copilot_api.quality_report_exports import (
    canonical_quality_report_snapshot_json,
    render_quality_report_markdown,
)
from ai_qa_copilot_api.quality_report_revisions import StoredQualityReportRevision
from ai_qa_copilot_api.quality_report_snapshots import (
    QualityReportEvidenceSnapshot,
    QualityReportSnapshotSummary,
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
)


PROJECT_ID = UUID("10000000-0000-0000-0000-000000000001")
REPORT_ID = UUID("20000000-0000-0000-0000-000000000002")
CLAIM_ID = UUID("30000000-0000-0000-0000-000000000003")
CITATION_ID = UUID("40000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 9, 11, 5, 30, tzinfo=timezone.utc)


def revision() -> StoredQualityReportRevision:
    evidence = QualityReportEvidenceReference(
        kind=QualityReportEvidenceKind.CITATION,
        id=CITATION_ID,
    )
    report = QualityReportV1(
        id=REPORT_ID,
        project_id=PROJECT_ID,
        created_at=NOW,
        generator_version="quality-report-collection/v1",
        evidence_catalog=(evidence,),
        provenance=QualityReportProvenanceV1(
            source_document_version_ids=(),
            requirement_analysis_run_ids=(),
            generated_test_case_ids=(),
            execution_job_ids=(),
        ),
        sections=(
            QualityReportSectionV1(
                name=QualityReportSectionName.SCOPE,
                state=QualityReportSectionState.COMPLETE,
                state_reason=None,
                claims=(
                    QualityReportClaimV1(
                        id=CLAIM_ID,
                        kind=QualityReportClaimKind.OBSERVATION,
                        statement="Scope *statement* <must remain text>",
                        evidence=(evidence,),
                        unsupported=False,
                        unsupported_reason=None,
                    ),
                ),
            ),
        ),
    )
    snapshot = QualityReportEvidenceSnapshot(
        report=report,
        summary=QualityReportSnapshotSummary(
            source_document_version_count=0,
            requirement_analysis_run_count=0,
            finding_count=0,
            finding_counts=(),
            generated_test_case_count=0,
            execution_count=0,
            succeeded_execution_count=0,
            failed_execution_count=0,
            cancelled_execution_count=0,
            failure_analysis_count=0,
        ),
    )
    return StoredQualityReportRevision(
        id=REPORT_ID,
        project_id=PROJECT_ID,
        schema_version="quality-report/v1",
        snapshot=snapshot,
        report_sha256="a" * 64,
        snapshot_sha256="b" * 64,
        created_at=NOW,
    )


def test_canonical_json_export_is_the_exact_stored_snapshot() -> None:
    stored_revision = revision()

    assert (
        canonical_quality_report_snapshot_json(stored_revision)
        == stored_revision.snapshot.canonical_json()
    )


def test_markdown_export_is_deterministic_and_escapes_report_text() -> None:
    stored_revision = revision()

    first_export = render_quality_report_markdown(stored_revision)
    second_export = render_quality_report_markdown(stored_revision)

    assert first_export == second_export
    assert first_export.endswith("\n")
    assert f"- Revision ID: `{REPORT_ID}`" in first_export
    assert "- Report SHA-256: `" + ("a" * 64) + "`" in first_export
    assert "- Snapshot SHA-256: `" + ("b" * 64) + "`" in first_export
    assert "### Scope" in first_export
    assert "Scope \\*statement\\* \\<must remain text\\>" in first_export
    assert f"`citation:{CITATION_ID}`" in first_export
