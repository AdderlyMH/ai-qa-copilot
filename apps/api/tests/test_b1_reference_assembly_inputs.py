from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_qa_copilot_api.b1_reference_assembly_inputs import (
    B1ReferenceAssemblyInputRejected,
    load_b1_measurements,
    load_b1_reference_assembly_input,
    load_evaluation_score_report,
)


SHA256 = "a" * 64
REFERENCE_RUN_ID = "11111111-1111-1111-1111-111111111111"
TRACE_ID = "22222222-2222-2222-2222-222222222222"


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def assembly_input() -> dict[str, object]:
    return {
        "schema_version": "b1-reference-assembly-input/v1",
        "reference_run_id": REFERENCE_RUN_ID,
        "workflow_trace_id": TRACE_ID,
        "recorded_at": "2026-09-16T15:00:00Z",
        "configuration": {
            "prompt_sha256": SHA256,
            "schema_sha256": SHA256,
            "retrieval_sha256": SHA256,
            "model_id": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "configuration_version": "B1/v1",
        },
    }


def measurements() -> dict[str, object]:
    return {
        "schema_version": "b1-measurements/v1",
        "measurements": [
            {
                "correlation_id": REFERENCE_RUN_ID,
                "trace_id": TRACE_ID,
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


def test_loads_pinned_b1_input_and_measurements(tmp_path: Path) -> None:
    request = load_b1_reference_assembly_input(
        write_json(tmp_path / "assembly-input.json", assembly_input())
    )
    decoded_measurements = load_b1_measurements(
        write_json(tmp_path / "measurements.json", measurements())
    )

    assert request.configuration.model_id == "gpt-5.6-terra"
    assert request.recorded_at.isoformat() == "2026-09-16T15:00:00+00:00"
    assert decoded_measurements[0].trace_id == request.workflow_trace_id
    assert decoded_measurements[0].pricing.pricing_version == "test/v1"


def test_rejects_non_b1_configuration_and_invalid_measurement(
    tmp_path: Path,
) -> None:
    invalid_input = assembly_input()
    configuration = invalid_input["configuration"]
    assert isinstance(configuration, dict)
    configuration["model_id"] = "other-model"

    with pytest.raises(
        B1ReferenceAssemblyInputRejected,
        match="requires model gpt-5.6-terra",
    ):
        load_b1_reference_assembly_input(
            write_json(tmp_path / "invalid-input.json", invalid_input)
        )

    invalid_measurements = measurements()
    records = invalid_measurements["measurements"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    record["input_tokens"] = None

    with pytest.raises(
        B1ReferenceAssemblyInputRejected,
        match="measurement is invalid",
    ):
        load_b1_measurements(
            write_json(tmp_path / "invalid-measurements.json", invalid_measurements)
        )


def score_report() -> dict[str, object]:
    return {
        "schema_version": "evaluation-score-report/v1",
        "scorer_version": "deterministic-evaluation-scorer/v1",
        "suite_id": "evaluation-corpus/v1",
        "case_fixture_sha256": SHA256,
        "ground_truth_sha256": SHA256,
        "run_sha256": SHA256,
        "passed": True,
        "scores": [
            {
                "case_id": "EVAL-001",
                "scorer_version": "deterministic-evaluation-scorer/v1",
                "passed": True,
                "checks": [
                    {
                        "code": "policy_boundary",
                        "passed": True,
                        "expected": "analysis_only",
                        "actual": "analysis_only",
                    }
                ],
            }
        ],
    }


def test_loads_recorded_score_report(tmp_path: Path) -> None:
    report = load_evaluation_score_report(
        write_json(tmp_path / "score-report.json", score_report())
    )

    assert report.suite_id == "evaluation-corpus/v1"
    assert report.passed is True
    assert report.scores[0].checks[0].code == "policy_boundary"


def test_rejects_inconsistent_score_report_pass_flag(tmp_path: Path) -> None:
    invalid_report = score_report()
    invalid_report["passed"] = False

    with pytest.raises(
        B1ReferenceAssemblyInputRejected,
        match="passed flag does not match scores",
    ):
        load_evaluation_score_report(
            write_json(tmp_path / "invalid-score-report.json", invalid_report)
        )
