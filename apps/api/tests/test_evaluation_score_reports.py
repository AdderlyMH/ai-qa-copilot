from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from ai_qa_copilot_api.evaluation_cases import (
    load_evaluation_case_suite,
    EvaluationCaseSuite,
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
    EvaluationScoringRejected,
    load_ground_truth_catalog,
    score_evaluation_run,
)


ROOT = Path(__file__).resolve().parents[3]
CASE_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
GROUND_TRUTH_FIXTURE = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"


def completed_run() -> tuple[EvaluationCaseSuite, EvaluationRun]:
    suite = load_evaluation_case_suite(CASE_FIXTURE)
    case = suite.cases[0]
    observation = EvaluationObservation(
        boundary=case.expected.policy_boundary,
        side_effects=case.expected.side_effects,
        ground_truth_ids=case.expected.required_ground_truth_ids,
        source_references=case.expected.expected_source_references,
        cost=case.expected.maximum_expected_cost,
    )
    run = EvaluationRun(
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
    return suite, run


def test_score_report_has_stable_provenance_and_json() -> None:
    suite, run = completed_run()

    report = score_evaluation_run(
        suite,
        run,
        load_ground_truth_catalog(GROUND_TRUTH_FIXTURE),
        case_fixture_path=CASE_FIXTURE,
        ground_truth_path=GROUND_TRUTH_FIXTURE,
    )

    payload = json.loads(report.as_json())

    assert report.passed is True
    assert payload["schema_version"] == EVALUATION_SCORE_REPORT_SCHEMA_VERSION
    assert payload["suite_id"] == suite.suite_id
    assert payload["scores"][0]["passed"] is True
    assert len(payload["ground_truth_sha256"]) == 64
    assert len(payload["run_sha256"]) == 64


def test_score_report_rejects_tampered_run_fixture_provenance() -> None:
    suite, run = completed_run()

    with pytest.raises(
        EvaluationScoringRejected,
        match="fixture provenance does not match",
    ):
        score_evaluation_run(
            suite,
            replace(run, fixture_sha256="0" * 64),
            load_ground_truth_catalog(GROUND_TRUTH_FIXTURE),
            case_fixture_path=CASE_FIXTURE,
            ground_truth_path=GROUND_TRUTH_FIXTURE,
        )
