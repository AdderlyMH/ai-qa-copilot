from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import cast

import pytest

from ai_qa_copilot_api import informed_run_provenance as provenance_module
from ai_qa_copilot_api.b1_reference_assembly_inputs import (
    B1ReferenceAssemblyInputRejected,
    load_b1_reference_assembly_input,
)
from ai_qa_copilot_api.c1_evaluation_model import load_c1_pricing
from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_run_provenance import (
    EvaluationRunProvenanceRejected,
    build_c1_run_provenance,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationObservation,
    run_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_spend_control import (
    SpendLimits,
    estimate_input_tokens,
)
from ai_qa_copilot_api.informed_baseline import (
    DEFAULT_INFORMED_CONFIG_PATH,
    InformedBaselineExecutor,
    load_informed_baseline_config,
)
from ai_qa_copilot_api.informed_claude_evaluation_model import (
    CLAUDE_INFORMED_CALIBRATION,
    InformedClaudeModel,
)
from ai_qa_copilot_api.informed_run_provenance import (
    INFORMED_DEVELOPER_TEXT_SHA256,
    INFORMED_PROMPT_CONFIG_SHA256,
    INFORMED_SCHEMA_SHA256,
    InformedRunProvenance,
    build_informed_run_provenance,
    write_informed_run_provenance,
)
from ai_qa_copilot_api.model_gateway import (
    ANTHROPIC_MESSAGES_URL,
    C1_MODEL_ID,
    AnthropicGatewaySettings,
)
from ai_qa_copilot_api.naive_baseline import B0_SIDE_EFFECTS


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from record_informed_evaluation_provenance import (  # noqa: E402
    main as record_informed_provenance_main,
)
from test_evaluation_run_provenance import c1_run  # noqa: E402

V2_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v2.yaml"
V3_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v3.yaml"
CONFIGURATION = ROOT / DEFAULT_INFORMED_CONFIG_PATH
PRICING = ROOT / "fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml"
B0_CONFIGURATION = ROOT / "fixtures/benchmark/baselines/b0-naive-single-prompt.v1.yaml"
COMMIT = "0" * 39 + "2"
API_KEY = "test-anthropic-key-not-real"
OUTPUT_MARKER = "MARKER-5d1e"
CASE_IDS = ("EVAL-001", "EVAL-025")
MAX_CALL = 100_000
MAX_RUN = 200_000


class FakeTransport:
    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        assert url == ANTHROPIC_MESSAGES_URL
        messages = cast(list[dict[str, list[dict[str, str]]]], body["messages"])
        output_config = cast(dict[str, dict[str, object]], body["output_config"])
        schema = json.dumps(output_config["format"]["schema"], separators=(",", ":"))
        characters = (
            len(cast(str, body["system"]))
            + len(messages[0]["content"][0]["text"])
            + len(schema)
        )
        estimate = estimate_input_tokens(characters, CLAUDE_INFORMED_CALIBRATION)
        actual = int(
            (Decimal(estimate) * Decimal("0.7")).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        output = {
            "boundary": "analysis_only",
            "ground_truth_ids": ["GT-FIND-001"],
            "source_references": [f"REQ-BASE-001#REQ-{OUTPUT_MARKER}#statement"],
        }
        return {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": C1_MODEL_ID,
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(output)}],
            "usage": {"input_tokens": actual, "output_tokens": 300},
        }


class ZeroCostExecutor:
    def execute(self, case: EvaluationCase) -> EvaluationObservation:
        return EvaluationObservation(
            boundary="analysis_only",
            side_effects=dict(B0_SIDE_EFFECTS),
            ground_truth_ids=(),
            source_references=(),
            cost=0,
        )


def informed_run(artifacts: Path) -> tuple[Path, Path]:
    """Run two v3 cases through the real informed Claude model with a fake transport."""

    artifacts.mkdir(parents=True, exist_ok=True)
    ledger_path = artifacts / "informed-ledger.jsonl"
    model = InformedClaudeModel(
        settings=AnthropicGatewaySettings(api_key=API_KEY),
        pricing=load_c1_pricing(PRICING),
        limits=SpendLimits(max_call_microusd=MAX_CALL, max_run_microusd=MAX_RUN),
        ledger_path=ledger_path,
        configuration=load_informed_baseline_config(CONFIGURATION),
        repository_root=ROOT,
        transport=FakeTransport(),
    )
    report = run_evaluation_cases(
        load_evaluation_case_suite(V3_FIXTURE),
        fixture_path=V3_FIXTURE,
        repository_root=ROOT,
        executor=InformedBaselineExecutor(
            configuration=load_informed_baseline_config(CONFIGURATION),
            repository_root=ROOT,
            model=model,
        ),
        case_ids=CASE_IDS,
        max_expected_cost=0.20,
        max_concurrency=1,
    )
    run_path = artifacts / "informed-run.json"
    run_path.write_text(report.as_json(), encoding="utf-8")
    return run_path, ledger_path


