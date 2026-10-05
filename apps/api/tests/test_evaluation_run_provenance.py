from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_qa_copilot_api.b1_reference_assembly_inputs import (
    B1ReferenceAssemblyInputRejected,
    load_b1_measurements,
    load_b1_reference_assembly_input,
)
from ai_qa_copilot_api.c1_evaluation_model import (
    C1B0Model,
    C1SpendLimits,
    estimate_input_tokens,
    load_c1_pricing,
)
from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_run_provenance import (
    EvaluationRunProvenance,
    EvaluationRunProvenanceRejected,
    build_c1_run_provenance,
    write_c1_run_provenance,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationObservation,
    evaluation_run_from_json,
    run_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_scoring import (
    load_ground_truth_catalog,
    score_evaluation_run,
)
from ai_qa_copilot_api.model_gateway import (
    ANTHROPIC_MESSAGES_URL,
    C1_MODEL_ID,
    AnthropicGatewaySettings,
)
from ai_qa_copilot_api.naive_baseline import (
    B0_SIDE_EFFECTS,
    DEFAULT_B0_CONFIG_PATH,
    NaiveBaselineExecutor,
    load_naive_baseline_config,
)


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from assemble_b1_reference_run import main as assemble_b1_main  # noqa: E402
from record_evaluation_provenance import main as record_provenance_main  # noqa: E402


V1_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
V2_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v2.yaml"
GROUND_TRUTH = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"
PRICING = ROOT / "fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml"
B0_CONFIGURATION = ROOT / DEFAULT_B0_CONFIG_PATH
COMMIT = "0" * 39 + "1"
API_KEY = "test-anthropic-key-not-real"
OUTPUT_MARKER = "OUTPUT-MARKER-5d1e"
CASE_IDS = ("EVAL-001", "EVAL-025")
MAX_CALL_MICROUSD = 90_000
MAX_RUN_MICROUSD = 180_000


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
        messages = body["messages"]
        assert isinstance(messages, list)
        prompt = messages[0]["content"][0]["text"]
        return {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": C1_MODEL_ID,
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "boundary": OUTPUT_MARKER,
                            "ground_truth_ids": [],
                            "source_references": [],
                        }
                    ),
                }
            ],
            "usage": {
                "input_tokens": estimate_input_tokens(prompt),
                "output_tokens": 300,
            },
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


def c1_run(artifacts: Path) -> tuple[Path, Path]:
    """Run two v2 cases through the real C1 model with a fake transport."""

    artifacts.mkdir(parents=True, exist_ok=True)
    ledger_path = artifacts / "c1-ledger.jsonl"
    model = C1B0Model(
        settings=AnthropicGatewaySettings(api_key=API_KEY),
        pricing=load_c1_pricing(PRICING),
        limits=C1SpendLimits(
            max_call_microusd=MAX_CALL_MICROUSD,
            max_run_microusd=MAX_RUN_MICROUSD,
        ),
        ledger_path=ledger_path,
        transport=FakeTransport(),
    )
    report = run_evaluation_cases(
        load_evaluation_case_suite(V2_FIXTURE),
        fixture_path=V2_FIXTURE,
        repository_root=ROOT,
        executor=NaiveBaselineExecutor(
            configuration=load_naive_baseline_config(B0_CONFIGURATION),
            repository_root=ROOT,
            model=model,
        ),
        case_ids=CASE_IDS,
        max_expected_cost=0.18,
        max_concurrency=1,
    )
    run_path = artifacts / "c1-run.json"
    run_path.write_text(report.as_json(), encoding="utf-8")
    return run_path, ledger_path


