from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID, uuid4

import pytest

import ai_qa_copilot_api.model_gateway as model_gateway
from ai_qa_copilot_api.model_gateway import (
    B1_MODEL_ID,
    MODEL_GATEWAY_TIMEOUT_SECONDS,
    FakeModelAdapter,
    ModelGateway,
    ModelGatewayConfigurationError,
    ModelGatewayProtocolError,
    ModelGatewaySettings,
    ModelGatewayTimeout,
    ModelUsage,
    OpenAIResponsesAdapter,
    StructuredModelRequest,
    StructuredModelResponse,
    UrllibJsonHttpTransport,
)
from ai_qa_copilot_api.metrics import (
    InMemoryWorkflowMetrics,
    ProviderPricing,
)
from ai_qa_copilot_api.observability import workflow_trace


PRICING = ProviderPricing(
    provider="openai",
    model_id=B1_MODEL_ID,
    pricing_version="test-pricing/v1",
    source_reference="test-fixture",
    input_microusd_per_million_tokens=1_250_000,
    output_microusd_per_million_tokens=2_000_000,
)


def request() -> StructuredModelRequest:
    return StructuredModelRequest(
        correlation_id=uuid4(),
        developer_instruction="Return a concise quality finding.",
        user_input="Synthetic requirement text.",
        schema_name="quality_finding_v1",
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    )


def response(correlation_id: UUID) -> StructuredModelResponse:
    return StructuredModelResponse(
        correlation_id=correlation_id,
        response_id="resp_test_123",
        model_id=B1_MODEL_ID,
        output_json={"summary": "Synthetic finding"},
        usage=ModelUsage(input_tokens=12, output_tokens=4, total_tokens=16),
    )


def test_fake_adapter_drives_a_typed_deterministic_model_call() -> None:
    model_request = request()
    adapter = FakeModelAdapter([response(model_request.correlation_id)])

    model_response = ModelGateway(adapter).generate_structured(model_request)

    assert adapter.requests == [model_request]
    assert model_response.output_json == {"summary": "Synthetic finding"}
    assert model_response.usage.total_tokens == 16
    assert model_response.configuration_version == "B1/v1"


def test_gateway_records_provider_usage_against_configured_pricing() -> None:
    model_request = request()
    metrics = InMemoryWorkflowMetrics()
    timestamps = iter((100.0, 100.125))
    gateway = ModelGateway(
        FakeModelAdapter([response(model_request.correlation_id)]),
        metrics=metrics,
        pricing=PRICING,
        monotonic_clock=lambda: next(timestamps),
    )

    gateway.generate_structured(model_request)

    measurement = metrics.measurements()[0]
    assert measurement.correlation_id == model_request.correlation_id
    assert measurement.trace_id is None
    assert measurement.pricing == PRICING
    assert measurement.outcome == "succeeded"
    assert measurement.duration_ms == 125.0
    assert measurement.retry_count == 0
    assert measurement.input_tokens == 12
    assert measurement.output_tokens == 4
    assert measurement.total_tokens == 16

    summary = metrics.report().summaries[0]
    assert summary.success_count == 1
    assert summary.failure_count == 0
    assert summary.cost_microusd == 23


def test_gateway_records_failure_without_forged_provider_usage() -> None:
    metrics = InMemoryWorkflowMetrics()
    timestamps = iter((50.0, 50.05))
    gateway = ModelGateway(
        FakeModelAdapter([]),
        metrics=metrics,
        pricing=PRICING,
        monotonic_clock=lambda: next(timestamps),
    )

    with pytest.raises(model_gateway.ModelGatewayUnavailable):
        gateway.generate_structured(request())

    measurement = metrics.measurements()[0]
    assert measurement.outcome == "failed"
    assert measurement.duration_ms == 50.0
    assert measurement.input_tokens is None
    assert measurement.output_tokens is None
    assert measurement.total_tokens is None

    summary = metrics.report().summaries[0]
    assert summary.success_count == 0
    assert summary.failure_count == 1
    assert summary.cost_microusd == 0


def test_gateway_links_usage_measurement_to_active_workflow_trace() -> None:
    model_request = request()
    metrics = InMemoryWorkflowMetrics()
    trace_id = uuid4()
    timestamps = iter((10.0, 10.01))
    gateway = ModelGateway(
        FakeModelAdapter([response(model_request.correlation_id)]),
        metrics=metrics,
        pricing=PRICING,
        monotonic_clock=lambda: next(timestamps),
    )

    with workflow_trace(trace_id=trace_id):
        gateway.generate_structured(model_request)

    measurement = metrics.measurements()[0]
    assert measurement.correlation_id == model_request.correlation_id
    assert measurement.trace_id == trace_id