def build(
    run_path: Path,
    ledger_paths: tuple[Path, ...],
    *,
    fixture: Path = V3_FIXTURE,
    configuration: Path = CONFIGURATION,
    git_commit: str = COMMIT,
    max_call: int = MAX_CALL,
    max_run: int = MAX_RUN,
) -> InformedRunProvenance:
    return build_informed_run_provenance(
        run_report_path=run_path,
        fixture_path=fixture,
        pricing_path=PRICING,
        configuration_path=configuration,
        ledger_paths=ledger_paths,
        repository_root=ROOT,
        git_commit=git_commit,
        max_call_cost_microusd=max_call,
        max_run_cost_microusd=max_run,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tampered_ledger(ledger_path: Path, **changes: object) -> Path:
    records = [json.loads(line) for line in ledger_path.read_text("utf-8").splitlines()]
    records[0].update(changes)
    path = ledger_path.with_name("tampered-ledger.jsonl")
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return path


def cli_arguments(run_path: Path, ledger: Path, output: Path) -> list[str]:
    return [
        "--run-report",
        str(run_path),
        "--ledger",
        str(ledger),
        "--pricing",
        str(PRICING),
        "--git-commit",
        COMMIT,
        "--max-call-cost-usd",
        "0.1",
        "--max-run-cost-usd",
        "0.2",
        "--output",
        str(output),
        "--repository-root",
        str(ROOT),
    ]


# Content


def test_provenance_records_identity_hashes_calibration_limits_and_totals(
    tmp_path: Path,
) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    output = run_path.parent / "informed-run.provenance.json"

    write_informed_run_provenance(
        build(run_path, (ledger_path,)),
        repository_root=tmp_path,
        run_report_path=run_path,
        output_path=output,
    )

    recorded = json.loads(output.read_text(encoding="utf-8"))
    ledger_records = [
        json.loads(line) for line in ledger_path.read_text("utf-8").splitlines()
    ]
    assert recorded == {
        "schema_version": "evaluation-run-provenance/v2",
        "evidence_class": "provider-comparison-informed-development",
        "b1_evidence": False,
        "provider": "anthropic",
        "model_id": "claude-sonnet-5-5",
        "configuration_version": "C1/v1",
        "baseline_id": "INFORMED",
        "prompt_version": "informed-single-prompt/v1",
        "developer_text_sha256": INFORMED_DEVELOPER_TEXT_SHA256,
        "prompt_config_sha256": sha256(CONFIGURATION),
        "schema_sha256": INFORMED_SCHEMA_SHA256,
        "catalog_sha256": load_informed_baseline_config(CONFIGURATION).catalog_sha256,
        "characters_per_token": "2.1",
        "calibration_tolerance": "0.15",
        "max_calibration_ratio": max(r["calibration_ratio"] for r in ledger_records),
        "pricing_version": load_c1_pricing(PRICING).pricing_version,
        "pricing_sha256": sha256(PRICING),
        "suite_id": "evaluation-corpus/v3",
        "fixture_sha256": sha256(V3_FIXTURE),
        "run_report_sha256": sha256(run_path),
        "git_commit": COMMIT,
        "max_concurrency": 1,
        "max_expected_cost_usd": 0.2,
        "max_call_cost_microusd": MAX_CALL,
        "max_run_cost_microusd": MAX_RUN,
        "ledger_sha256": [sha256(ledger_path)],
        "ledger_call_count": 2,
        "ledger_charged_microusd": sum(r["charged_microusd"] for r in ledger_records),
    }


def test_pins_equal_the_current_files() -> None:
    assert INFORMED_PROMPT_CONFIG_SHA256 == sha256(CONFIGURATION)
    assert INFORMED_DEVELOPER_TEXT_SHA256 == (
        "f024095091f73da5c1762387164754b7b5ff92f3bdd482070fc8313354a378ee"
    )


def test_provenance_contains_no_prompt_output_or_credential(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    text = build(run_path, (ledger_path,)).as_json() + ledger_path.read_text("utf-8")

    for forbidden in (
        API_KEY,
        OUTPUT_MARKER,
        "You are a QA analyst",
        "GT-FIND-001",
        "analysis_only",
        "Identify contradictions",
    ):
        assert forbidden not in text


def test_provenance_is_always_not_b1_evidence(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")

    assert build(run_path, (ledger_path,)).b1_evidence is False


# Placement


def test_provenance_must_be_written_next_to_the_run_report(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")

    with pytest.raises(EvaluationRunProvenanceRejected, match="next to the run report"):
        write_informed_run_provenance(
            build(run_path, (ledger_path,)),
            repository_root=tmp_path,
            run_report_path=run_path,
            output_path=tmp_path / "elsewhere.json",
        )


def test_provenance_is_never_written_under_evaluation_reviews(tmp_path: Path) -> None:
    reviews = tmp_path / "evaluation" / "reviews"
    run_path, ledger_path = informed_run(reviews)

    with pytest.raises(EvaluationRunProvenanceRejected, match="evaluation/reviews"):
        write_informed_run_provenance(
            build(run_path, (ledger_path,)),
            repository_root=tmp_path,
            run_report_path=run_path,
            output_path=reviews / "provenance.json",
        )


def test_existing_provenance_is_never_replaced(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    output = run_path.parent / "provenance.json"
    output.write_text("existing evidence", encoding="utf-8")

    with pytest.raises(EvaluationRunProvenanceRejected, match="already exists"):
        write_informed_run_provenance(
            build(run_path, (ledger_path,)),
            repository_root=tmp_path,
            run_report_path=run_path,
            output_path=output,
        )

    assert output.read_text(encoding="utf-8") == "existing evidence"


# Refusals


def test_suite_other_than_v3_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")

    with pytest.raises(EvaluationRunProvenanceRejected, match="evaluation-corpus/v3"):
        build(run_path, (ledger_path,), fixture=V2_FIXTURE)


def test_fixture_that_is_not_the_committed_v3_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    altered = tmp_path / "altered-v3.yaml"
    altered.write_text(V3_FIXTURE.read_text("utf-8") + "# edited\n", encoding="utf-8")

    with pytest.raises(EvaluationRunProvenanceRejected, match="committed"):
        build(run_path, (ledger_path,), fixture=altered)


def test_run_report_for_another_fixture_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    report = json.loads(run_path.read_text("utf-8"))
    report["fixture_sha256"] = "0" * 64
    run_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(EvaluationRunProvenanceRejected):
        build(run_path, (ledger_path,))


def test_concurrent_run_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    concurrent = run_evaluation_cases(
        load_evaluation_case_suite(V3_FIXTURE),
        fixture_path=V3_FIXTURE,
        repository_root=ROOT,
        executor=ZeroCostExecutor(),
        case_ids=CASE_IDS,
        max_expected_cost=0.20,
        max_concurrency=2,
    )
    run_path.write_text(concurrent.as_json(), encoding="utf-8")

    with pytest.raises(EvaluationRunProvenanceRejected, match="max_concurrency 1"):
        build(run_path, (ledger_path,))


def test_ledger_with_another_schema_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    tampered = tampered_ledger(ledger_path, schema_version="c1-call-ledger/v1")

    with pytest.raises(EvaluationRunProvenanceRejected, match="does not match"):
        build(run_path, (tampered,))


def test_a_c1_b0_ledger_is_refused(tmp_path: Path) -> None:
    run_path, _ = informed_run(tmp_path / "artifacts")
    _, c1_ledger = c1_run(tmp_path / "c1")

    with pytest.raises(EvaluationRunProvenanceRejected, match="does not match"):
        build(run_path, (c1_ledger,))


def test_ledger_with_a_failed_call_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    tampered = tampered_ledger(ledger_path, outcome="failed", failure="invalid_output")

    with pytest.raises(EvaluationRunProvenanceRejected, match="failed call"):
        build(run_path, (tampered,))


def test_ledger_call_count_must_equal_the_selected_cases(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    lines = ledger_path.read_text("utf-8").splitlines()
    short = ledger_path.with_name("short-ledger.jsonl")
    short.write_text(lines[0] + "\n", encoding="utf-8")
    long = ledger_path.with_name("long-ledger.jsonl")
    long.write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")

    for ledger in (short, long):
        with pytest.raises(EvaluationRunProvenanceRejected, match="selected cases"):
            build(run_path, (ledger,))


def test_declared_limits_must_match_the_ledger(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")

    with pytest.raises(EvaluationRunProvenanceRejected, match="limits differ"):
        build(run_path, (ledger_path,), max_run=MAX_RUN + 1)
    with pytest.raises(EvaluationRunProvenanceRejected, match="limits differ"):
        build(run_path, (ledger_path,), max_call=MAX_CALL - 1)


def test_ledger_with_other_pricing_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    tampered = tampered_ledger(ledger_path, pricing_version="other/2026-01-01")

    with pytest.raises(EvaluationRunProvenanceRejected, match="does not match"):
        build(run_path, (tampered,))


def test_per_call_limit_above_the_v3_case_budget_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")

    with pytest.raises(EvaluationRunProvenanceRejected, match="per-case budget"):
        build(run_path, (ledger_path,), max_call=100_001, max_run=MAX_RUN)


@pytest.mark.parametrize("commit", ["", "abc", "G" * 40, "A" * 40, "0" * 39, "0" * 41])
def test_git_commit_must_be_a_full_sha(tmp_path: Path, commit: str) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")

    with pytest.raises(EvaluationRunProvenanceRejected, match="40-character"):
        build(run_path, (ledger_path,), git_commit=commit)


@pytest.mark.parametrize(
    ("pin", "label"),
    [
        ("INFORMED_DEVELOPER_TEXT_SHA256", "developer text"),
        ("INFORMED_PROMPT_CONFIG_SHA256", "prompt configuration"),
        ("INFORMED_SCHEMA_SHA256", "output schema"),
    ],
)
def test_prompt_hash_that_differs_from_the_pin_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pin: str, label: str
) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    monkeypatch.setattr(provenance_module, pin, "0" * 64)

    with pytest.raises(EvaluationRunProvenanceRejected, match=label):
        build(run_path, (ledger_path,))


def test_changed_prompt_config_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    changed = tmp_path / "config.yaml"
    changed.write_text(
        CONFIGURATION.read_text("utf-8").replace(
            "maximum_prompt_characters: 60000", "maximum_prompt_characters: 59999"
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationRunProvenanceRejected, match="prompt configuration"):
        build(run_path, (ledger_path,), configuration=changed)


def test_catalog_hash_that_differs_from_the_file_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    changed = tmp_path / "config.yaml"
    changed.write_text(
        CONFIGURATION.read_text("utf-8").replace(
            load_informed_baseline_config(CONFIGURATION).catalog_sha256, "0" * 64
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationRunProvenanceRejected, match="catalog"):
        build(run_path, (ledger_path,), configuration=changed)


# Cross-rejection


def test_b1_assembly_rejects_v2_provenance_as_assembly_input(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    output = run_path.parent / "provenance.json"
    write_informed_run_provenance(
        build(run_path, (ledger_path,)),
        repository_root=tmp_path,
        run_report_path=run_path,
        output_path=output,
    )

    with pytest.raises(B1ReferenceAssemblyInputRejected):
        load_b1_reference_assembly_input(output)


def test_the_v1_recorder_rejects_an_informed_ledger(tmp_path: Path) -> None:
    informed_run(tmp_path / "informed")
    informed_ledger = tmp_path / "informed" / "informed-ledger.jsonl"
    c1_run_path, _ = c1_run(tmp_path / "c1")

    with pytest.raises(EvaluationRunProvenanceRejected, match="does not match"):
        build_c1_run_provenance(
            run_report_path=c1_run_path,
            fixture_path=V2_FIXTURE,
            pricing_path=PRICING,
            b0_configuration_path=B0_CONFIGURATION,
            ledger_paths=(informed_ledger,),
            git_commit=COMMIT,
            max_call_cost_microusd=90_000,
            max_run_cost_microusd=180_000,
        )


# CLI


def test_cli_records_provenance_next_to_the_run(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    output = run_path.parent / "informed-run.provenance.json"

    exit_code = record_informed_provenance_main(
        cli_arguments(run_path, ledger_path, output)
    )

    assert exit_code == 0
    recorded = json.loads(output.read_text(encoding="utf-8"))
    assert recorded["b1_evidence"] is False
    assert recorded["schema_version"] == "evaluation-run-provenance/v2"


def test_cli_refuses_a_bad_ledger_without_writing(tmp_path: Path) -> None:
    run_path, ledger_path = informed_run(tmp_path / "artifacts")
    tampered = tampered_ledger(ledger_path, outcome="failed", failure="invalid_output")
    output = run_path.parent / "informed-run.provenance.json"

    with pytest.raises(SystemExit, match="failed call"):
        record_informed_provenance_main(cli_arguments(run_path, tampered, output))

    assert not output.exists()