def build(
    run_path: Path,
    ledger_path: Path,
    *,
    fixture: Path = V2_FIXTURE,
    git_commit: str = COMMIT,
    max_call: int = MAX_CALL_MICROUSD,
    max_run: int = MAX_RUN_MICROUSD,
) -> EvaluationRunProvenance:
    return build_c1_run_provenance(
        run_report_path=run_path,
        fixture_path=fixture,
        pricing_path=PRICING,
        b0_configuration_path=B0_CONFIGURATION,
        ledger_paths=(ledger_path,),
        git_commit=git_commit,
        max_call_cost_microusd=max_call,
        max_run_cost_microusd=max_run,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Provenance content


def test_provenance_records_c1_identity_hashes_limits_and_no_content(
    tmp_path: Path,
) -> None:
    run_path, ledger_path = c1_run(tmp_path / "artifacts")
    output = tmp_path / "artifacts" / "c1-run.provenance.json"

    provenance = build(run_path, ledger_path)
    write_c1_run_provenance(
        provenance,
        repository_root=tmp_path,
        run_report_path=run_path,
        output_path=output,
    )

    recorded = json.loads(output.read_text(encoding="utf-8"))
    ledger_records = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    assert recorded == {
        "schema_version": "evaluation-run-provenance/v1",
        "evidence_class": "c1-provider-comparison",
        "b1_evidence": False,
        "provider": "anthropic",
        "model_id": "claude-sonnet-5-5",
        "configuration_version": "C1/v1",
        "prompt_version": "b0-single-prompt/v1",
        "b0_configuration_sha256": sha256(B0_CONFIGURATION),
        "pricing_version": (
            "anthropic-claude-sonnet-5-5/2026-10-04/standard-global-no-inference-geo"
        ),
        "pricing_sha256": sha256(PRICING),
        "suite_id": "evaluation-corpus/v2",
        "fixture_sha256": sha256(V2_FIXTURE),
        "run_report_sha256": sha256(run_path),
        "git_commit": COMMIT,
        "max_concurrency": 1,
        "max_expected_cost_usd": 0.18,
        "max_call_cost_microusd": MAX_CALL_MICROUSD,
        "max_run_cost_microusd": MAX_RUN_MICROUSD,
        "ledger_sha256": [sha256(ledger_path)],
        "ledger_call_count": 2,
        "ledger_charged_microusd": sum(
            record["charged_microusd"] for record in ledger_records
        ),
    }
    raw = output.read_text(encoding="utf-8")
    for forbidden in (OUTPUT_MARKER, API_KEY, "Identify", "You are a general"):
        assert forbidden not in raw


# Placement


def test_provenance_must_be_written_next_to_the_run_report(tmp_path: Path) -> None:
    run_path, ledger_path = c1_run(tmp_path / "artifacts")
    (tmp_path / "elsewhere").mkdir()

    with pytest.raises(EvaluationRunProvenanceRejected, match="next to the run"):
        write_c1_run_provenance(
            build(run_path, ledger_path),
            repository_root=tmp_path,
            run_report_path=run_path,
            output_path=tmp_path / "elsewhere" / "provenance.json",
        )


def test_provenance_is_never_written_under_evaluation_reviews(tmp_path: Path) -> None:
    run_path, ledger_path = c1_run(tmp_path / "evaluation" / "reviews" / "runs")

    with pytest.raises(EvaluationRunProvenanceRejected, match="evaluation/reviews"):
        write_c1_run_provenance(
            build(run_path, ledger_path),
            repository_root=tmp_path,
            run_report_path=run_path,
            output_path=run_path.parent / "provenance.json",
        )
    assert not (run_path.parent / "provenance.json").exists()


def test_existing_provenance_is_never_replaced(tmp_path: Path) -> None:
    run_path, ledger_path = c1_run(tmp_path / "artifacts")
    output = run_path.parent / "provenance.json"
    output.write_text("{}\n", encoding="utf-8")

    with pytest.raises(EvaluationRunProvenanceRejected, match="already exists"):
        write_c1_run_provenance(
            build(run_path, ledger_path),
            repository_root=tmp_path,
            run_report_path=run_path,
            output_path=output,
        )
    assert output.read_text(encoding="utf-8") == "{}\n"


# Validation


def test_v1_run_is_rejected(tmp_path: Path) -> None:
    _, ledger_path = c1_run(tmp_path / "artifacts")
    v1_run = tmp_path / "artifacts" / "v1-run.json"
    v1_run.write_text(
        run_evaluation_cases(
            load_evaluation_case_suite(V1_FIXTURE),
            fixture_path=V1_FIXTURE,
            repository_root=ROOT,
            executor=ZeroCostExecutor(),
            case_ids=CASE_IDS,
            max_expected_cost=0,
            max_concurrency=1,
        ).as_json(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationRunProvenanceRejected, match="evaluation-corpus/v2"):
        build(v1_run, ledger_path, fixture=V1_FIXTURE)


def test_concurrent_run_is_rejected(tmp_path: Path) -> None:
    _, ledger_path = c1_run(tmp_path / "artifacts")
    concurrent_run = tmp_path / "artifacts" / "concurrent-run.json"
    concurrent_run.write_text(
        run_evaluation_cases(
            load_evaluation_case_suite(V2_FIXTURE),
            fixture_path=V2_FIXTURE,
            repository_root=ROOT,
            executor=ZeroCostExecutor(),
            case_ids=CASE_IDS,
            max_expected_cost=0.18,
            max_concurrency=2,
        ).as_json(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationRunProvenanceRejected, match="max_concurrency 1"):
        build(concurrent_run, ledger_path)


def test_fixture_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    run_path, ledger_path = c1_run(tmp_path / "artifacts")

    with pytest.raises(EvaluationRunProvenanceRejected, match="fixture hash"):
        build(run_path, ledger_path, fixture=V1_FIXTURE)


def test_declared_limits_must_match_the_ledger(tmp_path: Path) -> None:
    run_path, ledger_path = c1_run(tmp_path / "artifacts")

    with pytest.raises(EvaluationRunProvenanceRejected, match="limits differ"):
        build(run_path, ledger_path, max_run=MAX_RUN_MICROUSD + 1)


def test_ledger_with_other_pricing_is_rejected(tmp_path: Path) -> None:
    run_path, ledger_path = c1_run(tmp_path / "artifacts")
    records = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    records[0]["pricing_version"] = "anthropic-claude-sonnet-5-5/other"
    ledger_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    with pytest.raises(EvaluationRunProvenanceRejected, match="does not match C1"):
        build(run_path, ledger_path)


@pytest.mark.parametrize("commit", ["", "abc123", "A" * 40, "g" * 40])
def test_git_commit_must_be_a_full_sha(tmp_path: Path, commit: str) -> None:
    run_path, ledger_path = c1_run(tmp_path / "artifacts")

    with pytest.raises(EvaluationRunProvenanceRejected, match="git_commit"):
        build(run_path, ledger_path, git_commit=commit)


# B1 reference assembly rejects C1 evidence (existing B1 validation, unchanged)


def b1_assembly_input() -> dict[str, object]:
    return {
        "schema_version": "b1-reference-assembly-input/v1",
        "reference_run_id": "11111111-1111-1111-1111-111111111111",
        "workflow_trace_id": "22222222-2222-2222-2222-222222222222",
        "recorded_at": "2026-09-16T15:00:00Z",
        "configuration": {
            "prompt_sha256": "a" * 64,
            "schema_sha256": "a" * 64,
            "retrieval_sha256": "a" * 64,
            "model_id": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "configuration_version": "B1/v1",
        },
    }


def b1_measurements() -> dict[str, object]:
    return {
        "schema_version": "b1-measurements/v1",
        "measurements": [
            {
                "correlation_id": "11111111-1111-1111-1111-111111111111",
                "trace_id": "22222222-2222-2222-2222-222222222222",
                "pricing": {
                    "provider": "openai",
                    "model_id": "gpt-5.6-terra",
                    "pricing_version": "test/v1",
                    "source_reference": "test-pricing",
                    "input_microusd_per_million_tokens": 1_000_000,
                    "output_microusd_per_million_tokens": 2_000_000,
                },
                "outcome": "succeeded",
                "duration_ms": 10.0,
                "retry_count": 0,
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            }
        ],
    }


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_b1_assembly_rejects_c1_provenance_as_assembly_input(tmp_path: Path) -> None:
    run_path, ledger_path = c1_run(tmp_path / "artifacts")
    output = run_path.parent / "provenance.json"
    write_c1_run_provenance(
        build(run_path, ledger_path),
        repository_root=tmp_path,
        run_report_path=run_path,
        output_path=output,
    )

    with pytest.raises(B1ReferenceAssemblyInputRejected):
        load_b1_reference_assembly_input(output)


@pytest.mark.parametrize("b1_evidence", [False, "false", 0, None])
def test_b1_assembly_rejects_any_input_declaring_b1_evidence_false(
    tmp_path: Path, b1_evidence: object
) -> None:
    value = b1_assembly_input()
    value["b1_evidence"] = b1_evidence

    with pytest.raises(B1ReferenceAssemblyInputRejected, match="fields"):
        load_b1_reference_assembly_input(write_json(tmp_path / "input.json", value))


def test_b1_assembly_rejects_c1_configuration(tmp_path: Path) -> None:
    value = b1_assembly_input()
    configuration = value["configuration"]
    assert isinstance(configuration, dict)
    configuration.update(model_id=C1_MODEL_ID, configuration_version="C1/v1")

    with pytest.raises(B1ReferenceAssemblyInputRejected, match="B1 configuration"):
        load_b1_reference_assembly_input(write_json(tmp_path / "input.json", value))


def test_b1_assembly_rejects_a_c1_call_ledger_as_measurements(
    tmp_path: Path,
) -> None:
    _, ledger_path = c1_run(tmp_path / "artifacts")

    with pytest.raises(B1ReferenceAssemblyInputRejected):
        load_b1_measurements(ledger_path)


def test_b1_assembly_cli_rejects_a_c1_v2_run_without_writing(tmp_path: Path) -> None:
    run_path, _ = c1_run(tmp_path / "artifacts")
    suite = load_evaluation_case_suite(V2_FIXTURE)
    score = score_evaluation_run(
        suite,
        evaluation_run_from_json(run_path.read_text(encoding="utf-8")),
        load_ground_truth_catalog(GROUND_TRUTH),
        case_fixture_path=V2_FIXTURE,
        ground_truth_path=GROUND_TRUTH,
    )
    score_path = tmp_path / "artifacts" / "c1-score.json"
    score_path.write_text(score.as_json(), encoding="utf-8")
    output = tmp_path / "b1-reference.json"

    with pytest.raises(SystemExit, match="complete current B1 corpus"):
        assemble_b1_main(
            [
                "--assembly-input",
                str(write_json(tmp_path / "input.json", b1_assembly_input())),
                "--evaluation-run",
                str(run_path),
                "--score-report",
                str(score_path),
                "--measurements",
                str(write_json(tmp_path / "measurements.json", b1_measurements())),
                "--review-manifest",
                str(tmp_path / "unused-review-manifest.yaml"),
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


# CLI


def test_cli_records_provenance_next_to_the_run(tmp_path: Path) -> None:
    run_path, ledger_path = c1_run(tmp_path / "artifacts")
    output = run_path.parent / "c1-run.provenance.json"

    assert (
        record_provenance_main(
            [
                "--run-report",
                str(run_path),
                "--ledger",
                str(ledger_path),
                "--pricing",
                str(PRICING),
                "--git-commit",
                COMMIT,
                "--max-call-cost-usd",
                "0.09",
                "--max-run-cost-usd",
                "0.18",
                "--output",
                str(output),
                "--repository-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))["b1_evidence"] is False
