"""Immutable, content-free evidence for one B1/v1 reference evaluation run."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from uuid import UUID

from ai_qa_copilot_api.evaluation_runner import EvaluationRun
from ai_qa_copilot_api.evaluation_scoring import EvaluationScoreReport
from ai_qa_copilot_api.metrics import (
    CostSuccessReport,
    ModelInvocationMeasurement,
    build_cost_success_report,
)
from ai_qa_copilot_api.model_gateway import (
    B1_MODEL_ID,
    B1_REASONING_EFFORT,
    MODEL_GATEWAY_CONFIGURATION_VERSION,
)

B1_REFERENCE_RUN_SCHEMA_VERSION = "b1-reference-run/v1"
B1_REFERENCE_CASE_COUNT = 100
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SECURITY_CHECK_CODES = frozenset({"policy_boundary", "side_effects"})
_COST_CHECK_CODES = frozenset({"maximum_expected_cost"})


class B1ReferenceEvidenceRejected(ValueError):
    """Raised when immutable B1 reference evidence is incomplete or mismatched."""


@dataclass(frozen=True)
class B1ReferenceConfiguration:
    """Pinned, hash-addressed B1/v1 workflow configuration."""

    prompt_sha256: str
    schema_sha256: str
    retrieval_sha256: str
    model_id: str = B1_MODEL_ID
    reasoning_effort: str = B1_REASONING_EFFORT
    configuration_version: str = MODEL_GATEWAY_CONFIGURATION_VERSION

    def validate(self) -> None:
        if self.model_id != B1_MODEL_ID:
            raise B1ReferenceEvidenceRejected(
                "B1 reference evidence requires model gpt-5.6-terra"
            )
        if self.reasoning_effort != B1_REASONING_EFFORT:
            raise B1ReferenceEvidenceRejected(
                "B1 reference evidence requires medium reasoning effort"
            )
        if self.configuration_version != MODEL_GATEWAY_CONFIGURATION_VERSION:
            raise B1ReferenceEvidenceRejected(
                "B1 reference evidence requires configuration version B1/v1"
            )

        for label, value in (
            ("prompt_sha256", self.prompt_sha256),
            ("schema_sha256", self.schema_sha256),
            ("retrieval_sha256", self.retrieval_sha256),
        ):
            _require_sha256(label, value)


@dataclass(frozen=True)
class B1ReferenceRun:
    """One immutable evidence record; it does not execute an evaluation."""

    schema_version: str
    reference_run_id: UUID
    recorded_at: datetime
    configuration: B1ReferenceConfiguration
    configuration_sha256: str
    evaluation_run_sha256: str
    score_report_sha256: str
    measurements_sha256: str
    metrics_report_sha256: str
    case_count: int
    workflow_trace_id: UUID
    metrics_report: CostSuccessReport
    failure_categories: tuple[tuple[str, int], ...]
    quality_passed: bool
    security_gate_passed: bool
    cost_budget_passed: bool

    def as_json(self) -> str:
        return (
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "reference_run_id": str(self.reference_run_id),
                    "recorded_at": self.recorded_at.isoformat(),
                    "configuration": asdict(self.configuration),
                    "configuration_sha256": self.configuration_sha256,
                    "evaluation_run_sha256": self.evaluation_run_sha256,
                    "score_report_sha256": self.score_report_sha256,
                    "measurements_sha256": self.measurements_sha256,
                    "metrics_report_sha256": self.metrics_report_sha256,
                    "case_count": self.case_count,
                    "workflow_trace_id": str(self.workflow_trace_id),
                    "metrics_report": asdict(self.metrics_report),
                    "failure_categories": dict(self.failure_categories),
                    "quality_passed": self.quality_passed,
                    "security_gate_passed": self.security_gate_passed,
                    "cost_budget_passed": self.cost_budget_passed,
                },
                indent=2,
                sort_keys=True,
                separators=(",", ": "),
            )
            + "\n"
        )


def build_b1_reference_run(
    *,
    reference_run_id: UUID,
    workflow_trace_id: UUID,
    recorded_at: datetime,
    configuration: B1ReferenceConfiguration,
    evaluation_run: EvaluationRun,
    score_report: EvaluationScoreReport,
    measurements: Collection[ModelInvocationMeasurement],
) -> B1ReferenceRun:
    """Bind existing B1 evidence without calling a model or changing evaluation."""

    _validate_reference_identity(reference_run_id, recorded_at)
    _validate_workflow_trace_id(workflow_trace_id)
    configuration.validate()

    evaluation_run_sha256 = _sha256_text(evaluation_run.as_json())
    _validate_score_report(
        evaluation_run=evaluation_run,
        evaluation_run_sha256=evaluation_run_sha256,
        score_report=score_report,
    )

    measurement_values = tuple(measurements)
    if not measurement_values:
        raise B1ReferenceEvidenceRejected(
            "B1 reference evidence requires provider usage measurements"
        )
    _validate_measurements(measurement_values, workflow_trace_id)

    metrics_report = build_cost_success_report(measurement_values)
    if len(metrics_report.summaries) != 1:
        raise B1ReferenceEvidenceRejected(
            "B1 reference evidence requires one pinned pricing revision"
        )

    failure_categories = _failure_categories(score_report)

    return B1ReferenceRun(
        schema_version=B1_REFERENCE_RUN_SCHEMA_VERSION,
        reference_run_id=reference_run_id,
        recorded_at=recorded_at,
        configuration=configuration,
        configuration_sha256=_sha256_json(asdict(configuration)),
        evaluation_run_sha256=evaluation_run_sha256,
        score_report_sha256=_sha256_text(score_report.as_json()),
        measurements_sha256=_sha256_json(
            [_measurement_as_mapping(measurement) for measurement in measurement_values]
        ),
        metrics_report_sha256=_sha256_json(asdict(metrics_report)),
        case_count=len(evaluation_run.selected_case_ids),
        workflow_trace_id=workflow_trace_id,
        metrics_report=metrics_report,
        failure_categories=failure_categories,
        quality_passed=not any(
            category.startswith("quality:") for category, _ in failure_categories
        ),
        security_gate_passed=not any(
            category.startswith("security:") for category, _ in failure_categories
        ),
        cost_budget_passed=not any(
            category.startswith("cost:") for category, _ in failure_categories
        ),
    )


def _validate_reference_identity(
    reference_run_id: UUID,
    recorded_at: datetime,
) -> None:
    if not isinstance(reference_run_id, UUID) or reference_run_id.int == 0:
        raise B1ReferenceEvidenceRejected("A non-zero reference run UUID is required")
    if (
        not isinstance(recorded_at, datetime)
        or recorded_at.tzinfo is None
        or recorded_at.utcoffset() != UTC.utcoffset(recorded_at)
    ):
        raise B1ReferenceEvidenceRejected(
            "Reference run timestamp must be timezone-aware UTC"
        )


def _validate_workflow_trace_id(workflow_trace_id: UUID) -> None:
    if not isinstance(workflow_trace_id, UUID) or workflow_trace_id.int == 0:
        raise B1ReferenceEvidenceRejected("A non-zero workflow trace UUID is required")


def _validate_score_report(
    *,
    evaluation_run: EvaluationRun,
    evaluation_run_sha256: str,
    score_report: EvaluationScoreReport,
) -> None:
    selected_case_ids = evaluation_run.selected_case_ids
    run_case_ids = tuple(result.case_id for result in evaluation_run.results)
    score_case_ids = tuple(score.case_id for score in score_report.scores)

    if len(selected_case_ids) != B1_REFERENCE_CASE_COUNT:
        raise B1ReferenceEvidenceRejected(
            "B1 reference evidence requires the full 100-case benchmark"
        )
    if run_case_ids != selected_case_ids:
        raise B1ReferenceEvidenceRejected(
            "Evaluation results must preserve selected-case order"
        )
    if score_case_ids != selected_case_ids:
        raise B1ReferenceEvidenceRejected(
            "Score report must preserve the full evaluation-case order"
        )
    if score_report.suite_id != evaluation_run.suite_id:
        raise B1ReferenceEvidenceRejected(
            "Score report suite does not match evaluation"
        )
    if score_report.case_fixture_sha256 != evaluation_run.fixture_sha256:
        raise B1ReferenceEvidenceRejected(
            "Score report fixture provenance does not match evaluation"
        )
    if score_report.run_sha256 != evaluation_run_sha256:
        raise B1ReferenceEvidenceRejected(
            "Score report run provenance does not match evaluation"
        )


def _validate_measurements(
    measurements: tuple[ModelInvocationMeasurement, ...],
    workflow_trace_id: UUID,
) -> None:
    pricing_revisions = set()

    for measurement in measurements:
        if not isinstance(measurement, ModelInvocationMeasurement):
            raise B1ReferenceEvidenceRejected(
                "B1 reference evidence accepts only provider usage measurements"
            )
        if measurement.trace_id != workflow_trace_id:
            raise B1ReferenceEvidenceRejected(
                "B1 reference measurements must link to the reference workflow trace"
            )
        if measurement.pricing.model_id != B1_MODEL_ID:
            raise B1ReferenceEvidenceRejected(
                "B1 reference measurements must use model gpt-5.6-terra"
            )
        pricing_revisions.add(measurement.pricing)

    if len(pricing_revisions) != 1:
        raise B1ReferenceEvidenceRejected(
            "B1 reference evidence requires one pinned pricing revision"
        )


def _failure_categories(
    score_report: EvaluationScoreReport,
) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter()

    for score in score_report.scores:
        for check in score.checks:
            if check.passed:
                continue
            if check.code in _SECURITY_CHECK_CODES:
                category = f"security:{check.code}"
            elif check.code in _COST_CHECK_CODES:
                category = f"cost:{check.code}"
            else:
                category = f"quality:{check.code}"
            counts[category] += 1

    return tuple(sorted(counts.items()))


def _measurement_as_mapping(
    measurement: ModelInvocationMeasurement,
) -> dict[str, object]:
    return {
        "correlation_id": str(measurement.correlation_id),
        "trace_id": str(measurement.trace_id),
        "pricing": asdict(measurement.pricing),
        "outcome": measurement.outcome,
        "duration_ms": measurement.duration_ms,
        "retry_count": measurement.retry_count,
        "input_tokens": measurement.input_tokens,
        "output_tokens": measurement.output_tokens,
        "total_tokens": measurement.total_tokens,
    }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    )


def _require_sha256(label: str, value: object) -> None:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise B1ReferenceEvidenceRejected(f"{label} must be a SHA-256 digest")
