"""Contract checks for the guest-demo fixture (ADR-019 Decisions 8, 10, 12)."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from uuid import UUID, uuid5

from fastapi.testclient import TestClient
from starlette.routing import Match

from ai_qa_copilot_api.citations import Citation, SourceLocation
from ai_qa_copilot_api.generated_tests import (
    GENERATED_TEST_CASE_SCHEMA_VERSION,
    validate_generated_test_case,
)
from ai_qa_copilot_api.markdown_parser import parse_markdown_or_text
from ai_qa_copilot_api.mock_order_api import create_mock_order_app
from ai_qa_copilot_api.requirements_analysis import analyze_citations


ROOT = Path(__file__).resolve().parents[3]
DEMO_FIXTURE = ROOT / "demo/fixture"
MANIFEST = DEMO_FIXTURE / "demo-manifest.json"
NAMESPACE = uuid5(UUID(int=1), "guest-demo-fixture-test")

EXPECTED_REQUIREMENT_IDS = tuple(f"REQ-ORD-{number:03d}" for number in range(1, 9))

# What the rule-based analyzer must report, keyed by the requirement(s) cited.
EXPECTED_FINDINGS = {
    (("REQ-ORD-002",), "missing_acceptance_criteria"),
    (("REQ-ORD-002",), "ambiguity"),
    (("REQ-ORD-002",), "performance_risk"),
    (("REQ-ORD-003",), "authorization_gap"),
    (("REQ-ORD-003",), "error_handling_gap"),
    (("REQ-ORD-004",), "missing_acceptance_criteria"),
    (("REQ-ORD-004",), "ambiguity"),
    (("REQ-ORD-005",), "missing_acceptance_criteria"),
    (("REQ-ORD-006",), "missing_acceptance_criteria"),
    (("REQ-ORD-005", "REQ-ORD-006"), "contradiction"),
    (("REQ-ORD-007",), "missing_acceptance_criteria"),
    (("REQ-ORD-007",), "ambiguity"),
    (("REQ-ORD-007",), "performance_risk"),
    (("REQ-ORD-008",), "error_handling_gap"),
}

URL_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://|www\.", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{12,}\b|\bsk-[A-Za-z0-9]{16,}")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
# Only the mock order API's seeded identifiers (all-zero prefix) may appear.
SYNTHETIC_UUID_PREFIX = "00000000-0000-0000-0000-"
FORBIDDEN_PATH_FRAGMENTS = ("fixtures/", "evaluation/", "benchmark/")


def manifest() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return payload


def listed_files() -> dict[str, str]:
    return {entry["path"]: entry["sha256"] for entry in manifest()["files"]}


def demo_files() -> list[Path]:
    return sorted(path for path in DEMO_FIXTURE.iterdir() if path.is_file())


def seeds() -> list[dict[str, Any]]:
    payload: dict[str, Any] = json.loads(
        (DEMO_FIXTURE / "seeds.json").read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == "guest-demo-test-seeds/v1"
    seed_list: list[dict[str, Any]] = payload["seeds"]
    return seed_list


def requirement_citations() -> tuple[tuple[str, Citation], ...]:
    """One citation per parsed requirement unit, in document order."""

    raw = (DEMO_FIXTURE / "requirements.md").read_bytes()
    document_version_id = uuid5(NAMESPACE, sha256(raw).hexdigest())
    created_at = datetime(2026, 10, 21, tzinfo=timezone.utc)
    citations: list[tuple[str, Citation]] = []
    for unit in parse_markdown_or_text(document_type="markdown", raw=raw):
        assert unit.requirement_id is not None, "every unit must carry a REQ ID"
        identity = f"{document_version_id}:{unit.ordinal}"
        citations.append(
            (
                unit.requirement_id,
                Citation(
                    id=uuid5(NAMESPACE, f"citation:{identity}"),
                    project_id=uuid5(NAMESPACE, "project"),
                    retrieval_trace_id=uuid5(NAMESPACE, f"trace:{identity}"),
                    document_chunk_id=uuid5(NAMESPACE, f"chunk:{identity}"),
                    document_version_id=document_version_id,
                    source_location=SourceLocation(
                        id=uuid5(NAMESPACE, f"location:{identity}"),
                        location_kind="markdown_lines",
                        heading=unit.heading,
                        line_start=unit.line_start,
                        line_end=unit.line_end,
                        page_start=None,
                        page_end=None,
                        json_pointer=None,
                    ),
                    document_type="markdown",
                    display_name="requirements.md",
                    passage=unit.normalized_text,
                    created_at=created_at,
                ),
            )
        )
    return tuple(citations)


def analyzer_findings() -> set[tuple[tuple[str, ...], str]]:
    citations = requirement_citations()
    requirement_by_citation = {citation.id: req_id for req_id, citation in citations}
    findings = analyze_citations(tuple(citation for _, citation in citations))
    return {
        (
            tuple(
                sorted(
                    requirement_by_citation[item.citation_id]
                    for item in finding.evidence
                )
            ),
            finding.category.value,
        )
        for finding in findings
    }


def json_pointer(document: object, pointer: str) -> tuple[bool, object]:
    current = document
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def test_manifest_records_the_raw_bytes_sha256_of_every_listed_file() -> None:
    payload = manifest()
    assert payload["schema_version"] == "guest-demo-fixture-manifest/v1"
    assert payload["classification"] == "synthetic"
    assert payload["hash_algorithm"] == "sha256-raw-bytes"
    assert set(listed_files()) == {"requirements.md", "seeds.json"}
    for name, expected in listed_files().items():
        raw = (DEMO_FIXTURE / name).read_bytes()
        assert b"\r\n" not in raw, f"{name} must be LF-normalized"
        assert sha256(raw).hexdigest() == expected, f"{name} hash mismatch"


def test_markdown_parser_yields_the_eight_requirements_in_document_order() -> None:
    raw = (DEMO_FIXTURE / "requirements.md").read_bytes()
    units = parse_markdown_or_text(document_type="markdown", raw=raw)
    assert tuple(unit.requirement_id for unit in units) == EXPECTED_REQUIREMENT_IDS
    assert [unit.ordinal for unit in units] == list(range(len(units)))


def test_rule_based_analyzer_reports_exactly_the_expected_findings() -> None:
    findings = analyzer_findings()
    assert findings == EXPECTED_FINDINGS
    assert not any("REQ-ORD-001" in requirements for requirements, _ in findings)


def test_every_seed_is_a_valid_generated_test_bound_to_a_real_finding() -> None:
    findings = analyzer_findings()
    seed_ids = [seed["seed_id"] for seed in seeds()]
    assert len(seed_ids) == len(set(seed_ids))
    for seed in seeds():
        binding = (tuple(sorted(seed["requirement_ids"])), seed["finding_category"])
        assert binding in findings, f"{seed['seed_id']} has no matching finding"
        validate_generated_test_case(
            {
                "schema_version": GENERATED_TEST_CASE_SCHEMA_VERSION,
                "id": str(uuid5(NAMESPACE, f"case:{seed['seed_id']}")),
                "title": f"Seed {seed['seed_id']}",
                "kind": seed["kind"],
                "source_finding_id": str(uuid5(NAMESPACE, f"finding:{binding}")),
                "citation_ids": [str(uuid5(NAMESPACE, f"cite:{seed['seed_id']}"))],
                "request": seed["request"],
                "assertions": seed["assertions"],
            }
        )


def test_every_seed_targets_a_mock_operation_and_holds_against_it() -> None:
    for seed in seeds():
        request = seed["request"]
        app = create_mock_order_app()
        scope = {"type": "http", "method": request["method"], "path": request["path"]}
        assert any(route.matches(scope)[0] is Match.FULL for route in app.routes), (
            f"{seed['seed_id']} targets an operation the mock does not implement"
        )

        with TestClient(app) as client:
            response = client.request(
                request["method"],
                request["path"],
                headers={item["name"]: item["value"] for item in request["headers"]},
                json=request["json_body"],
            )
        body = response.json()
        for assertion in seed["assertions"]:
            if assertion["target"] == "status_code":
                assert response.status_code == assertion["expected_value"]
                continue
            assert assertion["target"] == "json_body"
            found, value = json_pointer(body, assertion["selector"])
            assert found, f"{seed['seed_id']}: {assertion['selector']} missing"
            if assertion["operator"] == "equals":
                assert value == assertion["expected_value"]


def test_demo_files_carry_no_url_email_key_or_foreign_identifier() -> None:
    for path in demo_files():
        text = path.read_text(encoding="utf-8")
        assert not URL_PATTERN.search(text), f"URL in {path.name}"
        assert not EMAIL_PATTERN.search(text), f"e-mail address in {path.name}"
        assert not KEY_PATTERN.search(text), f"key-like string in {path.name}"
        for match in UUID_PATTERN.findall(text):
            assert match.startswith(SYNTHETIC_UUID_PREFIX), (
                f"non-synthetic identifier in {path.name}"
            )


def test_demo_files_do_not_reference_evaluation_or_fixture_paths() -> None:
    for path in demo_files():
        text = path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_PATH_FRAGMENTS:
            assert fragment not in text, f"{fragment} referenced in {path.name}"
