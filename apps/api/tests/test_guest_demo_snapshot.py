"""Offline contract tests for the guest-demo snapshot build (ADR-019, INFRA-011)."""

from __future__ import annotations

import ast
from dataclasses import replace
from functools import cache
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess  # nosec B404 - runs this repository's own build in a child
import sys
from typing import Any

from fastapi.testclient import TestClient
import pytest

from ai_qa_copilot_api.guest_demo_build import DemoBuild, build_demo
from ai_qa_copilot_api.guest_demo_snapshot import (
    CONTENT_CLASS,
    MAX_EXCERPT_CHARACTERS,
    NOT_A_MODEL_RESULT,
    PROVENANCE_KEYS,
    VIEWER_FILES,
    SnapshotRejected,
    project_snapshot,
    redact_excerpt,
    render_snapshot,
    validate_snapshot_schema,
)
from ai_qa_copilot_api.mock_order_api import SEEDED_CONFIRMED_ORDER_ID
from ai_qa_copilot_api.requirements_analysis import ANALYZER_VERSION
from ai_qa_copilot_api.test_generation import GROUNDED_TEST_GENERATOR_VERSION


ROOT = Path(__file__).resolve().parents[3]
DEMO_FIXTURE = ROOT / "demo/fixture"
VIEWER_DIR = ROOT / "demo/viewer"
BUILD_OUTPUT_FILES = ("snapshot.json", *VIEWER_FILES, "manifest.json")
BUILD_MODULES = (
    ROOT / "apps/api/src/ai_qa_copilot_api/guest_demo_build.py",
    ROOT / "apps/api/src/ai_qa_copilot_api/guest_demo_snapshot.py",
    ROOT / "apps/api/src/ai_qa_copilot_api/guest_demo_cli.py",
    ROOT / "apps/api/src/ai_qa_copilot_api/guest_demo_publish.py",
    ROOT / "scripts/build_demo_snapshot.py",
    ROOT / "scripts/publish_demo_site.py",
)
FORBIDDEN_MODULE_NAMES = frozenset(
    {
        "analysis_runs",
        "c1_evaluation_model",
        "informed_baseline",
        "informed_claude_evaluation_model",
        "informed_openai_evaluation_model",
        "model_gateway",
        "naive_baseline",
        "openai_informed_evaluation_adapter",
    }
)
FORBIDDEN_PATH_FRAGMENTS = ("evaluation/", "fixtures/")

# Prelude for every child interpreter: audits sockets and file writes, and
# ``report(**extra)`` prints the audit as the child's last line of JSON.
AUDIT_HOOK = """
import json, os, sys
events = []
descriptor_reopens = []
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
def audit(name, args):
    if name.startswith("socket."):
        events.append([name, repr(args)])
    elif name == "open":
        path, mode, flags = args
        if isinstance(path, int):
            # Wrapping an already-open descriptor creates no file; a path that
            # created one was audited by its own os.open or open event.
            descriptor_reopens.append(path)
            return
        if isinstance(mode, str):
            writes = bool(set(mode) & set("wax+"))
        else:
            writes = isinstance(flags, int) and bool(flags & WRITE_FLAGS)
        if writes:
            events.append([name, os.fsdecode(path)])
sys.addaudithook(audit)
def report(**extra):
    print(json.dumps({"events": events, "descriptor_reopens": descriptor_reopens, **extra}))
"""

# Builds and writes the snapshot in a fresh interpreter under the audit hook.
CHILD_BUILD = (
    AUDIT_HOOK
    + """
from pathlib import Path
from ai_qa_copilot_api.guest_demo_build import build_demo
from ai_qa_copilot_api.guest_demo_snapshot import (
    load_viewer, render_snapshot, write_snapshot,
)
output = render_snapshot(
    build_demo(Path(sys.argv[1])), load_viewer(Path(sys.argv[3]))
)
write_snapshot(output, Path(sys.argv[2]))
report(content_hash=output.content_hash, modules=sorted(sys.modules))
"""
)


@cache
def demo_build() -> DemoBuild:
    return build_demo(DEMO_FIXTURE)


@cache
def snapshot_bytes() -> bytes:
    return render_snapshot(demo_build()).snapshot_bytes


def snapshot() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(snapshot_bytes())
    return payload


