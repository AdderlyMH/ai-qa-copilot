"""Deterministic export formats for immutable quality-report revisions."""

from __future__ import annotations

from datetime import datetime, timezone

from ai_qa_copilot_api.quality_report_revisions import StoredQualityReportRevision


QUALITY_REPORT_MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"
QUALITY_REPORT_JSON_MEDIA_TYPE = "application/json"


def canonical_quality_report_snapshot_json(
    revision: StoredQualityReportRevision,
) -> str:
    """Return the exact canonical snapshot bytes represented by one revision."""

    return revision.snapshot.canonical_json()


def render_quality_report_markdown(
    revision: StoredQualityReportRevision,
) -> str:
    """Render one stored immutable revision as deterministic safe Markdown."""

    report = revision.snapshot.report
    summary = revision.snapshot.summary

    lines = [
        "# Quality Report",
        "",
        "## Immutable revision",
        "",
        f"- Revision ID: `{revision.id}`",
        f"- Project ID: `{revision.project_id}`",
        f"- Revision created at: {_timestamp(revision.created_at)}",
        f"- Report created at: {_timestamp(report.created_at)}",
        f"- Schema version: `{report.as_payload()['schema_version']}`",
        f"- Generator version: `{_markdown_text(report.generator_version)}`",
        f"- Report SHA-256: `{revision.report_sha256}`",
        f"- Snapshot SHA-256: `{revision.snapshot_sha256}`",
        "",
        "## Summary",
        "",
        f"- Source document versions: {summary.source_document_version_count}",
        f"- Requirement analysis runs: {summary.requirement_analysis_run_count}",
        f"- Findings: {summary.finding_count}",
        f"- Generated test cases: {summary.generated_test_case_count}",
        f"- Executions: {summary.execution_count}",
        f"- Succeeded executions: {summary.succeeded_execution_count}",
        f"- Failed executions: {summary.failed_execution_count}",
        f"- Cancelled executions: {summary.cancelled_execution_count}",
        f"- Failure analyses: {summary.failure_analysis_count}",
        "",
        "## Finding counts",
        "",
    ]

    if summary.finding_counts:
        for finding_count in summary.finding_counts:
            lines.append(
                "- "
                f"{finding_count.count} x {_markdown_text(finding_count.severity)}"
                f" / {_markdown_text(finding_count.category)}"
            )
    else:
        lines.append("- None")

    lines.extend(("", "## Report sections", ""))

    for section in report.sections:
        lines.extend(
            (
                f"### {_label(section.name.value)}",
                "",
                f"- State: {_label(section.state.value)}",
            )
        )

        if section.state_reason is not None:
            lines.append(f"- State reason: {_markdown_text(section.state_reason)}")

        if not section.claims:
            lines.extend(("- Claims: none", ""))
            continue

        lines.extend(("- Claims:", ""))

        for claim in section.claims:
            lines.extend(
                (
                    f"  - Claim ID: `{claim.id}`",
                    f"  - Kind: {_label(claim.kind.value)}",
                    f"  - Statement: {_markdown_text(claim.statement)}",
                )
            )

            if claim.unsupported:
                lines.append(
                    "  - Limitation: "
                    f"{_markdown_text(claim.unsupported_reason or 'Unsupported claim.')}"
                )

            if claim.evidence:
                lines.append("  - Evidence:")
                lines.extend(
                    f"    - `{reference.kind.value}:{reference.id}`"
                    for reference in claim.evidence
                )
            else:
                lines.append("  - Evidence: none")

            lines.append("")

    lines.extend(("", "## Provenance", ""))

    _append_identifier_list(
        lines,
        "Source document versions",
        report.provenance.source_document_version_ids,
    )
    _append_identifier_list(
        lines,
        "Requirement analysis runs",
        report.provenance.requirement_analysis_run_ids,
    )
    _append_identifier_list(
        lines,
        "Generated test cases",
        report.provenance.generated_test_case_ids,
    )
    _append_identifier_list(
        lines,
        "Execution jobs",
        report.provenance.execution_job_ids,
    )

    lines.extend(("", "## Evidence catalog", ""))

    if report.evidence_catalog:
        lines.extend(
            f"- `{reference.kind.value}:{reference.id}`"
            for reference in report.evidence_catalog
        )
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def _append_identifier_list(
    lines: list[str],
    title: str,
    identifiers: tuple[object, ...],
) -> None:
    lines.append(f"### {title}")

    if identifiers:
        lines.extend(f"- `{identifier}`" for identifier in identifiers)
    else:
        lines.append("- None")

    lines.append("")


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def _markdown_text(value: str) -> str:
    """Flatten and escape untrusted report text for safe Markdown display."""

    escaped = " ".join(value.split())

    for character in ("\\", "`", "*", "_", "[", "]", "<", ">", "#"):
        escaped = escaped.replace(character, f"\\{character}")

    return escaped


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
