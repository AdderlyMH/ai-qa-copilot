"""Allowlist projection of a guest-demo build into ``guest-demo-snapshot/v1``.

ADR-019 Decisions 1, 2, 3, 5 and 11. Only the fields named here reach the
public snapshot; everything else in the report or its citations is dropped.
Statements must equal the report generator's closed template set, excerpts are
redacted before hashing, public identifiers are derived from the body hash
(the projection with every identifier left empty), and the build is refused
when any check fails. The snapshot carries no date and no hash of itself: its
content hash is the SHA-256 of ``snapshot.json`` and the publication date
belongs to the later publish manifest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Final
from uuid import UUID

from ai_qa_copilot_api.citations import Citation
from ai_qa_copilot_api.documents import ExecutionResultOutcome
from ai_qa_copilot_api.findings import FindingCategory, FindingSeverity
from ai_qa_copilot_api.guest_demo_build import DemoBuild
from ai_qa_copilot_api.quality_reports import (
    QualityReportClaimKind,
    QualityReportEvidenceKind,
    QualityReportSectionName,
    QualityReportSectionState,
)


SNAPSHOT_SCHEMA_VERSION: Final = "guest-demo-snapshot/v1"
BUILD_MANIFEST_SCHEMA_VERSION: Final = "guest-demo-build-manifest/v1"
SANITIZATION_POLICY_VERSION: Final = "guest-demo-sanitization/v1"
CONTENT_CLASS: Final = "demo-content-not-evaluation-evidence"
SNAPSHOT_FILE: Final = "snapshot.json"
BUILD_MANIFEST_FILE: Final = "manifest.json"

MAX_EXCERPT_CHARACTERS: Final = 500
MAX_EXCERPTS: Final = 100
ALLOWED_LOCATION_KINDS: Final = frozenset({"markdown_lines"})

NOT_A_MODEL_RESULT: Final = "This is not a model result."
TRACEABILITY_LABEL: Final = (
    "Derived from the evidence links of the findings and generated-test claims."
)
TRACEABILITY_SECTION_NOTE: Final = (
    "The report's own traceability section is not available in v1."
)
PROVENANCE_TEXT: Final = {
    "findings": "Rule-based analyzer; no model.",
    "citations": (
        "Selected by the publishing script: one per parsed requirement unit, "
        "in document order."
    ),
    "test_proposals": "Deterministic generator from author-written seeds.",
    "execution": "Restricted executor against an in-process synthetic mock target.",
    "failure_analysis": "Deterministic.",
    "publication": (
        "The content hash is the SHA-256 of this file and names its directory; "
        "the publication date is recorded in the publish manifest."
    ),
}

# Report generator templates (quality_report_snapshots.py), the only statement,
# state-reason and unsupported-reason text that may be published.
_FIXED_TEXTS: Final = frozenset(
    {
        "The report snapshot is scoped to its catalogued project evidence.",
        "No immutable source document versions were selected for this snapshot.",
        "Requirement analysis was not run for this snapshot.",
        "A persisted finding is explicitly marked unsupported.",
        "The finding record does not establish a supported claim.",
        "Generated test design was not run for this snapshot.",
        "A generated test proposal is linked to its finding and citations.",
        "Immutable reviewed-test revision snapshots are not available yet.",
        "Immutable traceability-link revisions are not available yet.",
        "No approved execution was run for this snapshot.",
        "Execution evidence was not available when this snapshot was assembled.",
        "No failed or cancelled execution requires failure analysis.",
        "No execution was run for this snapshot.",
        "Failure analysis is unavailable because execution evidence was unavailable.",
        "Failure analysis preserves observations and hypotheses without asserting "
        "a root cause.",
        "This report pins immutable provenance identifiers for every selected "
        "source, analysis, test, and execution.",
        "This evidence snapshot is not an autonomous release decision.",
        "A report snapshot preserves evidence and limitations but cannot approve "
        "a release.",
    }
)


def _alternatives(values: Sequence[str]) -> str:
    return "|".join(re.escape(value) for value in sorted(values))


_TEMPLATE_PATTERNS: Final = (
    re.compile(
        rf"A ({_alternatives([item.value for item in FindingSeverity])}) "
        rf"({_alternatives([item.value for item in FindingCategory])}) "
        r"finding is recorded\."
    ),
    re.compile(
        r"An execution result was recorded as "
        rf"({_alternatives([item.value for item in ExecutionResultOutcome])})\."
    ),
    re.compile(
        r"Snapshot counts: \d+ source document version\(s\), \d+ requirement "
        r"analysis run\(s\), \d+ finding\(s\), \d+ generated test case\(s\), "
        r"\d+ execution result\(s\), \d+ succeeded, \d+ failed, \d+ cancelled, "
        r"and \d+ failure analysis record\(s\)\."
    ),
)

# Redaction policy guest-demo-sanitization/v1 (proposed in stage 2b).
# Secret-like text refuses the build; personal or network identifiers are
# replaced by fixed placeholders. A match is never truncated: an excerpt over
# the length cap refuses the build instead.
_SECRET_PATTERNS: Final = (
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
    re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
)
_PLACEHOLDER_PATTERNS: Final = (
    ("[redacted-url]", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://\S+")),
    ("[redacted-email]", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    (
        "[redacted-host]",
        re.compile(r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}\b"),
    ),
    ("[redacted-phone]", re.compile(r"(?<![\w-])\+?\d[\d ().-]{5,}\d(?![\w-])")),
)
_CONTROL_CHARACTERS: Final = re.compile(r"[\x00-\x1f\x7f]")

# Every key the snapshot may contain, per object kind.
SNAPSHOT_KEYS: Final = frozenset(
    {
        "schema_version",
        "content_class",
        "sanitization_policy_version",
        "source",
        "provenance",
        "summary",
        "sections",
        "traceability",
        "excerpts",
    }
)
SOURCE_KEYS: Final = frozenset({"fixture_id", "fixture_version", "classification"})
PROVENANCE_KEYS: Final = frozenset(
    {
        "not_a_model_result",
        "statement",
        "findings",
        "analyzer_version",
        "citations",
        "test_proposals",
        "test_generator_version",
        "execution",
        "failure_analysis",
        "publication",
    }
)
SUMMARY_KEYS: Final = frozenset(
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
FINDING_COUNT_KEYS: Final = frozenset({"severity", "category", "count"})
SECTION_KEYS: Final = frozenset({"name", "state", "state_reason", "claims"})
CLAIM_KEYS: Final = frozenset(
    {"public_id", "kind", "statement", "unsupported", "unsupported_reason", "evidence"}
)
TRACEABILITY_KEYS: Final = frozenset(
    {"label", "report_section_state", "report_section_note", "rows"}
)
TRACEABILITY_ROW_KEYS: Final = frozenset(
    {"finding", "test_proposals", "citation_excerpts"}
)
EXCERPT_KEYS: Final = frozenset(
    {
        "public_id",
        "location_kind",
        "line_start",
        "line_end",
        "page_start",
        "page_end",
        "text",
    }
)


class SnapshotRejected(ValueError):
    """Raised when the projection or a publish-time check refuses the build."""


@dataclass(frozen=True)
class SnapshotOutput:
    """The canonical snapshot bytes and the build manifest bytes."""

    snapshot_bytes: bytes
    manifest_bytes: bytes
    content_hash: str


class _Key(str):
    """A positional identifier placeholder, replaced by its public value."""


def redact_excerpt(text: str) -> str:
    """Apply the v1 redaction policy, refusing rather than truncating."""

    if _CONTROL_CHARACTERS.search(text):
        raise SnapshotRejected("Excerpt contains control characters")
    if len(text) > MAX_EXCERPT_CHARACTERS:
        raise SnapshotRejected("Excerpt exceeds the length cap; it is not truncated")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise SnapshotRejected("Excerpt contains secret-like text")
    redacted = text
    for placeholder, pattern in _PLACEHOLDER_PATTERNS:
        redacted = pattern.sub(placeholder, redacted)
    return redacted


def project_snapshot(build: DemoBuild) -> dict[str, object]:
    """Project one build into the public schema with derived public IDs."""

    report = build.snapshot.report
    summary = build.snapshot.summary.as_payload()

    catalog_keys: dict[tuple[str, UUID], _Key] = {}
    per_kind: dict[str, int] = {}
    for reference in report.evidence_catalog:
        kind = reference.kind.value
        catalog_keys[(kind, reference.id)] = _Key(f"{kind}:{per_kind.get(kind, 0)}")
        per_kind[kind] = per_kind.get(kind, 0) + 1

    citations_by_id = {citation.id: citation for citation in build.citations}
    excerpts = _excerpts(build.citations, catalog_keys)

    claim_keys: dict[tuple[str, UUID], _Key] = {}
    for section in report.sections:
        for index, claim in enumerate(section.claims):
            key = _Key(f"claim:{section.name.value}:{index}")
            if section.name is QualityReportSectionName.FINDINGS:
                for item in claim.evidence:
                    if item.kind is QualityReportEvidenceKind.FINDING:
                        claim_keys[("finding", item.id)] = key
            if section.name is QualityReportSectionName.GENERATED_TESTS:
                for item in claim.evidence:
                    if item.kind is QualityReportEvidenceKind.TEST_CASE:
                        claim_keys[("test_case", item.id)] = key

    def resolve(kind: QualityReportEvidenceKind, item_id: UUID) -> _Key | None:
        if kind is QualityReportEvidenceKind.CITATION:
            if item_id not in citations_by_id:
                raise SnapshotRejected("A claim cites an unknown citation")
            return catalog_keys[(kind.value, item_id)]
        if kind is QualityReportEvidenceKind.FINDING:
            return claim_keys.get(("finding", item_id))
        if kind is QualityReportEvidenceKind.TEST_CASE:
            return claim_keys.get(("test_case", item_id))
        return None

    sections: list[dict[str, object]] = []
    finding_rows: list[dict[str, object]] = []
    test_links: list[tuple[_Key, tuple[_Key, ...]]] = []
    traceability_state: str | None = None
    for section in report.sections:
        _require_text(section.state_reason)
        claims: list[dict[str, object]] = []
        for index, claim in enumerate(section.claims):
            _require_text(claim.statement)
            _require_text(claim.unsupported_reason)
            key = _Key(f"claim:{section.name.value}:{index}")
            evidence = [
                resolved
                for item in claim.evidence
                if (resolved := resolve(item.kind, item.id)) is not None
                and resolved != key
            ]
            claims.append(
                {
                    "public_id": key,
                    "kind": QualityReportClaimKind(claim.kind).value,
                    "statement": claim.statement,
                    "unsupported": claim.unsupported,
                    "unsupported_reason": claim.unsupported_reason,
                    "evidence": evidence,
                }
            )
            if section.name is QualityReportSectionName.FINDINGS:
                finding_rows.append(
                    {
                        "finding": key,
                        "citation_excerpts": [
                            e for e in evidence if e.startswith("citation:")
                        ],
                    }
                )
            if section.name is QualityReportSectionName.GENERATED_TESTS:
                test_links.append(
                    (key, tuple(e for e in evidence if e.startswith("claim:findings:")))
                )
        if section.name is QualityReportSectionName.TRACEABILITY:
            traceability_state = section.state.value
        sections.append(
            {
                "name": QualityReportSectionName(section.name).value,
                "state": QualityReportSectionState(section.state).value,
                "state_reason": section.state_reason,
                "claims": claims,
            }
        )

    if traceability_state != QualityReportSectionState.NOT_AVAILABLE.value:
        raise SnapshotRejected(
            "v1 expects the report's own traceability section to be not available"
        )
    rows = [
        {
            "finding": row["finding"],
            "test_proposals": [
                test for test, findings in test_links if row["finding"] in findings
            ],
            "citation_excerpts": row["citation_excerpts"],
        }
        for row in finding_rows
    ]

    snapshot: dict[str, object] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "content_class": CONTENT_CLASS,
        "sanitization_policy_version": SANITIZATION_POLICY_VERSION,
        "source": {
            "fixture_id": build.fixture.fixture_id,
            "fixture_version": build.fixture.fixture_version,
            "classification": build.fixture.classification,
        },
        "provenance": {
            "not_a_model_result": True,
            "statement": NOT_A_MODEL_RESULT,
            "findings": PROVENANCE_TEXT["findings"],
            "analyzer_version": build.analyzer_version,
            "citations": PROVENANCE_TEXT["citations"],
            "test_proposals": PROVENANCE_TEXT["test_proposals"],
            "test_generator_version": build.test_generator_version,
            "execution": PROVENANCE_TEXT["execution"],
            "failure_analysis": PROVENANCE_TEXT["failure_analysis"],
            "publication": PROVENANCE_TEXT["publication"],
        },
        "summary": _summary(summary),
        "sections": sections,
        "traceability": {
            "label": TRACEABILITY_LABEL,
            "report_section_state": traceability_state,
            "report_section_note": TRACEABILITY_SECTION_NOTE,
            "rows": rows,
        },
        "excerpts": excerpts,
    }
    return _with_public_ids(snapshot)


def canonical_json_bytes(value: object) -> bytes:
    """Sorted keys, no insignificant whitespace, ASCII, no trailing newline."""

    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def render_snapshot(build: DemoBuild) -> SnapshotOutput:
    """Project, check and serialize; refuse on any failed check."""

    snapshot = project_snapshot(build)
    validate_snapshot_schema(snapshot)
    snapshot_bytes = canonical_json_bytes(snapshot)
    _scan_output(snapshot_bytes, build.internal_identifiers)

    content_hash = sha256(snapshot_bytes).hexdigest()
    manifest = {
        "schema_version": BUILD_MANIFEST_SCHEMA_VERSION,
        "content_class": CONTENT_CLASS,
        "content_hash": content_hash,
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "sanitization_policy_version": SANITIZATION_POLICY_VERSION,
        "files": [
            {
                "path": SNAPSHOT_FILE,
                "sha256": content_hash,
                "bytes": len(snapshot_bytes),
            }
        ],
    }
    return SnapshotOutput(
        snapshot_bytes=snapshot_bytes,
        manifest_bytes=canonical_json_bytes(manifest),
        content_hash=content_hash,
    )


def write_snapshot(output: SnapshotOutput, output_dir: Path) -> tuple[Path, ...]:
    """Write exactly the snapshot and its manifest; never overwrite."""

    output_dir.mkdir(parents=True, exist_ok=True)
    targets = (
        (output_dir / SNAPSHOT_FILE, output.snapshot_bytes),
        (output_dir / BUILD_MANIFEST_FILE, output.manifest_bytes),
    )
    for path, _ in targets:
        if path.exists():
            raise SnapshotRejected(
                f"{path.name} already exists; it is never overwritten"
            )
    for path, data in targets:
        with path.open("xb") as handle:
            handle.write(data)
    return tuple(path for path, _ in targets)


def validate_snapshot_schema(snapshot: Mapping[str, object]) -> None:
    """Refuse any key outside the allowlist, at every level."""

    _keys(snapshot, SNAPSHOT_KEYS, "snapshot")
    if snapshot["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotRejected("Unexpected snapshot schema version")
    if snapshot["content_class"] != CONTENT_CLASS:
        raise SnapshotRejected("The demo-not-evaluation marker is missing")
    _keys(_mapping(snapshot["source"]), SOURCE_KEYS, "source")
    provenance = _mapping(snapshot["provenance"])
    _keys(provenance, PROVENANCE_KEYS, "provenance")
    if provenance["not_a_model_result"] is not True or (
        provenance["statement"] != NOT_A_MODEL_RESULT
    ):
        raise SnapshotRejected("The not-a-model-result statement is missing")
    summary = _mapping(snapshot["summary"])
    _keys(summary, SUMMARY_KEYS, "summary")
    for item in _list(summary["finding_counts"]):
        _keys(_mapping(item), FINDING_COUNT_KEYS, "finding count")
    for section in _list(snapshot["sections"]):
        section_map = _mapping(section)
        _keys(section_map, SECTION_KEYS, "section")
        for claim in _list(section_map["claims"]):
            _keys(_mapping(claim), CLAIM_KEYS, "claim")
    traceability = _mapping(snapshot["traceability"])
    _keys(traceability, TRACEABILITY_KEYS, "traceability")
    for row in _list(traceability["rows"]):
        _keys(_mapping(row), TRACEABILITY_ROW_KEYS, "traceability row")
    for excerpt in _list(snapshot["excerpts"]):
        _keys(_mapping(excerpt), EXCERPT_KEYS, "excerpt")


def _excerpts(
    citations: Sequence[Citation],
    catalog_keys: Mapping[tuple[str, UUID], _Key],
) -> list[dict[str, object]]:
    if len(citations) > MAX_EXCERPTS:
        raise SnapshotRejected("Too many excerpts for one publication")
    ordered = sorted(
        citations,
        key=lambda item: (item.source_location.line_start or 0, str(item.id)),
    )
    excerpts: list[dict[str, object]] = []
    for citation in ordered:
        location = citation.source_location
        if location.location_kind not in ALLOWED_LOCATION_KINDS:
            raise SnapshotRejected("Unsupported excerpt location kind")
        excerpts.append(
            {
                "public_id": catalog_keys[
                    (QualityReportEvidenceKind.CITATION.value, citation.id)
                ],
                "location_kind": location.location_kind,
                "line_start": location.line_start,
                "line_end": location.line_end,
                "page_start": location.page_start,
                "page_end": location.page_end,
                "text": redact_excerpt(citation.passage),
            }
        )
    return excerpts


def _summary(summary: Mapping[str, object]) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key in SUMMARY_KEYS - {"finding_counts"}:
        value = summary[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SnapshotRejected("Summary counts must be non-negative integers")
        projected[key] = value
    counts: list[dict[str, object]] = []
    for item in _list(summary["finding_counts"]):
        entry = _mapping(item)
        count = entry["count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise SnapshotRejected("Finding counts must be non-negative integers")
        severity, category = entry["severity"], entry["category"]
        if not isinstance(severity, str) or not isinstance(category, str):
            raise SnapshotRejected("Finding counts must name a severity and category")
        counts.append(
            {
                "severity": FindingSeverity(severity).value,
                "category": FindingCategory(category).value,
                "count": count,
            }
        )
    projected["finding_counts"] = counts
    return projected


def _require_text(value: str | None) -> None:
    if value is None or value in _FIXED_TEXTS:
        return
    if any(pattern.fullmatch(value) for pattern in _TEMPLATE_PATTERNS):
        return
    raise SnapshotRejected("Report text is not a known generator template")


def _with_public_ids(snapshot: dict[str, object]) -> dict[str, object]:
    """Replace positional keys with IDs derived from the body hash (D2)."""

    body_hash = sha256(
        canonical_json_bytes(_map_keys(snapshot, lambda _: ""))
    ).hexdigest()
    issued: dict[str, str] = {}

    def public(key: _Key) -> str:
        if key not in issued:
            digest = sha256(f"{body_hash}:{key}".encode("ascii")).hexdigest()
            issued[key] = "pub-" + digest[:16]
        return issued[key]

    result = _map_keys(snapshot, public)
    if len(set(issued.values())) != len(issued) or not isinstance(result, dict):
        raise SnapshotRejected("Public identifier collision")
    return result


def _map_keys(value: object, replace: Callable[[_Key], str]) -> object:
    if isinstance(value, _Key):
        return replace(value)
    if isinstance(value, Mapping):
        return {key: _map_keys(item, replace) for key, item in value.items()}
    if isinstance(value, list):
        return [_map_keys(item, replace) for item in value]
    return value


def _scan_output(data: bytes, internal_identifiers: frozenset[str]) -> None:
    text = data.decode("ascii")
    for identifier in internal_identifiers:
        if identifier and identifier in text:
            raise SnapshotRejected("An internal identifier reached the snapshot")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise SnapshotRejected("The snapshot contains secret-like text")
    for _, pattern in _PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            raise SnapshotRejected("The snapshot contains an unredacted identifier")


def _keys(value: Mapping[str, object], allowed: frozenset[str], label: str) -> None:
    if set(value) != allowed:
        raise SnapshotRejected(f"The {label} keys differ from the allowlist")


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SnapshotRejected("Expected an object")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise SnapshotRejected("Expected a list")
    return value