def run_child(code: str, workdir: Path, *args: str) -> dict[str, Any]:
    """Run ``code`` in a fresh interpreter and return its final JSON line."""

    completed = subprocess.run(  # nosec B603 - fixed argv, no shell
        [
            sys.executable,
            "-B",  # no bytecode caches: only the child's own writes are audited
            "-W",
            "ignore",
            "-c",
            code,
            *args,
        ],
        cwd=workdir,
        capture_output=True,
        check=True,
        text=True,
        timeout=180,
    )
    result: dict[str, Any] = json.loads(completed.stdout.strip().splitlines()[-1])
    result["workdir"] = workdir
    return result


def reported_writes(child: dict[str, Any]) -> set[Path]:
    """Resolve every write the audit hook reported, relative to the child cwd."""

    workdir: Path = child["workdir"]
    return {
        (path if path.is_absolute() else workdir / path).resolve()
        for path in (Path(event[1]) for event in child["events"] if event[0] == "open")
    }


def expected_build_writes(output_dir: Path) -> set[Path]:
    """The only files a build may create: the snapshot, the viewer, the manifest."""

    return {(output_dir / name).resolve() for name in BUILD_OUTPUT_FILES}


@pytest.fixture(scope="module")
def child_build(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    workdir = tmp_path_factory.mktemp("child-cwd")
    output_dir = tmp_path_factory.mktemp("child-out") / "snapshot"
    result = run_child(
        CHILD_BUILD, workdir, str(DEMO_FIXTURE), str(output_dir), str(VIEWER_DIR)
    )
    result["output_dir"] = output_dir
    return result


def forbidden_module(name: str) -> bool:
    parts = name.split(".")
    return any(
        part.startswith("evaluation")
        or part.startswith("b1_")
        or "provenance" in part
        or part in FORBIDDEN_MODULE_NAMES
        for part in parts
    )


def test_two_builds_in_one_process_are_byte_identical() -> None:
    first = render_snapshot(build_demo(DEMO_FIXTURE))
    second = render_snapshot(build_demo(DEMO_FIXTURE))
    assert first.snapshot_bytes == second.snapshot_bytes
    assert first.manifest_bytes == second.manifest_bytes
    assert first.content_hash == sha256(first.snapshot_bytes).hexdigest()


def test_a_fresh_interpreter_build_matches(child_build: dict[str, Any]) -> None:
    output_dir: Path = child_build["output_dir"]
    written = (output_dir / "snapshot.json").read_bytes()
    assert written == snapshot_bytes()
    assert child_build["content_hash"] == sha256(written).hexdigest()
    manifest = json.loads((output_dir / "manifest.json").read_bytes())
    assert manifest["content_hash"] == child_build["content_hash"]
    assert manifest["files"][0] == {
        "path": "snapshot.json",
        "sha256": child_build["content_hash"],
        "bytes": len(written),
    }
    for entry in manifest["files"][1:]:
        data = (output_dir / entry["path"]).read_bytes()
        assert entry == {
            "path": entry["path"],
            "sha256": sha256(data).hexdigest(),
            "bytes": len(data),
        }


def test_no_internal_identifier_or_timestamp_reaches_the_output() -> None:
    build = demo_build()
    text = snapshot_bytes().decode("ascii")
    report = build.snapshot.report
    expected_internal = {
        str(report.id),
        str(report.project_id),
        *(str(citation.id) for citation in build.citations),
        *(str(citation.document_version_id) for citation in build.citations),
        *(str(claim.id) for section in report.sections for claim in section.claims),
        *(str(item.id) for item in report.evidence_catalog),
        *(str(value) for value in report.provenance.requirement_analysis_run_ids),
        *(str(value) for value in report.provenance.execution_job_ids),
        report.created_at.isoformat(),
    }
    assert expected_internal <= build.internal_identifiers
    leaked = sorted(
        item for item in build.internal_identifiers if item and item in text
    )
    assert leaked == []
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text)
    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text
    )


def test_output_holds_only_allowlisted_keys() -> None:
    payload = snapshot()
    validate_snapshot_schema(payload)
    assert payload["content_class"] == CONTENT_CLASS

    extra = json.loads(snapshot_bytes())
    extra["sections"][0]["claims"][0]["project_id"] = "anything"
    with pytest.raises(SnapshotRejected):
        validate_snapshot_schema(extra)

    missing_marker = json.loads(snapshot_bytes())
    missing_marker["content_class"] = "evaluation"
    with pytest.raises(SnapshotRejected):
        validate_snapshot_schema(missing_marker)


