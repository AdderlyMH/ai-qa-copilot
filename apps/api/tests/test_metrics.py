from uuid import uuid4

import pytest
from dataclasses import replace

from ai_qa_copilot_api.metrics import (
    InMemoryWorkflowMetrics,
    MetricsRejected,
    ModelInvocationMeasurement,
    ProviderPricing,
)


PRICING = ProviderPricing(
    provider="openai",
    model_id="test-model",
    pricing_version="test-pricing/v1",
    source_reference="test-fixture",
    input_microusd_per_million_tokens=1_250_000,
    output_microusd_per_million_tokens=2_000_000,
)


def test_cost_success_report_uses_provider_usage_and_nearest_rank_percentiles() -> None:
    metrics = InMemoryWorkflowMetrics()
    correlation_id = uuid4()

    metrics.record(
        ModelInvocationMeasurement(
            correlation_id=correlation_id,
            trace_id=uuid4(),
            pricing=PRICING,
            outcome="succeeded",
            duration_ms=10.0,
            retry_count=0,
            input_tokens=12,
            output_tokens=4,
            total_tokens=16,
        )
    )
    metrics.record(
        ModelInvocationMeasurement(
            correlation_id=correlation_id,
            trace_id=uuid4(),
            pricing=PRICING,
            outcome="succeeded",
            duration_ms=20.0,
            retry_count=1,
            input_tokens=8,
            output_tokens=2,
            total_tokens=10,
        )
    )
    metrics.record(
        ModelInvocationMeasurement(
            correlation_id=correlation_id,
            trace_id=uuid4(),
            pricing=PRICING,
            outcome="failed",
            duration_ms=40.0,
            retry_count=2,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
        )
    )

    report = metrics.report()

    assert report.schema_version == "workflow-metrics/v1"
    assert len(report.summaries) == 1

    summary = report.summaries[0]
    assert summary.pricing == PRICING
    assert summary.invocation_count == 3
    assert summary.success_count == 2
    assert summary.failure_count == 1
    assert summary.retry_count == 3
    assert summary.success_rate_percent == 66.667
    assert summary.input_tokens == 20
    assert summary.output_tokens == 6
    assert summary.total_tokens == 26
    assert summary.cost_microusd == 37
    assert summary.latency_p50_ms == 20.0
    assert summary.latency_p95_ms == 40.0


@pytest.mark.parametrize(
    "outcome,input_tokens,output_tokens,total_tokens",
    [
        ("succeeded", None, None, None),
        ("failed", 1, 1, 2),
        ("succeeded", 1, None, 1),
    ],
)
def test_measurement_rejects_missing_or_forged_provider_usage(
    outcome: str,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
) -> None:
    with pytest.raises(MetricsRejected):
        ModelInvocationMeasurement(
            correlation_id=uuid4(),
            trace_id=None,
            pricing=PRICING,
            outcome=outcome,
            duration_ms=1.0,
            retry_count=0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )


def test_cost_uses_exact_integer_ceiling_division_for_large_usage() -> None:
    metrics = InMemoryWorkflowMetrics()
    pricing = replace(
        PRICING,
        input_microusd_per_million_tokens=1,
        output_microusd_per_million_tokens=0,
    )

    metrics.record(
        ModelInvocationMeasurement(
            correlation_id=uuid4(),
            trace_id=None,
            pricing=pricing,
            outcome="succeeded",
            duration_ms=1.0,
            retry_count=0,
            input_tokens=1_000_000_000_000_000_001,
            output_tokens=0,
            total_tokens=1_000_000_000_000_000_001,
        )
    )

    assert metrics.report().summaries[0].cost_microusd == 1_000_000_000_001
