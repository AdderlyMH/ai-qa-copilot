from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID, uuid4

import pytest

import ai_qa_copilot_api.model_gateway as model_gateway
from ai_qa_copilot_api.model_gateway import (
    ANTHROPIC_MESSAGES_URL,
    B1_MODEL_ID,
    C1_TIMEOUT_SECONDS,
    AnthropicMessagesAdapter,
    AnthropicUrllibJsonHttpTransport,
    ModelGatewayRefusal,
    ModelGatewayTruncated,
    ModelGatewayUnavailable,
    C1_CONFIGURATION_VERSION,
    C1_MODEL_ID,
    AnthropicGatewaySettings,
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
    model_provider_from_mapping,
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


def anthropic_payload() -> dict[str, object]:
    return {
        "id": "msg_test_123",
        "type": "message",
        "role": "assistant",
        "model": C1_MODEL_ID,
        "content": [{"type": "text", "text": '{"summary":"OK"}'}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 4},
    }


def anthropic_adapter(payload: Mapping[str, object]) -> AnthropicMessagesAdapter:
    return AnthropicMessagesAdapter(
        AnthropicGatewaySettings(api_key="test-server-only-key"),
        RecordingTransport(payload),
    )


def test_anthropic_adapter_builds_one_pinned_structured_request() -> None:
    transport = RecordingTransport(anthropic_payload())
    model_request = request()
    adapter = AnthropicMessagesAdapter(
        AnthropicGatewaySettings(api_key="test-server-only-key"), transport
    )

    model_response = adapter.generate(model_request)

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == ANTHROPIC_MESSAGES_URL
    assert call["timeout_seconds"] == C1_TIMEOUT_SECONDS
    assert call["headers"] == {
        "x-api-key": "test-server-only-key",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = cast(Mapping[str, object], call["body"])
    assert body == {
        "model": "claude-sonnet-5-5",
        "max_tokens": 4096,
        "system": model_request.developer_instruction,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": model_request.user_input}],
            }
        ],
        "output_config": {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": model_request.schema},
        },
    }
    assert "tools" not in body
    assert "stream" not in body
    assert "test-server-only-key" not in str(body)
    assert model_response.correlation_id == model_request.correlation_id
    assert model_response.response_id == "msg_test_123"
    assert model_response.model_id == "claude-sonnet-5-5"
    assert model_response.output_json == {"summary": "OK"}
    assert model_response.configuration_version == "C1/v1"


def test_anthropic_usage_total_is_input_plus_output() -> None:
    usage = anthropic_adapter(anthropic_payload()).generate(request()).usage

    assert usage == ModelUsage(input_tokens=12, output_tokens=4, total_tokens=16)


def test_anthropic_usage_is_not_taken_from_a_provider_total() -> None:
    payload = anthropic_payload()
    payload["usage"] = {"input_tokens": 7, "output_tokens": 3, "total_tokens": 999}

    assert anthropic_adapter(payload).generate(request()).usage.total_tokens == 10


def test_anthropic_adapter_ignores_thinking_blocks() -> None:
    payload = anthropic_payload()
    payload["content"] = [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "redacted_thinking", "data": "opaque"},
        {"type": "text", "text": '{"summary":"OK"}'},
    ]

    response = anthropic_adapter(payload).generate(request())

    assert response.output_json == {"summary": "OK"}


def test_anthropic_refusal_is_a_distinct_unavailable_error() -> None:
    payload = anthropic_payload()
    payload["stop_reason"] = "refusal"
    payload["content"] = [{"type": "text", "text": "I can't help with that."}]

    with pytest.raises(ModelGatewayRefusal, match="declined") as error:
        anthropic_adapter(payload).generate(request())

    assert isinstance(error.value, ModelGatewayUnavailable)
    assert "can't help" not in str(error.value)


def test_anthropic_truncation_is_rejected_even_if_json_looks_complete() -> None:
    payload = anthropic_payload()
    payload["stop_reason"] = "max_tokens"

    with pytest.raises(ModelGatewayTruncated, match="truncated"):
        anthropic_adapter(payload).generate(request())