def test_excerpts_equal_the_fixture_requirement_lines() -> None:
    lines = (DEMO_FIXTURE / "requirements.md").read_text(encoding="utf-8").splitlines()
    expected = [
        (number, match.group(1))
        for number, line in enumerate(lines, start=1)
        if (match := re.fullmatch(r"REQ-ORD-\d{3}: (.+)", line))
    ]
    excerpts = snapshot()["excerpts"]
    assert [(item["line_start"], item["text"]) for item in excerpts] == expected
    assert all(item["line_end"] == item["line_start"] for item in excerpts)
    assert {item["location_kind"] for item in excerpts} == {"markdown_lines"}


def test_redaction_replaces_identifiers_and_refuses_secrets_and_long_text() -> None:
    # Canary values are assembled at run time so no literal sits in the repo.
    email = "someone" + "@" + "mail.invalid"
    url = "https" + "://" + "orders.invalid/path"
    access_key = "AKIA" + "Q" * 16
    assert redact_excerpt(f"Contact {email} today") == "Contact [redacted-email] today"
    assert redact_excerpt(f"See {url} now") == "See [redacted-url] now"
    assert redact_excerpt("Call +1 555 010 0199") == "Call [redacted-phone]"
    assert redact_excerpt("Host api.orders.invalid") == "Host [redacted-host]"
    plain = "The order list must load fast for large accounts."
    assert redact_excerpt(plain) == plain

    for refused in (
        f"Use {access_key} for access",
        "password" + "=" + "hunter22",
        "x" * (MAX_EXCERPT_CHARACTERS + 1),
        "line\twith a tab",
    ):
        with pytest.raises(SnapshotRejected):
            redact_excerpt(refused)
    assert redact_excerpt("y" * MAX_EXCERPT_CHARACTERS) == "y" * MAX_EXCERPT_CHARACTERS


def test_unknown_report_text_refuses_the_build() -> None:
    build = demo_build()
    report = build.snapshot.report
    first = report.sections[0]
    injected = replace(
        first,
        claims=(replace(first.claims[0], statement="<script>unknown</script>"),),
    )
    tampered = replace(
        build,
        snapshot=replace(
            build.snapshot,
            report=replace(report, sections=(injected, *report.sections[1:])),
        ),
    )
    with pytest.raises(SnapshotRejected):
        project_snapshot(tampered)


def test_provenance_statement_is_complete_and_says_not_a_model_result() -> None:
    provenance = snapshot()["provenance"]
    assert set(provenance) == PROVENANCE_KEYS
    assert provenance["not_a_model_result"] is True
    assert provenance["statement"] == NOT_A_MODEL_RESULT
    assert provenance["analyzer_version"] == ANALYZER_VERSION
    assert provenance["test_generator_version"] == GROUNDED_TEST_GENERATOR_VERSION
    assert "no model" in provenance["findings"]
    assert (
        "one per parsed requirement unit, in document order" in provenance["citations"]
    )
    assert "author-written seeds" in provenance["test_proposals"]
    assert "in-process synthetic mock target" in provenance["execution"]
    assert provenance["failure_analysis"] == "Deterministic."
    assert "content hash" in provenance["publication"]


def test_traceability_is_derived_labelled_and_resolves() -> None:
    payload = snapshot()
    traceability = payload["traceability"]
    assert traceability["label"].startswith("Derived from the evidence links")
    assert traceability["report_section_state"] == "not_available"
    assert "not available in v1" in traceability["report_section_note"]

    sections = {section["name"]: section for section in payload["sections"]}
    assert sections["traceability"]["state"] == "not_available"
    finding_ids = {claim["public_id"] for claim in sections["findings"]["claims"]}
    test_ids = {claim["public_id"] for claim in sections["generated_tests"]["claims"]}
    excerpt_ids = {excerpt["public_id"] for excerpt in payload["excerpts"]}

    rows = traceability["rows"]
    assert {row["finding"] for row in rows} == finding_ids
    assert len(finding_ids) == 14 and len(test_ids) == 5
    assert {test for row in rows for test in row["test_proposals"]} == test_ids
    for row in rows:
        assert row["citation_excerpts"] and set(row["citation_excerpts"]) <= excerpt_ids


