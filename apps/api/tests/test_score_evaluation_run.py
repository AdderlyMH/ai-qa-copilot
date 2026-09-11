from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCaseSuite,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_runner import (
    EVALUATION_RUN_SCHEMA_VERSION,
    EvaluationObservation,
    EvaluationRun,
    EvaluationRunCaseResult,
    evaluation_case_sha256,
)
from ai_qa_copilot_api.evaluation_scoring import (
    EVALUATION_SCORE_REPORT_SCHEMA_VERSION,
)


SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from score_evaluation_run import main  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
CASE_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
GROUND_TRUTH_FIXTURE = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"


def completed_run(suite: EvaluationCaseSuite) -> EvaluationRun:
    case = suite.cases[0]
    observation = EvaluationObservation(
        boundary=case.expected.policy_boundary,
        side_effects=case.expected.side_effects,
        ground_truth_ids=case.expected.required_ground_truth_ids,
        source_references=case.expected.expected_source_references,
        cost=case.expected.maximum_expected_cost,
    )

    return EvaluationRun(
        schema_version=EVALUATION_RUN_SCHEMA_VERSION,
        suite_id=suite.suite_id,
        fixture_sha256=hashlib.sha256(CASE_FIXTURE.read_bytes()).hexdigest(),
        selected_case_ids=(case.id,),
        max_expected_cost=None,
        max_concurrency=1,
        results=(
            EvaluationRunCaseResult(
                case_id=case.id,
                case_version=case.version,
                case_sha256=evaluation_case_sha256(case),
                observation=observation,
                reused=False,
            ),
        ),
    )


def test_cli_writes_machine_readable_score_report(tmp_path: Path) -> None:
    suite = load_evaluation_case_suite(CASE_FIXTURE)
    run_report_path = tmp_path / "evaluation-run.json"
    output_path = tmp_path / "evaluation-score-report.json"
    run_report_path.write_text(completed_run(suite).as_json(), encoding="utf-8")

    assert (
        main(
            [
                "--fixture",
                str(CASE_FIXTURE),
                "--ground-truth",
                str(GROUND_TRUTH_FIXTURE),
                "--run-report",
                str(run_report_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == EVALUATION_SCORE_REPORT_SCHEMA_VERSION
    assert payload["passed"] is True
    assert payload["scores"][0]["case_id"] == "EVAL-001"


def test_cli_refuses_to_overwrite_an_existing_score_report(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evaluation-score-report.json"
    output_path.write_text("already exists", encoding="utf-8")
    run_report_path = tmp_path / "evaluation-run.json"
    run_report_path.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit, match="Output already exists"):
        main(
            [
                "--run-report",
                str(run_report_path),
                "--output",
                str(output_path),
            ]
        )