@pytest.mark.parametrize(
    "stop_reason", ["tool_use", "pause_turn", "stop_sequence", None]
)
def test_anthropic_unexpected_stop_reasons_fail_closed(stop_reason: object) -> None:
    payload = anthropic_payload()
    payload["stop_reason"] = stop_reason

    with pytest.raises(ModelGatewayProtocolError, match="stopped unexpectedly"):
        anthropic_adapter(payload).generate(request())


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "missing output"),
        ("text", "missing output"),
        ([], "missing output text"),
        ([{"type": "thinking", "thinking": ""}], "missing output text"),
        (["text"], "invalid block"),
        ([{"type": "text"}], "invalid block"),
        ([{"type": "text", "text": 5}], "invalid block"),
        (
            [
                {"type": "tool_use", "id": "toolu_1", "name": "x", "input": {}},
                {"type": "text", "text": '{"summary":"OK"}'},
            ],
            "unexpected content block",
        ),
        ([{"type": "server_tool_use"}], "unexpected content block"),
        (
            [
                {"type": "text", "text": '{"summary":"A"}'},
                {"type": "text", "text": '{"summary":"B"}'},
            ],
            "multiple text blocks",
        ),
        ([{"type": "text", "text": "not json"}], "valid JSON"),
        ([{"type": "text", "text": "[]"}], "must be an object"),
        ([{"type": "text", "text": '"x"'}], "must be an object"),
    ],
)
def test_anthropic_content_block_shapes_fail_closed(
    content: object, message: str
) -> None:
    payload = anthropic_payload()
    payload["content"] = content

    with pytest.raises(ModelGatewayProtocolError, match=message):
        anthropic_adapter(payload).generate(request())


@pytest.mark.parametrize(
    "mutation",
    [
        {"id": None},
        {"id": ""},
        {"id": 5},
        {"model": None},
        {"type": "error"},
        {"role": "user"},
    ],
)
def test_anthropic_missing_provenance_fails_closed(mutation: dict[str, object]) -> None:
    payload = {**anthropic_payload(), **mutation}

    with pytest.raises(ModelGatewayProtocolError, match="missing provenance"):
        anthropic_adapter(payload).generate(request())


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5", ""])
def test_anthropic_unexpected_model_fails_closed(model: str) -> None:
    payload = {**anthropic_payload(), "model": model}

    with pytest.raises(ModelGatewayProtocolError, match="unexpected model"):
        anthropic_adapter(payload).generate(request())


@pytest.mark.parametrize(
    "usage",
    [
        None,
        "usage",
        {},
        {"input_tokens": 1},
        {"output_tokens": 1},
        {"input_tokens": -1, "output_tokens": 1},
        {"input_tokens": 1, "output_tokens": -1},
        {"input_tokens": 1.5, "output_tokens": 1},
        {"input_tokens": "1", "output_tokens": 1},
        {"input_tokens": True, "output_tokens": 1},
        {"input_tokens": 1, "output_tokens": False},
    ],
)
def test_anthropic_missing_or_invalid_usage_fails_closed(usage: object) -> None:
    payload = anthropic_payload()
    payload["usage"] = usage

    with pytest.raises(ModelGatewayProtocolError, match="usage"):
        anthropic_adapter(payload).generate(request())


def test_anthropic_refusal_and_truncation_still_require_valid_usage() -> None:
    payload = anthropic_payload()
    payload["stop_reason"] = "refusal"
    payload["usage"] = {}

    with pytest.raises(ModelGatewayProtocolError, match="usage"):
        anthropic_adapter(payload).generate(request())


@pytest.mark.parametrize(
    "cache_usage",
    [
        {"cache_creation_input_tokens": 5},
        {"cache_read_input_tokens": 5},
        {"cache_read_input_tokens": True},
        {"cache_creation_input_tokens": "0"},
    ],
)
def test_anthropic_unpriced_cache_usage_fails_closed(
    cache_usage: dict[str, object],
) -> None:
    payload = anthropic_payload()
    payload["usage"] = {"input_tokens": 12, "output_tokens": 4, **cache_usage}

    with pytest.raises(ModelGatewayProtocolError, match="cache usage"):
        anthropic_adapter(payload).generate(request())


