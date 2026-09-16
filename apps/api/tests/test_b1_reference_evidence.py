from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ai_qa_copilot_api.b1_reference_evidence import (
    B1ReferenceConfiguration,
    B1ReferenceEvidenceRejected,
    B1ReferenceRun,
    build_b1_reference_run,
)
from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationCaseExecutor,
    EvaluationObservation,
    EvaluationRun,
    run_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_scoring import (
    EvaluationScoreReport,
    load_ground_truth_catalog,
    score_evaluation_run,
)
from ai_qa_copilot_api.metrics import ModelInvocationMeasurement, ProviderPricing


ROOT = Path(__file__).resolve().parents[3]
CASE_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
GROUND_TRUTH_FIXTURE = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"
SHA256 = "a" * 64
PRICING = ProviderPricing(
    provider="openai",
    model_id="gpt-5.6-terra",
    pricing_version="test/v1",
    source_reference="test-pricing",
    input_microusd_per_million_tokens=1_000_000,
    output_microusd_per_million_tokens=2_000_000,
)


class MatchingExecutor(EvaluationCaseExecutor):
    def execute(self, case: EvaluationCase) -> EvaluationObservation:
        expected = case.expected
        return EvaluationObservation(
            boundary=expected.policy_boundary,
            side_effects=expected.side_effects,
            ground_truth_ids=expected.required_ground_truth_ids,
            source_references=expected.expected_source_references,
            cost=expected.maximum_expected_cost,
        )


def full_run_and_score() -> tuple[EvaluationRun, EvaluationScoreReport]:
    suite = load_evaluation_case_suite(CASE_FIXTURE)
    evaluation_run = run_evaluation_cases(
        suite,
        fixture_path=CASE_FIXTURE,
        repository_root=ROOT,
        executor=MatchingExecutor(),
    )
    score_report = score_evaluation_run(
        suite,
        evaluation_run,
        load_ground_truth_catalog(GROUND_TRUTH_FIXTURE),
        case_fixture_path=CASE_FIXTURE,
        ground_truth_path=GROUND_TRUTH_FIXTURE,
    )
    return evaluation_run, score_report


def measurements(
    workflow_trace_id: UUID,
) -> tuple[ModelInvocationMeasurement, ...]:
    return (
        ModelInvocationMeasurement(
            correlation_id=uuid4(),
            trace_id=workflow_trace_id,
            pricing=PRICING,
            outcome="succeeded",
            duration_ms=10.0,
            retry_count=0,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        ),
        ModelInvocationMeasurement(
            correlation_id=uuid4(),
            trace_id=workflow_trace_id,
            pricing=PRICING,
            outcome="failed",
            duration_ms=20.0,
            retry_count=1,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
        ),
    )


def configuration() -> B1ReferenceConfiguration:
    return B1ReferenceConfiguration(
        prompt_sha256=SHA256,
        schema_sha256="b" * 64,
        retrieval_sha256="c" * 64,
    )


def build_reference(
    score_report: EvaluationScoreReport | None = None,
    invocation_measurements: tuple[ModelInvocationMeasurement, ...] | None = None,
    workflow_trace_id: UUID | None = None,
) -> B1ReferenceRun:
    evaluation_run, original_score_report = full_run_and_score()
    if workflow_trace_id is None:
        selected_trace_id = uuid4()
    else:
        selected_trace_id = workflow_trace_id
    selected_measurements = (
        invocation_measurements
        if invocation_measurements is not None
        else measurements(selected_trace_id)
    )
    return build_b1_reference_run(
        reference_run_id=uuid4(),
        workflow_trace_id=selected_trace_id,
        recorded_at=datetime(2026, 9, 16, 15, 0, tzinfo=UTC),
        configuration=configuration(),
        evaluation_run=evaluation_run,
        score_report=score_report or original_score_report,
        measurements=selected_measurements,
    )


def test_builds_full_b1_reference_evidence_with_metrics_and_traces() -> None:
    workflow_trace_id = uuid4()
    reference = build_reference(workflow_trace_id=workflow_trace_id)

    assert reference.case_count == 100
    assert reference.quality_passed is True
    assert reference.security_gate_passed is True
    assert reference.cost_budget_passed is True
    assert reference.failure_categories == ()
    assert reference.workflow_trace_id == workflow_trace_id
    assert reference.metrics_report.summaries[0].cost_microusd == 20
    assert reference.metrics_report.summaries[0].latency_p95_ms == 20.0

    payload = json.loads(reference.as_json())
    assert payload["schema_version"] == "b1-reference-run/v1"
    assert payload["configuration"]["model_id"] == "gpt-5.6-terra"
    assert payload["case_count"] == 100


@pytest.mark.parametrize(
    ("check_code", "expected_category"),
    [
        ("policy_boundary", "security:policy_boundary"),
        ("maximum_expected_cost", "cost:maximum_expected_cost"),
    ],
)
def test_preserves_security_and_budget_failures(
    check_code: str,
    expected_category: str,
) -> None:
    workflow_trace_id = uuid4()
    evaluation_run, score_report = full_run_and_score()
    first_score = score_report.scores[0]
    failed_checks = tuple(
        replace(check, passed=False) if check.code == check_code else check
        for check in first_score.checks
    )
    failed_score_report = replace(
        score_report,
        passed=False,
        scores=(
            replace(first_score, passed=False, checks=failed_checks),
            *score_report.scores[1:],
        ),
    )

    reference = build_b1_reference_run(
        workflow_trace_id=workflow_trace_id,
        reference_run_id=uuid4(),
        recorded_at=datetime(2026, 9, 16, 15, 0, tzinfo=UTC),
        configuration=configuration(),
        evaluation_run=evaluation_run,
        score_report=failed_score_report,
        measurements=measurements(workflow_trace_id),
    )

    assert (expected_category, 1) in reference.failure_categories
    if expected_category.startswith("security:"):
        assert reference.security_gate_passed is False
    else:
        assert reference.cost_budget_passed is False


def test_rejects_mismatched_score_or_mismatched_trace_measurement() -> None:
    workflow_trace_id = uuid4()
    evaluation_run, score_report = full_run_and_score()

    with pytest.raises(B1ReferenceEvidenceRejected, match="run provenance"):
        build_b1_reference_run(
            workflow_trace_id=workflow_trace_id,
            reference_run_id=uuid4(),
            recorded_at=datetime(2026, 9, 16, 15, 0, tzinfo=UTC),
            configuration=configuration(),
            evaluation_run=evaluation_run,
            score_report=replace(score_report, run_sha256="d" * 64),
            measurements=measurements(workflow_trace_id),
        )

    with pytest.raises(B1ReferenceEvidenceRejected, match="reference workflow trace"):
        build_b1_reference_run(
            reference_run_id=uuid4(),
            workflow_trace_id=workflow_trace_id,
            recorded_at=datetime(2026, 9, 16, 15, 0, tzinfo=UTC),
            configuration=configuration(),
            evaluation_run=evaluation_run,
            score_report=score_report,
            measurements=(
                replace(measurements(workflow_trace_id)[0], trace_id=uuid4()),
            ),
        )
