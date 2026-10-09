"""The informed-v4 comparison report: verification, tables and determinism.

Synthetic inputs only: run folders are produced by the real informed models
with fake transports, the real runner, scorer and provenance recorder. No
provider or network call.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from ai_qa_copilot_api.c1_evaluation_model import load_c1_pricing
from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_runner import run_evaluation_cases
from ai_qa_copilot_api.evaluation_scoring import (
    load_ground_truth_catalog,
    score_evaluation_run,
)
from ai_qa_copilot_api.evaluation_spend_control import SpendLimits
from ai_qa_copilot_api.informed_baseline import (
    DEFAULT_INFORMED_CONFIG_PATH,
    InformedBaselineExecutor,
    load_informed_baseline_config,
)
from ai_qa_copilot_api.informed_claude_evaluation_model import InformedClaudeModel
from ai_qa_copilot_api.informed_openai_evaluation_model import (
    InformedOpenAIModel,
    load_openai_informed_pricing,
)
from ai_qa_copilot_api.informed_run_provenance import (
    build_informed_run_provenance,
    write_informed_run_provenance,
)
from ai_qa_copilot_api.model_gateway import AnthropicGatewaySettings
from ai_qa_copilot_api.openai_informed_evaluation_adapter import (
    OpenAIInformedSettings,
)


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import report_informed_v4_comparison as report  # noqa: E402
from test_informed_openai_evaluation_model import (  # noqa: E402
    estimate_transport as openai_transport,
)
from test_informed_run_provenance import (  # noqa: E402
    FakeTransport as ClaudeTransport,
)


V4_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v4.yaml"
CATALOG = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"
CONFIGURATION = ROOT / DEFAULT_INFORMED_CONFIG_PATH
COMMIT = "0" * 39 + "6"
# One requirement case, the largest prompt, a policy case and a negative control.
CASE_IDS = ("EVAL-101", "EVAL-111", "EVAL-120", "EVAL-128")
CALL_LIMIT = 110_000


def write_lf(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def make_run_folder(runs_root: Path, label: str, case_ids: tuple[str, ...]) -> None:
    """Produce one run folder exactly as the workflow would (fake transports)."""

    provider = report.FOLDER_PROVIDER[label]
    scope = report.FOLDER_SCOPE[label]
    folder = runs_root / label
    folder.mkdir(parents=True)
    stem = f"informed-v4-{provider}-{scope}"
    ledger = folder / f"{stem}-ledger.jsonl"
    limits = SpendLimits(
        max_call_microusd=CALL_LIMIT, max_run_microusd=CALL_LIMIT * len(case_ids)
    )
    configuration = load_informed_baseline_config(CONFIGURATION)
    model: InformedClaudeModel | InformedOpenAIModel
    if provider == "anthropic":
        model = InformedClaudeModel(
            settings=AnthropicGatewaySettings(api_key="test-anthropic-key-not-real"),
            pricing=load_c1_pricing(ROOT / report.PROVIDER_PRICING[provider]),
            limits=limits,
            ledger_path=ledger,
            configuration=configuration,
            repository_root=ROOT,
            transport=ClaudeTransport(),
        )
    else:
        model = InformedOpenAIModel(
            settings=OpenAIInformedSettings(api_key="test-openai-key-not-real"),
            pricing=load_openai_informed_pricing(
                ROOT / report.PROVIDER_PRICING[provider]
            ),
            limits=limits,
            ledger_path=ledger,
            configuration=configuration,
            repository_root=ROOT,
            transport=openai_transport(scale=Decimal("0.5")),
        )
    suite = load_evaluation_case_suite(V4_FIXTURE)
    run = run_evaluation_cases(
        suite,
        fixture_path=V4_FIXTURE,
        repository_root=ROOT,
        executor=InformedBaselineExecutor(
            configuration=configuration, repository_root=ROOT, model=model
        ),
        case_ids=case_ids,
        max_expected_cost=float(Decimal("0.11") * len(case_ids)),
        max_concurrency=1,
    )
    run_path = folder / f"{stem}-run.json"
    write_lf(run_path, run.as_json())
    if scope != "probe":
        score = score_evaluation_run(
            suite,
            run,
            load_ground_truth_catalog(CATALOG),
            case_fixture_path=V4_FIXTURE,
            ground_truth_path=CATALOG,
        )
        write_lf(folder / f"{stem}-score.json", score.as_json())
    write_informed_run_provenance(
        build_informed_run_provenance(
            run_report_path=run_path,
            fixture_path=V4_FIXTURE,
            pricing_path=ROOT / report.PROVIDER_PRICING[provider],
            configuration_path=CONFIGURATION,
            ledger_paths=(ledger,),
            repository_root=ROOT,
            git_commit=COMMIT,
            max_call_cost_microusd=CALL_LIMIT,
            max_run_cost_microusd=CALL_LIMIT * len(case_ids),
            provider=provider,
        ),
        repository_root=runs_root,
        run_report_path=run_path,
        output_path=folder / f"{stem}-provenance.json",
    )


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("v4-runs")
    for label in report.FULL_RUNS:
        make_run_folder(root, label, CASE_IDS)
    make_run_folder(root, "probe-1", ("EVAL-111",))
    return root


@pytest.fixture
def runs_root(template: Path, tmp_path: Path) -> Iterator[Path]:
    copy = tmp_path / "runs"
    shutil.copytree(template, copy)
    yield copy


def render(runs_root: Path) -> str:
    return report.render_report(report.load_runs(runs_root, ROOT), ROOT)


def stem(label: str) -> str:
    return f"informed-v4-{report.FOLDER_PROVIDER[label]}-{report.FOLDER_SCOPE[label]}"


def path_of(runs_root: Path, label: str, kind: str) -> Path:
    return runs_root / label / f"{stem(label)}-{kind}"


# Rendering


def test_verified_runs_render_deterministic_lf_markdown(runs_root: Path) -> None:
    first = render(runs_root)
    second = render(runs_root)

    assert first == second
    assert "\r" not in first
    assert first.endswith("\n")
    assert "cases passed" not in first.lower()
    assert "side_effects" not in first
    assert "| claude-1 | Claude | development | 4 |" in first
    assert "| probe-1 | OpenAI | probe | 1 |" in first


def test_only_the_four_discriminating_checks_are_reported(runs_root: Path) -> None:
    text = render(runs_root)
    header = "| Run | Required IDs | No unexpected IDs | Source references | Boundary |"

    assert header in text
    for code in (
        "known_expected",
        "prohibited",
        "known_observed",
        "maximum_expected_cost",
    ):
        assert code not in text


def _counts_from_score(runs_root: Path, label: str) -> dict[str, tuple[int, int]]:
    suite = load_evaluation_case_suite(V4_FIXTURE)
    controls = {c.id for c in suite.cases if "negative_control" in c.tags}
    scores = json.loads(path_of(runs_root, label, "score.json").read_text("utf-8"))
    counts: dict[str, tuple[int, int]] = {}
    for code, _ in report.DISCRIMINATING_CHECKS:
        outcomes = [
            check["passed"]
            for score in scores["scores"]
            for check in score["checks"]
            if check["code"] == code
            and not (
                code in report.NOT_APPLICABLE_ON_CONTROLS
                and score["case_id"] in controls
            )
        ]
        counts[code] = (sum(outcomes), len(outcomes))
    return counts


@pytest.mark.parametrize("label", report.FULL_RUNS)
def test_run_totals_match_an_independent_count_of_the_score(
    runs_root: Path, label: str
) -> None:
    counts = _counts_from_score(runs_root, label)
    row = (
        f"| {label} | "
        + " | ".join(
            f"{counts[code][0]} of {counts[code][1]}"
            for code, _ in report.DISCRIMINATING_CHECKS
        )
        + " |"
    )

    assert row in render(runs_root)
    # Three non-control cases carry required IDs and references; all four carry
    # unexpected IDs and boundary.
    assert [counts[c][1] for c, _ in report.DISCRIMINATING_CHECKS] == [3, 4, 3, 4]


def test_categories_come_from_the_fixture_and_controls_are_separate(
    runs_root: Path,
) -> None:
    text = render(runs_root)
    section = text.split("### By category: claude-1", 1)[1].split("###", 1)[0]

    for category in (
        "requirement_quality",
        "requirement_openapi_consistency",
        "tool_planning_execution",
    ):
        assert f"| {category} | 1 |" in section
    control_row = next(
        line
        for line in section.splitlines()
        if line.startswith("| negative controls |")
    )
    cells = [cell.strip() for cell in control_row.strip("|").split("|")]
    assert cells[0:2] == ["negative controls", "1"]
    assert cells[2] == "n/a" and cells[4] == "n/a"
    assert "n/a" not in (cells[3], cells[5])
    assert section.index("| tool_planning_execution |") < section.index(
        "| negative controls |"
    )


def test_policy_cases_are_noted_as_structural(runs_root: Path) -> None:
    text = render(runs_root)

    assert "EVAL-120, EVAL-121, EVAL-122, EVAL-123, EVAL-124, EVAL-125" in text
    assert "fails by construction (structural)" in text


def test_stability_counts_identical_runs(runs_root: Path) -> None:
    text = render(runs_root)

    assert "| Claude | claude-1, claude-2 | 4 | 4 of 4 | 4 of 4 |" in text
    assert "| OpenAI | openai-1, openai-2 | 4 | 4 of 4 | 4 of 4 |" in text


def test_provider_differences_and_reference_misses_are_listed(runs_root: Path) -> None:
    text = render(runs_root)

    differ = text.split("### Where the providers differ", 1)[1].split("###", 1)[0]
    misses = text.split("### Reference misses", 1)[1].split("###", 1)[0]
    # Both fakes answer GT-FIND-001; they cite different references.
    assert "| none | n/a | n/a | n/a | n/a |" in differ
    assert "| claude-1 | EVAL-101 | `REQ-BASE-001#REQ-REFUND-001#AC-5` |" in misses
    assert "EVAL-128" not in misses


def test_cost_table_equals_the_ledger_sums(runs_root: Path) -> None:
    text = render(runs_root)
    for label in (*report.FULL_RUNS, "probe-1"):
        records = [
            json.loads(line)
            for line in path_of(runs_root, label, "ledger.jsonl")
            .read_text("utf-8")
            .splitlines()
        ]
        charged = sum(r["charged_microusd"] for r in records) / 1_000_000
        tokens = sum(r["actual_input_tokens"] for r in records)
        assert f"| {label} | " in text
        row = next(
            line
            for line in text.splitlines()
            if line.startswith(f"| {label} | ")
            and "USD" not in line
            and line.count("|") == 10
        )
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[3] == f"{charged:.6f}"
        assert cells[4] == str(tokens)
        if report.FOLDER_PROVIDER[label] == "anthropic":
            assert cells[6] == "n/a"


@pytest.mark.parametrize(
    ("expected", "cited", "flag"),
    [
        (
            "REQ-BASE-001#REQ-ORDER-006#statement",
            "REQ-BASE-001#REQ-ORDER-006#AC-3",
            True,
        ),
        (
            "REQ-BASE-001#REQ-ORDER-006#statement",
            "REQ-BASE-001#REQ-ORDER-003#AC-2",
            False,
        ),
        (
            "OAS-BASE-001#/paths/~1orders/post",
            "OAS-BASE-001#/paths/~1orders/post/description",
            True,
        ),
        ("OAS-BASE-001#/a/b/maximum", "OAS-BASE-001#/a/b", True),
        ("OAS-BASE-001#/a/b", "OAS-BASE-001#/a/bc", False),
        ("OAS-BASE-001#/a/b", "REQ-BASE-001#REQ-A-001#statement", False),
        ("OAS-BASE-001#/a/b", "OAS-BASE-001#absence:X", False),
        ("OAS-BASE-001#/a/b", "OAS-BASE-001#/a/b", False),
    ],
)
def test_granularity_flag(expected: str, cited: str, flag: bool) -> None:
    assert report.same_artifact_different_granularity(expected, cited) is flag


# Verification refusals


def _edit_json(path: Path, change: Callable[[dict[str, object]], None]) -> None:
    data = cast(dict[str, object], json.loads(path.read_text("utf-8")))
    change(data)
    write_lf(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _reseal_provenance(runs_root: Path, label: str) -> None:
    """Point the provenance at the current ledger bytes (to reach later checks)."""

    import hashlib

    digest = hashlib.sha256(
        path_of(runs_root, label, "ledger.jsonl").read_bytes()
    ).hexdigest()
    _edit_json(
        path_of(runs_root, label, "provenance.json"),
        lambda d: d.update(ledger_sha256=[digest]),
    )


def _append_space(path: Path) -> None:
    path.write_bytes(path.read_bytes() + b" ")


def _fail_first_call(runs_root: Path) -> None:
    path = path_of(runs_root, "claude-1", "ledger.jsonl")
    lines = path.read_text("utf-8").splitlines()
    first = json.loads(lines[0])
    first.update(outcome="failed", failure="invalid_output")
    write_lf(path, "\n".join([json.dumps(first, sort_keys=True), *lines[1:]]) + "\n")
    _reseal_provenance(runs_root, "claude-1")


def _flip_a_check(runs_root: Path) -> None:
    def flip(data: dict[str, object]) -> None:
        scores = cast(list[dict[str, object]], data["scores"])
        check = cast(list[dict[str, object]], scores[0]["checks"])[1]
        check["passed"] = not check["passed"]

    _edit_json(path_of(runs_root, "claude-1", "score.json"), flip)


REFUSALS: list[tuple[str, Callable[[Path], None], str]] = [
    (
        "ledger bytes",
        lambda r: _append_space(path_of(r, "claude-1", "ledger.jsonl")),
        "ledger SHA-256",
    ),
    (
        "run report bytes",
        lambda r: _append_space(path_of(r, "openai-1", "run.json")),
        "run-report SHA-256",
    ),
    (
        "score run hash",
        lambda r: _edit_json(
            path_of(r, "claude-2", "score.json"),
            lambda d: d.update(run_sha256="0" * 64),
        ),
        "score run_sha256",
    ),
    ("score not a re-score", _flip_a_check, "re-score"),
    (
        "b1 evidence",
        lambda r: _edit_json(
            path_of(r, "openai-2", "provenance.json"),
            lambda d: d.update(b1_evidence=True),
        ),
        "b1_evidence",
    ),
    (
        "fixture pin",
        lambda r: _edit_json(
            path_of(r, "claude-1", "provenance.json"),
            lambda d: d.update(fixture_sha256="0" * 64),
        ),
        "fixture_sha256",
    ),
    (
        "prompt pin",
        lambda r: _edit_json(
            path_of(r, "claude-1", "provenance.json"),
            lambda d: d.update(developer_text_sha256="0" * 64),
        ),
        "developer_text_sha256",
    ),
    (
        "provider",
        lambda r: _edit_json(
            path_of(r, "claude-1", "provenance.json"),
            lambda d: d.update(provider="openai"),
        ),
        "not anthropic",
    ),
    (
        "charged total",
        lambda r: _edit_json(
            path_of(r, "openai-1", "provenance.json"),
            lambda d: d.update(ledger_charged_microusd=1),
        ),
        "charged total",
    ),
    ("failed call", _fail_first_call, "failed call"),
    (
        "derived field",
        lambda r: _edit_json(
            path_of(r, "openai-1", "provenance.json"),
            lambda d: d.update(max_calibration_ratio=0.1),
        ),
        "differs from a rebuild",
    ),
    (
        "extra file",
        lambda r: write_lf(r / "claude-1" / "notes.txt", "x"),
        "unexpected files",
    ),
    (
        "missing score",
        lambda r: path_of(r, "openai-2", "score.json").unlink(),
        "missing",
    ),
    (
        "missing full run",
        lambda r: shutil.rmtree(r / "claude-2"),
        "Missing full run folder",
    ),
    (
        "probe with a score",
        lambda r: write_lf(r / "probe-1" / f"{stem('probe-1')}-score.json", "{}"),
        "unexpected files",
    ),
]


@pytest.mark.parametrize(
    ("tamper", "message"),
    [(tamper, message) for _, tamper, message in REFUSALS],
    ids=[name for name, *_ in REFUSALS],
)
def test_any_mismatch_refuses_the_report(
    runs_root: Path, tamper: Callable[[Path], None], message: str
) -> None:
    tamper(runs_root)

    with pytest.raises(report.ComparisonReportRejected, match=message):
        report.load_runs(runs_root, ROOT)


# CLI


def test_cli_writes_the_tables_and_refuses_bad_input(
    runs_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "tables.md"

    assert report.main(["--runs-root", str(runs_root), "--output", str(output)]) == 0
    assert output.read_bytes() == render(runs_root).encode("utf-8")

    _append_space(path_of(runs_root, "claude-1", "ledger.jsonl"))
    with pytest.raises(SystemExit, match="ledger SHA-256"):
        report.main(["--runs-root", str(runs_root), "--output", str(tmp_path / "x.md")])