def test_anthropic_zero_cache_usage_is_accepted() -> None:
    payload = anthropic_payload()
    payload["usage"] = {
        "input_tokens": 12,
        "output_tokens": 4,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    assert anthropic_adapter(payload).generate(request()).usage.total_tokens == 16


def test_anthropic_adapter_propagates_normalized_transport_errors() -> None:
    class FailingTransport:
        def __init__(self, error: Exception) -> None:
            self._error = error

        def post(self, **_: object) -> Mapping[str, object]:
            raise self._error

    settings = AnthropicGatewaySettings(api_key="test")
    for error in (
        ModelGatewayTimeout("Model provider timed out"),
        ModelGatewayUnavailable("Model provider is unavailable"),
    ):
        with pytest.raises(type(error)):
            AnthropicMessagesAdapter(settings, FailingTransport(error)).generate(
                request()
            )


def test_anthropic_adapter_rejects_unsafe_settings_before_any_request() -> None:
    transport = RecordingTransport(anthropic_payload())

    with pytest.raises(ModelGatewayConfigurationError):
        AnthropicMessagesAdapter(AnthropicGatewaySettings(api_key=""), transport)

    assert transport.calls == []


def test_gateway_accounts_anthropic_usage_against_anthropic_pricing() -> None:
    model_request = request()
    metrics = InMemoryWorkflowMetrics()
    pricing = ProviderPricing(
        provider="anthropic",
        model_id=C1_MODEL_ID,
        pricing_version="test-pricing/v1",
        source_reference="test-fixture",
        input_microusd_per_million_tokens=2_000_000,
        output_microusd_per_million_tokens=10_000_000,
    )
    timestamps = iter((1.0, 1.5))
    gateway = ModelGateway(
        anthropic_adapter(anthropic_payload()),
        metrics=metrics,
        pricing=pricing,
        monotonic_clock=lambda: next(timestamps),
    )

    gateway.generate_structured(model_request)

    measurement = metrics.measurements()[0]
    assert measurement.pricing == pricing
    assert (measurement.input_tokens, measurement.output_tokens) == (12, 4)
    assert measurement.total_tokens == 16
    assert metrics.report().summaries[0].cost_microusd == 64


def test_gateway_rejects_anthropic_response_priced_as_another_model() -> None:
    metrics = InMemoryWorkflowMetrics()
    gateway = ModelGateway(
        anthropic_adapter(anthropic_payload()),
        metrics=metrics,
        pricing=PRICING,
    )

    with pytest.raises(ValueError, match="does not match configured pricing"):
        gateway.generate_structured(request())


def test_anthropic_transport_pins_only_the_messages_endpoint() -> None:
    assert ANTHROPIC_MESSAGES_URL == "https://api.anthropic.com/v1/messages"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.anthropic.com/v1/messages",
        "https://api.anthropic.com/v1/messages/batches",
        "https://api.anthropic.com/v1/messages?x=1",
        "https://api.anthropic.com/v1/messages/",
        "https://api.anthropic.com.evil.example/v1/messages",
        "https://api.openai.com/v1/responses",
        "http://127.0.0.1/internal",
    ],
)
def test_anthropic_transport_rejects_unpinned_urls_before_opening_them(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_urlopen(*_: object, **__: object) -> object:
        raise AssertionError("urlopen must not be reached")

    monkeypatch.setattr(model_gateway, "urlopen", forbidden_urlopen)

    with pytest.raises(ModelGatewayConfigurationError, match="pinned Anthropic HTTPS"):
        AnthropicUrllibJsonHttpTransport().post(
            url=url, headers={}, body={}, timeout_seconds=C1_TIMEOUT_SECONDS
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://api.anthropic.com/v1/messages",
        "https://api.anthropic.com/v1/messages/batches",
    ],
)
def test_openai_transport_allowlist_was_not_widened_to_anthropic(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_urlopen(*_: object, **__: object) -> object:
        raise AssertionError("urlopen must not be reached")

    monkeypatch.setattr(model_gateway, "urlopen", forbidden_urlopen)

    with pytest.raises(ModelGatewayConfigurationError, match="pinned OpenAI HTTPS"):
        UrllibJsonHttpTransport().post(
            url=url, headers={}, body={}, timeout_seconds=MODEL_GATEWAY_TIMEOUT_SECONDS
        )


def test_anthropic_transport_posts_to_the_pinned_endpoint_and_normalizes_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[str, float]] = []

    class JsonResponse:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def __enter__(self) -> JsonResponse:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return self._data

    def ok_urlopen(request: object, timeout: float) -> JsonResponse:
        opened.append((getattr(request, "full_url"), timeout))
        return JsonResponse(b'{"id":"msg_1"}')

    monkeypatch.setattr(model_gateway, "urlopen", ok_urlopen)
    transport = AnthropicUrllibJsonHttpTransport()

    payload = transport.post(
        url=ANTHROPIC_MESSAGES_URL, headers={}, body={}, timeout_seconds=60.0
    )

    assert payload == {"id": "msg_1"}
    assert opened == [(ANTHROPIC_MESSAGES_URL, 60.0)]

    for data, expected in (
        (b"not json", ModelGatewayProtocolError),
        (b"[]", ModelGatewayProtocolError),
    ):
        monkeypatch.setattr(
            model_gateway, "urlopen", lambda *_, d=data, **__: JsonResponse(d)
        )
        with pytest.raises(expected, match="invalid response"):
            transport.post(
                url=ANTHROPIC_MESSAGES_URL, headers={}, body={}, timeout_seconds=60.0
            )

    def timing_out_urlopen(*_: object, **__: object) -> object:
        raise TimeoutError("socket detail")

    monkeypatch.setattr(model_gateway, "urlopen", timing_out_urlopen)
    with pytest.raises(ModelGatewayTimeout, match="timed out") as timeout_error:
        transport.post(
            url=ANTHROPIC_MESSAGES_URL, headers={}, body={}, timeout_seconds=60.0
        )
    assert "socket detail" not in str(timeout_error.value)

    def unavailable_urlopen(*_: object, **__: object) -> object:
        raise OSError("secret-host-detail")

    monkeypatch.setattr(model_gateway, "urlopen", unavailable_urlopen)
    with pytest.raises(ModelGatewayUnavailable, match="unavailable") as down_error:
        transport.post(
            url=ANTHROPIC_MESSAGES_URL, headers={}, body={}, timeout_seconds=60.0
        )
    assert "secret-host-detail" not in str(down_error.value)


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


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, "openai"),
        ({"MODEL_PROVIDER": ""}, "openai"),
        ({"MODEL_PROVIDER": "  "}, "openai"),
        ({"MODEL_PROVIDER": "openai"}, "openai"),
        ({"MODEL_PROVIDER": "anthropic"}, "anthropic"),
        ({"MODEL_PROVIDER": " anthropic "}, "anthropic"),
    ],
)
def test_provider_selection_defaults_to_openai(
    environment: Mapping[str, str], expected: str
) -> None:
    assert model_provider_from_mapping(environment) == expected