def test_gateway_rejects_partial_accounting_configuration() -> None:
    with pytest.raises(ValueError, match="Metrics and pricing"):
        ModelGateway(
            FakeModelAdapter([]),
            metrics=InMemoryWorkflowMetrics(),
        )

    with pytest.raises(ValueError, match="Metrics and pricing"):
        ModelGateway(
            FakeModelAdapter([]),
            pricing=PRICING,
        )


class RecordingTransport:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": dict(body),
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.payload


def provider_payload() -> Mapping[str, object]:
    return {
        "id": "resp_test_123",
        "model": B1_MODEL_ID,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"summary":"OK"}'}],
            }
        ],
        "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
    }


def test_openai_adapter_uses_fixed_timeout_and_strict_json_schema() -> None:
    transport = RecordingTransport(provider_payload())
    model_request = request()
    adapter = OpenAIResponsesAdapter(
        ModelGatewaySettings(api_key="test-server-only-key"), transport
    )

    model_response = adapter.generate(model_request)

    assert model_response.output_json == {"summary": "OK"}
    assert transport.calls[0]["timeout_seconds"] == MODEL_GATEWAY_TIMEOUT_SECONDS
    body = cast(Mapping[str, object], transport.calls[0]["body"])
    assert body["model"] == B1_MODEL_ID
    assert body["reasoning"] == {"effort": "medium"}
    assert body["text"] == {
        "format": {
            "type": "json_schema",
            "name": "quality_finding_v1",
            "strict": True,
            "schema": model_request.schema,
        }
    }
    assert "test-server-only-key" not in str(body)
    assert transport.calls[0]["headers"] == {
        "Authorization": "Bearer test-server-only-key",
        "Content-Type": "application/json",
    }


def test_provider_rejects_malformed_structured_output() -> None:
    payload = dict(provider_payload())
    payload["output"] = [
        {"type": "message", "content": [{"type": "output_text", "text": "[]"}]}
    ]
    adapter = OpenAIResponsesAdapter(
        ModelGatewaySettings(api_key="test"), RecordingTransport(payload)
    )

    with pytest.raises(
        ModelGatewayProtocolError, match="JSON output must be an object"
    ):
        adapter.generate(request())


def test_provider_rejects_an_unexpected_model() -> None:
    payload = dict(provider_payload())
    payload["model"] = "gpt-5.6"
    adapter = OpenAIResponsesAdapter(
        ModelGatewaySettings(api_key="test"), RecordingTransport(payload)
    )

    with pytest.raises(ModelGatewayProtocolError, match="unexpected model"):
        adapter.generate(request())


def test_timeout_is_normalized_without_provider_detail() -> None:
    class TimeoutTransport:
        def post(self, **_: object) -> Mapping[str, object]:
            raise ModelGatewayTimeout("Model provider timed out")

    adapter = OpenAIResponsesAdapter(
        ModelGatewaySettings(api_key="test"), TimeoutTransport()
    )

    with pytest.raises(ModelGatewayTimeout, match="Model provider timed out"):
        adapter.generate(request())


def test_server_transport_normalizes_invalid_provider_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidJsonResponse:
        def __enter__(self) -> InvalidJsonResponse:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b"not json"

    def invalid_json_urlopen(*_: object, **__: object) -> InvalidJsonResponse:
        return InvalidJsonResponse()

    monkeypatch.setattr(model_gateway, "urlopen", invalid_json_urlopen)

    with pytest.raises(ModelGatewayProtocolError, match="invalid response"):
        UrllibJsonHttpTransport().post(
            url="https://api.openai.com/v1/responses",
            headers={},
            body={},
            timeout_seconds=MODEL_GATEWAY_TIMEOUT_SECONDS,
        )


def test_server_transport_rejects_unpinned_urls_before_opening_them() -> None:
    with pytest.raises(ModelGatewayConfigurationError, match="pinned OpenAI HTTPS"):
        UrllibJsonHttpTransport().post(
            url="http://127.0.0.1/internal",
            headers={},
            body={},
            timeout_seconds=MODEL_GATEWAY_TIMEOUT_SECONDS,
        )


@pytest.mark.parametrize(
    "settings",
    [
        ModelGatewaySettings(api_key=""),
        ModelGatewaySettings(api_key="test", model_id="gpt-5.6"),
        ModelGatewaySettings(api_key="test", timeout_seconds=5.0),
    ],
)
def test_settings_fail_closed_outside_pinned_b1_configuration(
    settings: ModelGatewaySettings,
) -> None:
    with pytest.raises(ModelGatewayConfigurationError):
        settings.validate()
