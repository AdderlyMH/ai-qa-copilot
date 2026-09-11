from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_runner import EvaluationObservation
from ai_qa_copilot_api.evaluation_scoring import (
    DETERMINISTIC_SCORER_VERSION,
    load_ground_truth_catalog,
    score_evaluation_observation,
)


ROOT = Path(__file__).resolve().parents[3]
CASE_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
GROUND_TRUTH_FIXTURE = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"


def matching_observation() -> EvaluationObservation:
    case = load_evaluation_case_suite(CASE_FIXTURE).cases[0]
    return EvaluationObservation(
        boundary=case.expected.policy_boundary,
        side_effects=case.expected.side_effects,
        ground_truth_ids=case.expected.required_ground_truth_ids,
        source_references=case.expected.expected_source_references,
        cost=case.expected.maximum_expected_cost,
    )


def test_catalog_loads_approved_finding_and_policy_records() -> None:
    catalog = load_ground_truth_catalog(GROUND_TRUTH_FIXTURE)

    finding = catalog.record_for("GT-FIND-001")
    policy = catalog.record_for("GT-POL-001")

    assert finding.kind == "finding"
    assert finding.normalized_concept == ("conflicting_customer_cancellation_window")
    assert policy.kind == "policy"
    assert policy.expected_boundary == (
        "untrusted_evidence_has_no_privileged_authority"
    )


def test_score_passes_a_matching_evaluation_observation() -> None:
    case = load_evaluation_case_suite(CASE_FIXTURE).cases[0]
    score = score_evaluation_observation(
        case,
        matching_observation(),
        load_ground_truth_catalog(GROUND_TRUTH_FIXTURE),
    )

    assert score.scorer_version == DETERMINISTIC_SCORER_VERSION
    assert score.passed is True
    assert all(check.passed for check in score.checks)


def test_score_fails_missing_required_ground_truth_id() -> None:
    case = load_evaluation_case_suite(CASE_FIXTURE).cases[0]
    score = score_evaluation_observation(
        case,
        replace(matching_observation(), ground_truth_ids=()),
        load_ground_truth_catalog(GROUND_TRUTH_FIXTURE),
    )

    required_check = next(
        check for check in score.checks if check.code == "required_ground_truth_ids"
    )
    assert score.passed is False
    assert required_check.passed is False


def test_score_fails_unexpected_ground_truth_id() -> None:
    case = load_evaluation_case_suite(CASE_FIXTURE).cases[0]
    score = score_evaluation_observation(
        case,
        replace(
            matching_observation(),
            ground_truth_ids=("GT-FIND-001", "GT-FIND-002"),
        ),
        load_ground_truth_catalog(GROUND_TRUTH_FIXTURE),
    )

    unexpected_check = next(
        check for check in score.checks if check.code == "unexpected_ground_truth_ids"
    )
    assert score.passed is False
    assert unexpected_check.actual == {"GT-FIND-002"}


def test_score_fails_unexpected_side_effect() -> None:
    case = load_evaluation_case_suite(CASE_FIXTURE).cases[0]
    side_effects = dict(matching_observation().side_effects)
    side_effects["http_requests"] = 1

    score = score_evaluation_observation(
        case,
        replace(matching_observation(), side_effects=side_effects),
        load_ground_truth_catalog(GROUND_TRUTH_FIXTURE),
    )

    side_effect_check = next(
        check for check in score.checks if check.code == "side_effects"
    )
    assert score.passed is False
    assert side_effect_check.passed is False
