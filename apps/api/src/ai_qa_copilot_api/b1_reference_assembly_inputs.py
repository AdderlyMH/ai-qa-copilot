"""Strict decoding of recorded, content-free B1 assembly inputs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import re
from pathlib import Path
from typing import cast
from uuid import UUID

from ai_qa_copilot_api.b1_reference_evidence import (
    B1ReferenceConfiguration,
    B1ReferenceEvidenceRejected,
)
from ai_qa_copilot_api.metrics import (
    MetricsRejected,
    ModelInvocationMeasurement,
    ProviderPricing,
)
from ai_qa_copilot_api.evaluation_scoring import (
    DETERMINISTIC_SCORER_VERSION,
    EVALUATION_SCORE_REPORT_SCHEMA_VERSION,
    EvaluationScore,
    EvaluationScoreCheck,
    EvaluationScoreReport,
)


B1_REFERENCE_ASSEMBLY_INPUT_SCHEMA_VERSION = "b1-reference-assembly-input/v1"
B1_MEASUREMENTS_SCHEMA_VERSION = "b1-measurements/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class B1ReferenceAssemblyInputRejected(ValueError):
    """Raised when recorded B1 assembly input is incomplete or malformed."""


@dataclass(frozen=True)
class B1ReferenceAssemblyInput:
    """Non-secret identity and pinned configuration for recorded B1 evidence."""

    reference_run_id: UUID
    workflow_trace_id: UUID
    recorded_at: datetime
    configuration: B1ReferenceConfiguration


def load_b1_reference_assembly_input(path: Path) -> B1ReferenceAssemblyInput:
    """Load one strict B1 assembly-input record without executing anything."""

    raw = _load_mapping(path, "B1 assembly input")
    _require_exact_fields(
        raw,
        {
            "schema_version",
            "reference_run_id",
            "workflow_trace_id",
            "recorded_at",
            "configuration",
        },
        "B1 assembly input",
    )
    if _text(raw["schema_version"], "schema_version") != (
        B1_REFERENCE_ASSEMBLY_INPUT_SCHEMA_VERSION
    ):
        raise B1ReferenceAssemblyInputRejected("Unsupported B1 assembly input schema")

    configuration = _mapping(raw["configuration"], "configuration")
    _require_exact_fields(
        configuration,
        {
            "prompt_sha256",
            "schema_sha256",
            "retrieval_sha256",
            "model_id",
            "reasoning_effort",
            "configuration_version",
        },
        "configuration",
    )
    decoded_configuration = B1ReferenceConfiguration(
        prompt_sha256=_sha256(configuration["prompt_sha256"], "prompt_sha256"),
        schema_sha256=_sha256(configuration["schema_sha256"], "schema_sha256"),
        retrieval_sha256=_sha256(
            configuration["retrieval_sha256"],
            "retrieval_sha256",
        ),
        model_id=_text(configuration["model_id"], "model_id"),
        reasoning_effort=_text(
            configuration["reasoning_effort"],
            "reasoning_effort",
        ),
        configuration_version=_text(
            configuration["configuration_version"],
            "configuration_version",
        ),
    )
    try:
        decoded_configuration.validate()
    except B1ReferenceEvidenceRejected as error:
        raise B1ReferenceAssemblyInputRejected(
            f"B1 configuration is invalid: {error}"
        ) from error

    return B1ReferenceAssemblyInput(
        reference_run_id=_uuid(raw["reference_run_id"], "reference_run_id"),
        workflow_trace_id=_uuid(raw["workflow_trace_id"], "workflow_trace_id"),
        recorded_at=_utc_timestamp(raw["recorded_at"], "recorded_at"),
        configuration=decoded_configuration,
    )


def load_b1_measurements(path: Path) -> tuple[ModelInvocationMeasurement, ...]:
    """Load content-free provider-usage measurements from strict JSON."""

    raw = _load_mapping(path, "B1 measurements")
    _require_exact_fields(
        raw,
        {"schema_version", "measurements"},
        "B1 measurements",
    )
    if _text(raw["schema_version"], "schema_version") != B1_MEASUREMENTS_SCHEMA_VERSION:
        raise B1ReferenceAssemblyInputRejected("Unsupported B1 measurements schema")

    records = raw["measurements"]
    if not isinstance(records, list) or not records:
        raise B1ReferenceAssemblyInputRejected(
            "B1 measurements must contain at least one record"
        )

    return tuple(_measurement(_mapping(record, "measurement")) for record in records)


def _measurement(record: Mapping[str, object]) -> ModelInvocationMeasurement:
    _require_exact_fields(
        record,
        {
            "correlation_id",
            "trace_id",
            "pricing",
            "outcome",
            "duration_ms",
            "retry_count",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        },
        "measurement",
    )
    pricing = _mapping(record["pricing"], "measurement.pricing")
    _require_exact_fields(
        pricing,
        {
            "provider",
            "model_id",
            "pricing_version",
            "source_reference",
            "input_microusd_per_million_tokens",
            "output_microusd_per_million_tokens",
        },
        "measurement.pricing",
    )
    try:
        return ModelInvocationMeasurement(
            correlation_id=_uuid(record["correlation_id"], "correlation_id"),
            trace_id=_uuid(record["trace_id"], "trace_id"),
            pricing=ProviderPricing(
                provider=_text(pricing["provider"], "provider"),
                model_id=_text(pricing["model_id"], "model_id"),
                pricing_version=_text(pricing["pricing_version"], "pricing_version"),
                source_reference=_text(pricing["source_reference"], "source_reference"),
                input_microusd_per_million_tokens=_non_negative_int(
                    pricing["input_microusd_per_million_tokens"],
                    "input_microusd_per_million_tokens",
                ),
                output_microusd_per_million_tokens=_non_negative_int(
                    pricing["output_microusd_per_million_tokens"],
                    "output_microusd_per_million_tokens",
                ),
            ),
            outcome=_text(record["outcome"], "outcome"),
            duration_ms=_number(record["duration_ms"], "duration_ms"),
            retry_count=_non_negative_int(record["retry_count"], "retry_count"),
            input_tokens=_optional_non_negative_int(
                record["input_tokens"], "input_tokens"
            ),
            output_tokens=_optional_non_negative_int(
                record["output_tokens"],
                "output_tokens",
            ),
            total_tokens=_optional_non_negative_int(
                record["total_tokens"], "total_tokens"
            ),
        )
    except MetricsRejected as error:
        raise B1ReferenceAssemblyInputRejected(
            f"measurement is invalid: {error}"
        ) from error


def _load_mapping(path: Path, label: str) -> Mapping[str, object]:
    if not path.is_file():
        raise B1ReferenceAssemblyInputRejected(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise B1ReferenceAssemblyInputRejected(f"{label} is not valid JSON") from error
    return _mapping(value, label)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise B1ReferenceAssemblyInputRejected(f"{label} must be a JSON object")
    return cast(Mapping[str, object], value)


def _require_exact_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise B1ReferenceAssemblyInputRejected(
            f"{label} fields must be exactly {sorted(expected)}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise B1ReferenceAssemblyInputRejected(f"{label} must be non-empty text")
    return value


def _sha256(value: object, label: str) -> str:
    result = _text(value, label)
    if not _SHA256.fullmatch(result):
        raise B1ReferenceAssemblyInputRejected(f"{label} must be a SHA-256 digest")
    return result


def _uuid(value: object, label: str) -> UUID:
    try:
        result = UUID(_text(value, label))
    except ValueError as error:
        raise B1ReferenceAssemblyInputRejected(f"{label} must be a UUID") from error
    if result.int == 0:
        raise B1ReferenceAssemblyInputRejected(f"{label} must be non-zero")
    return result


def _utc_timestamp(value: object, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, label).replace("Z", "+00:00"))
    except ValueError as error:
        raise B1ReferenceAssemblyInputRejected(
            f"{label} must be an ISO-8601 timestamp"
        ) from error
    if result.tzinfo is None or result.utcoffset() != UTC.utcoffset(result):
        raise B1ReferenceAssemblyInputRejected(f"{label} must be UTC")
    return result


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise B1ReferenceAssemblyInputRejected(f"{label} must be numeric")
    return float(value)


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise B1ReferenceAssemblyInputRejected(
            f"{label} must be a non-negative integer"
        )
    return value


def _optional_non_negative_int(value: object, label: str) -> int | None:
    return None if value is None else _non_negative_int(value, label)


def load_evaluation_score_report(path: Path) -> EvaluationScoreReport:
    """Load a strict, already-recorded deterministic score report."""

    raw = _load_mapping(path, "Evaluation score report")
    _require_exact_fields(
        raw,
        {
            "schema_version",
            "scorer_version",
            "suite_id",
            "case_fixture_sha256",
            "ground_truth_sha256",
            "run_sha256",
            "passed",
            "scores",
        },
        "Evaluation score report",
    )
    if _text(raw["schema_version"], "schema_version") != (
        EVALUATION_SCORE_REPORT_SCHEMA_VERSION
    ):
        raise B1ReferenceAssemblyInputRejected(
            "Unsupported evaluation score report schema"
        )
    if _text(raw["scorer_version"], "scorer_version") != (DETERMINISTIC_SCORER_VERSION):
        raise B1ReferenceAssemblyInputRejected(
            "Unsupported evaluation score report scorer"
        )

    raw_scores = raw["scores"]
    if not isinstance(raw_scores, list) or not raw_scores:
        raise B1ReferenceAssemblyInputRejected(
            "Evaluation score report must contain scores"
        )
    scores = tuple(_score(_mapping(value, "score")) for value in raw_scores)
    passed = _boolean(raw["passed"], "passed")
    if passed != all(score.passed for score in scores):
        raise B1ReferenceAssemblyInputRejected(
            "Evaluation score report passed flag does not match scores"
        )

    return EvaluationScoreReport(
        schema_version=EVALUATION_SCORE_REPORT_SCHEMA_VERSION,
        scorer_version=DETERMINISTIC_SCORER_VERSION,
        suite_id=_text(raw["suite_id"], "suite_id"),
        case_fixture_sha256=_sha256(
            raw["case_fixture_sha256"],
            "case_fixture_sha256",
        ),
        ground_truth_sha256=_sha256(
            raw["ground_truth_sha256"],
            "ground_truth_sha256",
        ),
        run_sha256=_sha256(raw["run_sha256"], "run_sha256"),
        passed=passed,
        scores=scores,
    )


def _score(record: Mapping[str, object]) -> EvaluationScore:
    _require_exact_fields(
        record,
        {"case_id", "scorer_version", "passed", "checks"},
        "score",
    )
    if _text(record["scorer_version"], "score.scorer_version") != (
        DETERMINISTIC_SCORER_VERSION
    ):
        raise B1ReferenceAssemblyInputRejected("Unsupported score scorer")

    raw_checks = record["checks"]
    if not isinstance(raw_checks, list) or not raw_checks:
        raise B1ReferenceAssemblyInputRejected("Score must contain checks")
    checks = tuple(_score_check(_mapping(value, "score check")) for value in raw_checks)
    passed = _boolean(record["passed"], "score.passed")
    if passed != all(check.passed for check in checks):
        raise B1ReferenceAssemblyInputRejected(
            "Score passed flag does not match checks"
        )

    return EvaluationScore(
        case_id=_text(record["case_id"], "case_id"),
        scorer_version=DETERMINISTIC_SCORER_VERSION,
        passed=passed,
        checks=checks,
    )


def _score_check(record: Mapping[str, object]) -> EvaluationScoreCheck:
    _require_exact_fields(
        record,
        {"code", "passed", "expected", "actual"},
        "score check",
    )
    return EvaluationScoreCheck(
        code=_text(record["code"], "score check code"),
        passed=_boolean(record["passed"], "score check passed"),
        expected=_json_value(record["expected"], "score check expected"),
        actual=_json_value(record["actual"], "score check actual"),
    )


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise B1ReferenceAssemblyInputRejected(f"{label} must be a boolean")
    return value


def _json_value(value: object, label: str) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_json_value(item, label) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json_value(item, label) for key, item in sorted(value.items())}
    raise B1ReferenceAssemblyInputRejected(f"{label} must be JSON-compatible")
