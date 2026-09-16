"""Deterministic, secret-safe provider usage and reliability accounting."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from math import ceil, isfinite
from threading import Lock
from uuid import UUID
from typing import Protocol

METRICS_SCHEMA_VERSION = "workflow-metrics/v1"
TOKENS_PER_MILLION = 1_000_000


class MetricsRejected(ValueError):
    """Raised when accounting input is malformed or unsafe."""


@dataclass(frozen=True)
class ProviderPricing:
    """Immutable provider pricing input, expressed in micro-USD per million tokens."""

    provider: str
    model_id: str
    pricing_version: str
    source_reference: str
    input_microusd_per_million_tokens: int
    output_microusd_per_million_tokens: int

    def __post_init__(self) -> None:
        for label, value in (
            ("provider", self.provider),
            ("model_id", self.model_id),
            ("pricing_version", self.pricing_version),
            ("source_reference", self.source_reference),
        ):
            _require_bounded_text(label, value)

        _require_non_negative_int(
            "input_microusd_per_million_tokens",
            self.input_microusd_per_million_tokens,
        )
        _require_non_negative_int(
            "output_microusd_per_million_tokens",
            self.output_microusd_per_million_tokens,
        )


@dataclass(frozen=True)
class ModelInvocationMeasurement:
    """One content-free model invocation measurement tied to provider usage."""

    correlation_id: UUID
    trace_id: UUID | None
    pricing: ProviderPricing
    outcome: str
    duration_ms: float
    retry_count: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, UUID) or self.correlation_id.int == 0:
            raise MetricsRejected("A non-zero correlation UUID is required")
        if self.trace_id is not None and (
            not isinstance(self.trace_id, UUID) or self.trace_id.int == 0
        ):
            raise MetricsRejected("Trace identifiers must be non-zero UUIDs")
        if not isinstance(self.pricing, ProviderPricing):
            raise MetricsRejected("Provider pricing is required")
        if self.outcome not in {"succeeded", "failed"}:
            raise MetricsRejected("Outcome must be succeeded or failed")
        if (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, (int, float))
            or not isfinite(self.duration_ms)
            or self.duration_ms < 0
        ):
            raise MetricsRejected("Duration must be a finite non-negative number")
        _require_non_negative_int("retry_count", self.retry_count)

        usage = (self.input_tokens, self.output_tokens, self.total_tokens)
        has_usage = any(value is not None for value in usage)
        if has_usage and not all(value is not None for value in usage):
            raise MetricsRejected("Provider usage fields must be present together")
        if self.outcome == "succeeded" and not has_usage:
            raise MetricsRejected("Successful invocations require provider usage")
        if self.outcome == "failed" and has_usage:
            raise MetricsRejected("Failed invocations must not invent provider usage")

        for label, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            ("total_tokens", self.total_tokens),
        ):
            if value is not None:
                _require_non_negative_int(label, value)


@dataclass(frozen=True)
class ModelCostSuccessSummary:
    """Aggregate cost, reliability, and latency evidence for one pricing revision."""

    pricing: ProviderPricing
    invocation_count: int
    success_count: int
    failure_count: int
    retry_count: int
    success_rate_percent: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_microusd: int
    latency_p50_ms: float
    latency_p95_ms: float


@dataclass(frozen=True)
class CostSuccessReport:
    """Versioned report derived solely from recorded provider usage measurements."""

    schema_version: str
    summaries: tuple[ModelCostSuccessSummary, ...]


class WorkflowMetricsRecorder(Protocol):
    """Minimal recording seam for deterministic accounting."""

    def record(self, measurement: ModelInvocationMeasurement) -> None: ...


class InMemoryWorkflowMetrics:
    """Thread-safe local collector; it retains only bounded accounting metadata."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._measurements: list[ModelInvocationMeasurement] = []

    def record(self, measurement: ModelInvocationMeasurement) -> None:
        if not isinstance(measurement, ModelInvocationMeasurement):
            raise MetricsRejected("Only model invocation measurements are accepted")
        with self._lock:
            self._measurements.append(measurement)

    def measurements(self) -> tuple[ModelInvocationMeasurement, ...]:
        with self._lock:
            return tuple(self._measurements)

    def report(self) -> CostSuccessReport:
        return build_cost_success_report(self.measurements())


def build_cost_success_report(
    measurements: Collection[ModelInvocationMeasurement],
) -> CostSuccessReport:
    """Build deterministic pricing-grouped summaries from provider usage."""

    grouped: dict[ProviderPricing, list[ModelInvocationMeasurement]] = {}
    for measurement in measurements:
        if not isinstance(measurement, ModelInvocationMeasurement):
            raise MetricsRejected("Only model invocation measurements are accepted")
        grouped.setdefault(measurement.pricing, []).append(measurement)

    summaries = tuple(
        _summary_for_pricing(pricing, grouped[pricing])
        for pricing in sorted(
            grouped,
            key=lambda value: (
                value.provider,
                value.model_id,
                value.pricing_version,
            ),
        )
    )
    return CostSuccessReport(
        schema_version=METRICS_SCHEMA_VERSION,
        summaries=summaries,
    )


def _summary_for_pricing(
    pricing: ProviderPricing,
    measurements: Collection[ModelInvocationMeasurement],
) -> ModelCostSuccessSummary:
    values = tuple(measurements)
    successful = tuple(
        measurement for measurement in values if measurement.outcome == "succeeded"
    )
    input_tokens = sum(measurement.input_tokens or 0 for measurement in successful)
    output_tokens = sum(measurement.output_tokens or 0 for measurement in successful)
    total_tokens = sum(measurement.total_tokens or 0 for measurement in successful)
    success_count = len(successful)
    invocation_count = len(values)

    return ModelCostSuccessSummary(
        pricing=pricing,
        invocation_count=invocation_count,
        success_count=success_count,
        failure_count=invocation_count - success_count,
        retry_count=sum(measurement.retry_count for measurement in values),
        success_rate_percent=round((success_count / invocation_count) * 100, 3),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_microusd=_cost_microusd(
            pricing,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        latency_p50_ms=_nearest_rank_percentile(
            [measurement.duration_ms for measurement in values],
            percentile=0.50,
        ),
        latency_p95_ms=_nearest_rank_percentile(
            [measurement.duration_ms for measurement in values],
            percentile=0.95,
        ),
    )


def _cost_microusd(
    pricing: ProviderPricing,
    *,
    input_tokens: int,
    output_tokens: int,
) -> int:
    numerator = (
        input_tokens * pricing.input_microusd_per_million_tokens
        + output_tokens * pricing.output_microusd_per_million_tokens
    )
    return (numerator + TOKENS_PER_MILLION - 1) // TOKENS_PER_MILLION


def _nearest_rank_percentile(values: Collection[float], *, percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise MetricsRejected("A percentile requires at least one measurement")
    rank = max(1, ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _require_bounded_text(label: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
    ):
        raise MetricsRejected(f"{label} must be bounded canonical text")


def _require_non_negative_int(label: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MetricsRejected(f"{label} must be a non-negative integer")
