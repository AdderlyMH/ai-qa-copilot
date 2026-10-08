"""Direct, pinned OpenAI Responses API adapter for the informed baseline (O1/v1).

Mirrors ``AnthropicMessagesAdapter`` (C1/v1) in ``model_gateway.py``: one request,
no tools, no streaming, no retry or repair loop, the gateway's error taxonomy, and
the same 60-second timeout. Only the request wrapper differs from the Claude path;
the developer text, user text and JSON Schema are passed through unchanged.

Request settings, each verified 2026-10-08 on developers.openai.com (ADR-016):

- ``model`` ``gpt-6.1-sol``; ``reasoning.effort`` ``medium``.
- ``max_output_tokens`` 4096, which covers visible output and reasoning tokens.
- ``text.format``: ``json_schema`` with ``name`` and ``strict: true``.
- ``store: false`` (the default is ``true``).
- ``service_tier: "default"`` (standard processing; the default ``auto`` follows
  the project setting, which could select another tier and price).
- ``prompt_cache_options.mode: "explicit"`` with no breakpoints: "the request
  does not use prompt caching or create cache writes".
- No ``temperature``, ``top_p``, ``tools`` or ``stream``.

Fail closed (typed ``ModelGateway*`` errors) on: missing provenance; a model other
than a documented ``gpt-6.1-sol`` snapshot; missing or invalid usage; nonzero
``cached_tokens`` or ``cache_write_tokens``; reasoning tokens above output tokens;
a processing tier other than ``default``; any error object; status ``incomplete``
(``max_output_tokens`` is truncation, ``content_filter`` a refusal) or any status
other than ``completed``; a refusal part; any output item other than reasoning and
one assistant message; any content part other than one ``output_text``; and
output that is not a JSON object. Usage is checked before status because an
incomplete or refused response is still billed. The API key is sent only in the
``Authorization`` header and never appears in errors.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from ai_qa_copilot_api.model_gateway import (
    MODEL_PROVIDER_OPENAI,
    OPENAI_RESPONSES_URL,
    JsonHttpTransport,
    ModelGatewayConfigurationError,
    ModelGatewayProtocolError,
    ModelGatewayRefusal,
    ModelGatewayTruncated,
    ModelUsage,
    StructuredModelRequest,
    StructuredModelResponse,
    UrllibJsonHttpTransport,
)


OPENAI_INFORMED_MODEL_ID: Final = "gpt-6.1-sol"
# Snapshots listed on https://developers.openai.com/api/docs/models/gpt-6.1-sol
# (checked 2026-10-08): only "gpt-6.1-sol"; no dated snapshot is documented. A
# response reporting any other model string fails closed until documented here.
OPENAI_INFORMED_DOCUMENTED_MODEL_IDS: Final = frozenset({OPENAI_INFORMED_MODEL_ID})
OPENAI_INFORMED_REASONING_EFFORT: Final = "medium"
OPENAI_INFORMED_MAX_OUTPUT_TOKENS: Final = 4096
OPENAI_INFORMED_TIMEOUT_SECONDS: Final = 60.0
OPENAI_INFORMED_SERVICE_TIER: Final = "default"
OPENAI_INFORMED_CONFIGURATION_VERSION: Final = "O1/v1"

_IGNORED_OUTPUT_ITEM_TYPES: Final = frozenset({"reasoning"})


@dataclass(frozen=True)
class OpenAIInformedSettings:
    """Pinned O1/v1 configuration, sourced only from server environment."""

    api_key: str
    model_id: str = OPENAI_INFORMED_MODEL_ID
    reasoning_effort: str = OPENAI_INFORMED_REASONING_EFFORT
    max_output_tokens: int = OPENAI_INFORMED_MAX_OUTPUT_TOKENS
    timeout_seconds: float = OPENAI_INFORMED_TIMEOUT_SECONDS
    service_tier: str = OPENAI_INFORMED_SERVICE_TIER

    @classmethod
    def from_environment(cls) -> OpenAIInformedSettings:
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, environment: Mapping[str, str]) -> OpenAIInformedSettings:
        return cls(api_key=environment.get("OPENAI_API_KEY", "").strip())

    def validate(self) -> None:
        if not self.api_key:
            raise ModelGatewayConfigurationError("OPENAI_API_KEY must be configured")
        if self.model_id != OPENAI_INFORMED_MODEL_ID:
            raise ModelGatewayConfigurationError("O1/v1 requires model gpt-6.1-sol")
        if self.reasoning_effort != OPENAI_INFORMED_REASONING_EFFORT:
            raise ModelGatewayConfigurationError(
                "O1/v1 requires medium reasoning effort"
            )
        if self.max_output_tokens != OPENAI_INFORMED_MAX_OUTPUT_TOKENS:
            raise ModelGatewayConfigurationError(
                "O1/v1 requires 4096 max output tokens"
            )
        if self.timeout_seconds != OPENAI_INFORMED_TIMEOUT_SECONDS:
            raise ModelGatewayConfigurationError("O1/v1 requires a 60 second timeout")
        if self.service_tier != OPENAI_INFORMED_SERVICE_TIER:
            raise ModelGatewayConfigurationError(
                "O1/v1 requires the default service tier"
            )


@dataclass(frozen=True)
class OpenAIInformedResponse(StructuredModelResponse):
    """A structured response plus the content-free reasoning-token count, if reported."""

    reasoning_tokens: int | None = None


class OpenAIInformedResponsesAdapter:
    """Direct, pinned OpenAI Responses API adapter for O1/v1.

    One request, no tools, no streaming, no retry or repair loop.
    """

    def __init__(
        self,
        settings: OpenAIInformedSettings,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        settings.validate()
        self._settings = settings
        # The gateway transport is pinned to the OpenAI Responses URL only.
        self._transport = transport or UrllibJsonHttpTransport()

    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        request.validate()
        payload = self._transport.post(
            url=OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
            },
            body=openai_informed_request_body(self._settings, request),
            timeout_seconds=self._settings.timeout_seconds,
        )
        return openai_informed_response_from_payload(payload, request.correlation_id)


def openai_informed_request_body(
    settings: OpenAIInformedSettings, request: StructuredModelRequest
) -> dict[str, object]:
    """The exact Responses API request body (no credential)."""

    return {
        "model": settings.model_id,
        "input": [
            {
                "role": "developer",
                "content": [
                    {"type": "input_text", "text": request.developer_instruction}
                ],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": request.user_input}],
            },
        ],
        "reasoning": {"effort": settings.reasoning_effort},
        "max_output_tokens": settings.max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": request.schema_name,
                "strict": True,
                "schema": dict(request.schema),
            }
        },
        "store": False,
        "service_tier": settings.service_tier,
        "prompt_cache_options": {"mode": "explicit"},
    }


def openai_informed_response_from_payload(
    payload: Mapping[str, object], correlation_id: UUID
) -> OpenAIInformedResponse:
    response_id = payload.get("id")
    model_id = payload.get("model")
    if (
        payload.get("object") != "response"
        or not isinstance(response_id, str)
        or not response_id
        or not isinstance(model_id, str)
    ):
        raise ModelGatewayProtocolError("Model provider response is missing provenance")
    if model_id not in OPENAI_INFORMED_DOCUMENTED_MODEL_IDS:
        raise ModelGatewayProtocolError("Model provider returned an unexpected model")

    # Usage is billed even for refusals and truncation, so validate it first.
    usage, reasoning_tokens = _usage_from_payload(payload.get("usage"))

    if payload.get("service_tier") != OPENAI_INFORMED_SERVICE_TIER:
        raise ModelGatewayProtocolError(
            "Model provider used an unexpected processing tier"
        )
    if payload.get("error") is not None:
        raise ModelGatewayProtocolError("Model provider reported an error")

    status = payload.get("status")
    if status == "incomplete":
        details = payload.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        if reason == "max_output_tokens":
            raise ModelGatewayTruncated("Model provider output was truncated")
        if reason == "content_filter":
            raise ModelGatewayRefusal("Model provider declined the request")
        raise ModelGatewayProtocolError("Model provider stopped unexpectedly")
    if status != "completed":
        raise ModelGatewayProtocolError("Model provider stopped unexpectedly")

    output_text = _output_text(payload.get("output"))
    try:
        output_json = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise ModelGatewayProtocolError(
            "Model provider did not return valid JSON"
        ) from error
    if not isinstance(output_json, dict):
        raise ModelGatewayProtocolError("Model provider JSON output must be an object")
    return OpenAIInformedResponse(
        correlation_id=correlation_id,
        response_id=response_id,
        model_id=model_id,
        output_json=output_json,
        usage=usage,
        configuration_version=OPENAI_INFORMED_CONFIGURATION_VERSION,
        provider=MODEL_PROVIDER_OPENAI,
        reasoning_tokens=reasoning_tokens,
    )


def _output_text(value: object) -> str:
    """Return the one output_text part; tolerate reasoning items, reject the rest."""

    if not isinstance(value, list):
        raise ModelGatewayProtocolError("Model provider response is missing output")
    texts: list[str] = []
    messages = 0
    for item in value:
        if not isinstance(item, dict):
            raise ModelGatewayProtocolError("Model provider returned an invalid item")
        item_type = item.get("type")
        if item_type in _IGNORED_OUTPUT_ITEM_TYPES:
            continue
        if item_type != "message" or item.get("role") != "assistant":
            # No tool-calling loop: a tool call or any unknown item is never acted on.
            raise ModelGatewayProtocolError(
                "Model provider returned an unexpected output item"
            )
        messages += 1
        content = item.get("content")
        if not isinstance(content, list):
            raise ModelGatewayProtocolError("Model provider returned an invalid item")
        for part in content:
            if not isinstance(part, dict):
                raise ModelGatewayProtocolError(
                    "Model provider returned an invalid part"
                )
            part_type = part.get("type")
            if part_type == "refusal":
                raise ModelGatewayRefusal("Model provider declined the request")
            if part_type != "output_text":
                raise ModelGatewayProtocolError(
                    "Model provider returned an unexpected content part"
                )
            text = part.get("text")
            if not isinstance(text, str):
                raise ModelGatewayProtocolError(
                    "Model provider returned an invalid part"
                )
            texts.append(text)
    if messages > 1:
        raise ModelGatewayProtocolError("Model provider returned multiple messages")
    if not texts:
        raise ModelGatewayProtocolError(
            "Model provider response is missing output text"
        )
    if len(texts) > 1:
        raise ModelGatewayProtocolError("Model provider returned multiple text parts")
    return texts[0]


def _usage_from_payload(value: object) -> tuple[ModelUsage, int | None]:
    if not isinstance(value, dict):
        raise ModelGatewayProtocolError("Model provider response is missing usage")
    input_tokens = _count(value.get("input_tokens"))
    output_tokens = _count(value.get("output_tokens"))
    total_tokens = _count(value.get("total_tokens"))

    input_details = value.get("input_tokens_details")
    if not isinstance(input_details, dict):
        raise ModelGatewayProtocolError("Model provider response has invalid usage")
    for cache_field in ("cached_tokens", "cache_write_tokens"):
        # Both fields are documented; a missing count cannot be shown to be zero.
        if _count(input_details.get(cache_field)) != 0:
            # Caching is disabled and only uncached input is priced; fail closed
            # rather than undercount cost.
            raise ModelGatewayProtocolError(
                "Model provider reported unpriced cache usage"
            )

    reasoning_tokens: int | None = None
    output_details = value.get("output_tokens_details")
    if output_details is not None:
        if not isinstance(output_details, dict):
            raise ModelGatewayProtocolError("Model provider response has invalid usage")
        if output_details.get("reasoning_tokens") is not None:
            reported = _count(output_details.get("reasoning_tokens"))
            if reported > output_tokens:
                # Charges assume output_tokens includes reasoning tokens.
                raise ModelGatewayProtocolError(
                    "Model provider reported more reasoning than output tokens"
                )
            reasoning_tokens = reported

    return (
        ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        ),
        reasoning_tokens,
    )


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelGatewayProtocolError("Model provider response has invalid usage")
    return value