def test_each_seed_ran_against_its_own_fresh_mock() -> None:
    runs = demo_build().seed_runs
    assert len(runs) == 5
    assert len({id(run.mock_app) for run in runs}) == len(runs)
    assert {run.outcome for run in runs} == {"succeeded"}

    statuses = {}
    for run in runs:
        with TestClient(run.mock_app) as client:
            response = client.get(f"/orders/{SEEDED_CONFIRMED_ORDER_ID}")
        statuses[run.seed_id] = response.json()["status"]
    # Only the cancel seed's own mock saw the cancel; the others stayed pristine.
    assert statuses.pop("SEED-ORD-004-STATE") == "CANCELED"
    assert set(statuses.values()) == {"CONFIRMED"}


def test_build_modules_import_no_evaluation_code_and_name_no_evaluation_path() -> None:
    for path in BUILD_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [alias.name for alias in node.names]
            else:
                names = []
            assert not any(forbidden_module(name) for name in names), path.name
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for fragment in FORBIDDEN_PATH_FRAGMENTS:
                    assert fragment not in node.value, f"{fragment} in {path.name}"


def test_a_fresh_build_loads_no_evaluation_or_model_module(
    child_build: dict[str, Any],
) -> None:
    loaded = [name for name in child_build["modules"] if forbidden_module(name)]
    assert loaded == []


def test_a_fresh_build_opens_no_network_connection(child_build: dict[str, Any]) -> None:
    lookups = {
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyname_ex",
        "socket.gethostbyaddr",
        "socket.sendto",
        "socket.sendmsg",
    }
    socket_events = [
        event for event in child_build["events"] if event[0].startswith("socket.")
    ]
    assert not [event for event in socket_events if event[0] in lookups]
    # asyncio's Windows event loop makes a loopback socket pair for each test
    # client; anything beyond loopback is a real network connection.
    for name, args in socket_events:
        if name in {"socket.connect", "socket.bind"}:
            assert "'127.0.0.1'" in args or "'::1'" in args, args


def test_a_fresh_build_writes_only_into_its_output_directory(
    child_build: dict[str, Any],
) -> None:
    output_dir: Path = child_build["output_dir"]
    assert reported_writes(child_build) == expected_build_writes(output_dir)
    assert sorted(item.name for item in output_dir.iterdir()) == sorted(
        BUILD_OUTPUT_FILES
    )
    assert list(child_build["workdir"].iterdir()) == []
    assert json.loads((output_dir / "snapshot.json").read_bytes())["content_class"] == (
        CONTENT_CLASS
    )


# Self-tests of the write-audit hook: each child runs the real AUDIT_HOOK.
UNEXPECTED_WRITES_IN_OUTPUT = (
    AUDIT_HOOK
    + """
from pathlib import Path
output_dir = Path(sys.argv[1])
output_dir.mkdir(parents=True)
with open(output_dir / "unexpected.txt", "w") as handle:
    handle.write("x")
os.close(os.open(output_dir / "unexpected.bin", os.O_CREAT | os.O_WRONLY))
report()
"""
)
WRITE_OUTSIDE_OUTPUT = (
    AUDIT_HOOK
    + """
from pathlib import Path
with open(Path(sys.argv[1]), "w") as handle:
    handle.write("x")
report()
"""
)
DESCRIPTOR_REOPEN_ONLY = (
    AUDIT_HOOK
    + """
read_fd, write_fd = os.pipe()
with open(write_fd, "w") as handle:
    handle.write("")
os.close(read_fd)
report(write_fd=write_fd)
"""
)


def test_audit_hook_reports_unexpected_files_written_into_the_output_directory(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    output_dir = tmp_path / "out"
    child = run_child(UNEXPECTED_WRITES_IN_OUTPUT, workdir, str(output_dir))
    writes = reported_writes(child)
    assert writes == {
        (output_dir / "unexpected.txt").resolve(),
        (output_dir / "unexpected.bin").resolve(),
    }
    assert writes != expected_build_writes(output_dir)


def test_audit_hook_reports_a_write_outside_the_output_directory(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    outside = tmp_path / "elsewhere.txt"
    child = run_child(WRITE_OUTSIDE_OUTPUT, workdir, str(outside))
    assert reported_writes(child) == {outside.resolve()}
    assert not reported_writes(child) <= expected_build_writes(tmp_path / "out")


def test_audit_hook_ignores_a_reopened_descriptor_that_writes_no_new_file(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    child = run_child(DESCRIPTOR_REOPEN_ONLY, workdir)
    assert reported_writes(child) == set()
    assert child["descriptor_reopens"] == [child["write_fd"]]
    assert list(workdir.iterdir()) == []
