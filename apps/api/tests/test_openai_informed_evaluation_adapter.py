"""O1/v1 OpenAI Responses adapter for the informed baseline. Fake transport only."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import cast
from uuid import uuid4

import pytest

from ai_qa_copilot_api.model_gateway import (
    C1_MAX_TOKENS,
    C1_TIMEOUT_SECONDS,
    MODEL_PROVIDER_OPENAI,
    OPENAI_RESPONSES_URL,
    ModelGatewayConfigurationError,
    ModelGatewayProtocolError,
    ModelGatewayRefusal,
    ModelGatewayTruncated,
    StructuredModelRequest,
    UrllibJsonHttpTransport,
)
from ai_qa_copilot_api.openai_informed_evaluation_adapter import (
    OPENAI_INFORMED_CONFIGURATION_VERSION,
    OPENAI_INFORMED_DOCUMENTED_MODEL_IDS,
    OpenAIInformedResponse,
    OpenAIInformedResponsesAdapter,
    OpenAIInformedSettings,
)


API_KEY = "test-openai-key-not-real"
VALID_OUTPUT = {
    "boundary": "analysis_only",
    "ground_truth_ids": ["GT-FIND-001"],
    "source_references": ["REQ-BASE-001#REQ-ORDER-004#statement"],
}
SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"boundary": {"type": "string", "enum": ["analysis_only"]}},
    "required": ["boundary"],
    "additionalProperties": False,
}


def openai_payload(
    *,
    input_tokens: int = 7000,
    output_tokens: int = 300,
    reasoning_tokens: int | None = 120,
    output: Mapping[str, object] | None = None,
    **overrides: object,
) -> dict[str, object]:
    usage: dict[str, object] = {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if reasoning_tokens is not None:
        usage["output_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    payload: dict[str, object] = {
        "id": "resp_test",
        "object": "response",
        "model": "gpt-6.1-sol",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "service_tier": "default",
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(dict(output or VALID_OUTPUT)),
                        "annotations": [],
                    }
                ],
            },
        ],
        "usage": usage,
    }
    payload.update(overrides)
    return payload


class FakeTransport:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self._payload = payload
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
            {"url": url, "headers": headers, "body": body, "timeout": timeout_seconds}
        )
        return self._payload


def request() -> StructuredModelRequest:
    return StructuredModelRequest(
        correlation_id=uuid4(),
        developer_instruction="Developer text.",
        user_input="User text.",
        schema_name="informed_observation_v1",
        schema=SCHEMA,
    )


def generate(payload: Mapping[str, object]) -> OpenAIInformedResponse:
    adapter = OpenAIInformedResponsesAdapter(
        OpenAIInformedSettings(api_key=API_KEY), FakeTransport(payload)
    )
    return cast(OpenAIInformedResponse, adapter.generate(request()))


def test_request_body_is_exactly_the_pinned_o1_request() -> None:
    transport = FakeTransport(openai_payload())
    adapter = OpenAIInformedResponsesAdapter(
        OpenAIInformedSettings(api_key=API_KEY), transport
    )

    adapter.generate(request())

    (call,) = transport.calls
    assert call["url"] == OPENAI_RESPONSES_URL
    assert call["timeout"] == 60.0 == C1_TIMEOUT_SECONDS
    assert call["headers"] == {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    assert call["body"] == {
        "model": "gpt-6.1-sol",
        "input": [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": "Developer text."}],
            },
            {"role": "user", "content": [{"type": "input_text", "text": "User text."}]},
        ],
        "reasoning": {"effort": "medium"},
        "max_output_tokens": 4096,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "informed_observation_v1",
                "strict": True,
                "schema": SCHEMA,
            }
        },
        "store": False,
        "service_tier": "default",
        "prompt_cache_options": {"mode": "explicit"},
    }
    body = cast(dict[str, object], call["body"])
    for forbidden in (
        "temperature",
        "top_p",
        "tools",
        "tool_choice",
        "stream",
        "instructions",
        "parallel_tool_calls",
        "prompt_cache_retention",
    ):
        assert forbidden not in body
    # No explicit cache breakpoint anywhere in the request.
    assert "prompt_cache_breakpoint" not in json.dumps(body)
    assert body["max_output_tokens"] == C1_MAX_TOKENS


def test_default_transport_is_the_gateway_transport_pinned_to_openai() -> None:
    adapter = OpenAIInformedResponsesAdapter(OpenAIInformedSettings(api_key=API_KEY))

    assert isinstance(adapter._transport, UrllibJsonHttpTransport)
    with pytest.raises(ModelGatewayConfigurationError, match="pinned OpenAI"):
        UrllibJsonHttpTransport().post(
            url="https://example.invalid/v1/responses",
            headers={},
            body={},
            timeout_seconds=1,
        )


def test_success_returns_output_usage_and_reasoning_tokens() -> None:
    response = generate(openai_payload(reasoning_tokens=120))

    assert response.output_json == VALID_OUTPUT
    assert response.response_id == "resp_test"
    assert response.model_id == "gpt-6.1-sol"
    assert response.provider == MODEL_PROVIDER_OPENAI
    assert response.configuration_version == OPENAI_INFORMED_CONFIGURATION_VERSION
    assert (response.usage.input_tokens, response.usage.output_tokens) == (7000, 300)
    assert response.usage.total_tokens == 7300
    assert response.reasoning_tokens == 120


def test_reasoning_tokens_are_none_when_not_reported() -> None:
    assert generate(openai_payload(reasoning_tokens=None)).reasoning_tokens is None


def test_only_the_documented_model_string_is_accepted() -> None:
    assert OPENAI_INFORMED_DOCUMENTED_MODEL_IDS == frozenset({"gpt-6.1-sol"})


def _without_usage_field(*path: str) -> dict[str, object]:
    payload = openai_payload()
    node = cast(dict[str, object], payload["usage"])
    for key in path[:-1]:
        node = cast(dict[str, object], node[key])
    del node[path[-1]]
    return payload


def _with_usage_details(name: str, value: object) -> dict[str, object]:
    payload = openai_payload()
    usage = cast(dict[str, object], payload["usage"])
    cast(dict[str, object], usage["input_tokens_details"])[name] = value
    return payload


def _with_output(items: list[object]) -> dict[str, object]:
    return openai_payload(output=None) | {"output": items}


def _message(*parts: Mapping[str, object]) -> dict[str, object]:
    return {"type": "message", "role": "assistant", "content": list(parts)}


TEXT_PART = {"type": "output_text", "text": json.dumps(VALID_OUTPUT)}

FAIL_CLOSED: list[
    tuple[str, Callable[[], Mapping[str, object]], type[Exception], str]
] = [
    (
        "wrong object",
        lambda: openai_payload(object="chat.completion"),
        ModelGatewayProtocolError,
        "provenance",
    ),
    (
        "missing id",
        lambda: openai_payload(id=""),
        ModelGatewayProtocolError,
        "provenance",
    ),
    (
        "missing model",
        lambda: openai_payload(model=None),
        ModelGatewayProtocolError,
        "provenance",
    ),
    (
        "undocumented snapshot",
        lambda: openai_payload(model="gpt-6.1-sol-2026-09-01"),
        ModelGatewayProtocolError,
        "unexpected model",
    ),
    (
        "other model",
        lambda: openai_payload(model="gpt-6-sol"),
        ModelGatewayProtocolError,
        "unexpected model",
    ),
    (
        "missing usage",
        lambda: openai_payload(usage=None),
        ModelGatewayProtocolError,
        "missing usage",
    ),
    (
        "missing input tokens",
        lambda: _without_usage_field("input_tokens"),
        ModelGatewayProtocolError,
        "invalid usage",
    ),
    (
        "negative output tokens",
        lambda: openai_payload(output_tokens=-1),
        ModelGatewayProtocolError,
        "invalid usage",
    ),
    (
        "bool total",
        lambda: (
            openai_payload()
            | {
                "usage": {
                    **cast(dict[str, object], openai_payload()["usage"]),
                    "total_tokens": True,
                }
            }
        ),
        ModelGatewayProtocolError,
        "invalid usage",
    ),
    (
        "missing input details",
        lambda: _without_usage_field("input_tokens_details"),
        ModelGatewayProtocolError,
        "invalid usage",
    ),
    (
        "missing cached tokens",
        lambda: _without_usage_field("input_tokens_details", "cached_tokens"),
        ModelGatewayProtocolError,
        "invalid usage",
    ),
    (
        "missing cache write tokens",
        lambda: _without_usage_field("input_tokens_details", "cache_write_tokens"),
        ModelGatewayProtocolError,
        "invalid usage",
    ),
    (
        "cached tokens",
        lambda: _with_usage_details("cached_tokens", 5),
        ModelGatewayProtocolError,
        "unpriced cache usage",
    ),
    (
        "cache write tokens",
        lambda: _with_usage_details("cache_write_tokens", 5),
        ModelGatewayProtocolError,
        "unpriced cache usage",
    ),
    (
        "reasoning above output",
        lambda: openai_payload(output_tokens=100, reasoning_tokens=101),
        ModelGatewayProtocolError,
        "more reasoning than output",
    ),
    (
        "bad reasoning count",
        lambda: openai_payload(reasoning_tokens=-1),
        ModelGatewayProtocolError,
        "invalid usage",
    ),
    (
        "priority tier",
        lambda: openai_payload(service_tier="priority"),
        ModelGatewayProtocolError,
        "processing tier",
    ),
    (
        "flex tier",
        lambda: openai_payload(service_tier="flex"),
        ModelGatewayProtocolError,
        "processing tier",
    ),
    (
        "missing tier",
        lambda: openai_payload(service_tier=None),
        ModelGatewayProtocolError,
        "processing tier",
    ),
    (
        "error object",
        lambda: openai_payload(error={"code": "server_error"}),
        ModelGatewayProtocolError,
        "reported an error",
    ),
    (
        "truncated",
        lambda: openai_payload(
            status="incomplete", incomplete_details={"reason": "max_output_tokens"}
        ),
        ModelGatewayTruncated,
        "truncated",
    ),
    (
        "content filter",
        lambda: openai_payload(
            status="incomplete", incomplete_details={"reason": "content_filter"}
        ),
        ModelGatewayRefusal,
        "declined",
    ),
    (
        "other incomplete",
        lambda: openai_payload(status="incomplete", incomplete_details=None),
        ModelGatewayProtocolError,
        "stopped unexpectedly",
    ),
    (
        "failed status",
        lambda: openai_payload(status="failed"),
        ModelGatewayProtocolError,
        "stopped unexpectedly",
    ),
    (
        "in progress",
        lambda: openai_payload(status="in_progress"),
        ModelGatewayProtocolError,
        "stopped unexpectedly",
    ),
    (
        "refusal part",
        lambda: _with_output([_message({"type": "refusal", "refusal": "No."})]),
        ModelGatewayRefusal,
        "declined",
    ),
    (
        "function call item",
        lambda: _with_output(
            [
                {"type": "function_call", "name": "x", "arguments": "{}"},
                _message(TEXT_PART),
            ]
        ),
        ModelGatewayProtocolError,
        "unexpected output item",
    ),
    (
        "non-assistant message",
        lambda: _with_output(
            [{"type": "message", "role": "user", "content": [TEXT_PART]}]
        ),
        ModelGatewayProtocolError,
        "unexpected output item",
    ),
    (
        "two messages",
        lambda: _with_output([_message(TEXT_PART), _message(TEXT_PART)]),
        ModelGatewayProtocolError,
        "multiple messages",
    ),
    (
        "two text parts",
        lambda: _with_output([_message(TEXT_PART, TEXT_PART)]),
        ModelGatewayProtocolError,
        "multiple text parts",
    ),
    (
        "unknown part",
        lambda: _with_output([_message({"type": "output_audio"})]),
        ModelGatewayProtocolError,
        "unexpected content part",
    ),
    (
        "no text",
        lambda: _with_output([{"type": "reasoning", "summary": []}]),
        ModelGatewayProtocolError,
        "missing output text",
    ),
    (
        "missing output",
        lambda: openai_payload(output=None) | {"output": None},
        ModelGatewayProtocolError,
        "missing output",
    ),
    (
        "not json",
        lambda: _with_output([_message({"type": "output_text", "text": "not json"})]),
        ModelGatewayProtocolError,
        "valid JSON",
    ),
    (
        "json array",
        lambda: _with_output([_message({"type": "output_text", "text": "[]"})]),
        ModelGatewayProtocolError,
        "must be an object",
    ),
]


@pytest.mark.parametrize(
    ("payload", "error", "message"),
    [(payload, error, message) for _, payload, error, message in FAIL_CLOSED],
    ids=[name for name, *_ in FAIL_CLOSED],
)
def test_response_fails_closed(
    payload: Callable[[], Mapping[str, object]], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message) as raised:
        generate(payload())

    assert API_KEY not in str(raised.value)


def test_usage_is_validated_before_status() -> None:
    # A truncated response with cache usage is reported as cache usage: usage is
    # billed whatever the status, so it is checked first.
    payload = _with_usage_details("cache_write_tokens", 7) | {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    with pytest.raises(ModelGatewayProtocolError, match="unpriced cache usage"):
        generate(payload)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"api_key": ""}, "OPENAI_API_KEY"),
        ({"model_id": "gpt-6-sol"}, "gpt-6.1-sol"),
        ({"reasoning_effort": "high"}, "medium"),
        ({"max_output_tokens": 8192}, "4096"),
        ({"timeout_seconds": 10.0}, "60 second"),
        ({"service_tier": "auto"}, "default service tier"),
    ],
)
def test_settings_refuse_any_other_configuration(
    change: dict[str, object], message: str
) -> None:
    settings = OpenAIInformedSettings(**{"api_key": API_KEY, **change})  # type: ignore[arg-type]

    with pytest.raises(ModelGatewayConfigurationError, match=message):
        OpenAIInformedResponsesAdapter(settings, FakeTransport(openai_payload()))


def test_settings_read_only_the_openai_key_from_the_environment() -> None:
    settings = OpenAIInformedSettings.from_mapping(
        {"OPENAI_API_KEY": f"  {API_KEY}  ", "MODEL_PROVIDER": "anthropic"}
    )

    assert settings == OpenAIInformedSettings(api_key=API_KEY)