@pytest.mark.parametrize(
    "provider", ["Anthropic", "claude", "azure", "openai,anthropic"]
)
def test_provider_selection_fails_closed_on_unknown_values(provider: str) -> None:
    with pytest.raises(ModelGatewayConfigurationError, match="MODEL_PROVIDER"):
        model_provider_from_mapping({"MODEL_PROVIDER": provider})


def test_anthropic_settings_read_only_the_anthropic_credential() -> None:
    settings = AnthropicGatewaySettings.from_mapping(
        {"ANTHROPIC_API_KEY": " test-anthropic-key ", "OPENAI_API_KEY": "other"}
    )

    settings.validate()
    assert settings.api_key == "test-anthropic-key"
    assert settings.model_id == C1_MODEL_ID == "claude-sonnet-5-5"
    assert settings.effort == "medium"
    assert settings.max_tokens == 4096
    assert settings.timeout_seconds == 60.0
    assert C1_CONFIGURATION_VERSION == "C1/v1"


def test_openai_settings_ignore_the_anthropic_credential() -> None:
    settings = ModelGatewaySettings.from_mapping({"ANTHROPIC_API_KEY": "test"})

    with pytest.raises(ModelGatewayConfigurationError, match="OPENAI_API_KEY"):
        settings.validate()


@pytest.mark.parametrize(
    "settings",
    [
        AnthropicGatewaySettings(api_key=""),
        AnthropicGatewaySettings(api_key="test", model_id="claude-opus-5-5"),
        AnthropicGatewaySettings(api_key="test", effort="high"),
        AnthropicGatewaySettings(api_key="test", max_tokens=64_000),
        AnthropicGatewaySettings(api_key="test", timeout_seconds=10.0),
    ],
)
def test_anthropic_settings_fail_closed_outside_pinned_c1_configuration(
    settings: AnthropicGatewaySettings,
) -> None:
    with pytest.raises(ModelGatewayConfigurationError):
        settings.validate()


def test_anthropic_configuration_error_does_not_echo_the_credential() -> None:
    settings = AnthropicGatewaySettings(
        api_key="secret-test-value", model_id="claude-opus-5-5"
    )

    with pytest.raises(ModelGatewayConfigurationError) as error:
        settings.validate()

    assert "secret-test-value" not in str(error.value)
