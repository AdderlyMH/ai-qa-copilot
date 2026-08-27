"""Small server-only OpenAI Responses API gateway for the SKEL-004 proof."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OPENAI_RESPONSES_URL: Final = "https://api.openai.com/v1/responses"
B1_MODEL_ID: Final = "gpt-5.6-terra"
B1_REASONING_EFFORT: Final = "medium"
MODEL_GATEWAY_TIMEOUT_SECONDS: Final = 10.0
MODEL_GATEWAY_CONFIGURATION_VERSION: Final = "B1/v1"


class ModelGatewayConfigurationError(RuntimeError):
    """Raised when the server-side model configuration is unsafe or incomplete."""


class ModelGatewayUnavailable(RuntimeError):
    """Safe normalized provider failure; it deliberately contains no credentials."""


class ModelGatewayTimeout(ModelGatewayUnavailable):
    """Raised when the provider does not respond before the fixed timeout."""


class ModelGatewayProtocolError(ModelGatewayUnavailable):
    """Raised when the provider response cannot satisfy the typed contract."""


@dataclass(frozen=True)
class ModelGatewaySettings:
    """Pinned B1/v1 provider configuration, sourced only from server environment."""

    api_key: str
    model_id: str = B1_MODEL_ID
    reasoning_effort: str = B1_REASONING_EFFORT
    timeout_seconds: float = MODEL_GATEWAY_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls) -> ModelGatewaySettings:
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, environment: Mapping[str, str]) -> ModelGatewaySettings:
        return cls(api_key=environment.get("OPENAI_API_KEY", "").strip())

    def validate(self) -> None:
        if not self.api_key:
            raise ModelGatewayConfigurationError("OPENAI_API_KEY must be configured")
        if self.model_id != B1_MODEL_ID:
            raise ModelGatewayConfigurationError("B1/v1 requires model gpt-5.6-terra")
        if self.reasoning_effort != B1_REASONING_EFFORT:
            raise ModelGatewayConfigurationError(
                "B1/v1 requires medium reasoning effort"
            )
        if self.timeout_seconds != MODEL_GATEWAY_TIMEOUT_SECONDS:
            raise ModelGatewayConfigurationError("B1/v1 requires a 10 second timeout")


@dataclass(frozen=True)
class StructuredModelRequest:
    """Typed, versioned input for one strict JSON-schema model call."""

    correlation_id: UUID
    developer_instruction: str
    user_input: str
    schema_name: str
    schema: Mapping[str, object]

    def validate(self) -> None:
        if not self.developer_instruction.strip() or not self.user_input.strip():
            raise ValueError("Model instructions and input must be non-empty")
        if not self.schema_name.strip() or not self.schema:
            raise ValueError("A versioned response schema is required")


@dataclass(frozen=True)
class ModelUsage:
    """Provider token counts retained as typed, non-secret usage metadata."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class StructuredModelResponse:
    """Typed model output plus immutable B1/v1 provenance."""

    correlation_id: UUID
    response_id: str
    model_id: str
    output_json: Mapping[str, object]
    usage: ModelUsage
    configuration_version: str = MODEL_GATEWAY_CONFIGURATION_VERSION


class ModelAdapter(Protocol):
    """Provider seam; domain code invokes this only through ``ModelGateway``."""

    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse: ...


class JsonHttpTransport(Protocol):
    """Minimal transport seam for deterministic provider-adapter tests."""

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_seconds: float,
    ) -> Mapping[str, object]: ...


class UrllibJsonHttpTransport:
    """Server-side HTTPS transport with no browser or API-route exposure."""

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        encoded_body = json.dumps(body).encode("utf-8")
        request = Request(url, data=encoded_body, headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except TimeoutError as error:
            raise ModelGatewayTimeout("Model provider timed out") from error
        except (HTTPError, URLError, OSError) as error:
            raise ModelGatewayUnavailable("Model provider is unavailable") from error
        if not isinstance(payload, dict):
            raise ModelGatewayProtocolError(
                "Model provider returned an invalid response"
            )
        return payload


class OpenAIResponsesAdapter:
    """Direct, pinned OpenAI Responses API adapter for B1/v1."""

    def __init__(
        self,
        settings: ModelGatewaySettings,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        settings.validate()
        self._settings = settings
        self._transport = transport or UrllibJsonHttpTransport()

    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        request.validate()
        payload = self._transport.post(
            url=OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
            },
            body={
                "model": self._settings.model_id,
                "input": [
                    {
                        "role": "developer",
                        "content": [
                            {
                                "type": "input_text",
                                "text": request.developer_instruction,
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": request.user_input}],
                    },
                ],
                "reasoning": {"effort": self._settings.reasoning_effort},
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": request.schema_name,
                        "strict": True,
                        "schema": dict(request.schema),
                    }
                },
            },
            timeout_seconds=self._settings.timeout_seconds,
        )
        return _response_from_provider_payload(
            payload, request.correlation_id, self._settings.model_id
        )


class FakeModelAdapter:
    """Deterministic test adapter that never contacts a provider or uses a secret."""

    def __init__(self, responses: list[StructuredModelResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[StructuredModelRequest] = []

    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        request.validate()
        self.requests.append(request)
        if not self._responses:
            raise ModelGatewayUnavailable("Fake model response was not configured")
        response = self._responses.pop(0)
        if response.correlation_id != request.correlation_id:
            raise ModelGatewayProtocolError("Fake model response correlation mismatch")
        return response


class ModelGateway:
    """Application-facing boundary for one typed, structured model invocation."""

    def __init__(self, adapter: ModelAdapter) -> None:
        self._adapter = adapter

    def generate_structured(
        self, request: StructuredModelRequest
    ) -> StructuredModelResponse:
        return self._adapter.generate(request)


def _response_from_provider_payload(
    payload: Mapping[str, object], correlation_id: UUID, expected_model_id: str
) -> StructuredModelResponse:
    response_id = payload.get("id")
    model_id = payload.get("model")
    output_text = _output_text(payload.get("output"))
    usage = _usage_from_payload(payload.get("usage"))
    if not isinstance(response_id, str) or not isinstance(model_id, str):
        raise ModelGatewayProtocolError("Model provider response is missing provenance")
    if model_id != expected_model_id:
        raise ModelGatewayProtocolError("Model provider returned an unexpected model")
    try:
        output_json = json.loads(output_text)
    except (TypeError, json.JSONDecodeError) as error:
        raise ModelGatewayProtocolError(
            "Model provider did not return valid JSON"
        ) from error
    if not isinstance(output_json, dict):
        raise ModelGatewayProtocolError("Model provider JSON output must be an object")
    return StructuredModelResponse(
        correlation_id=correlation_id,
        response_id=response_id,
        model_id=model_id,
        output_json=output_json,
        usage=usage,
    )


def _output_text(value: object) -> str:
    if not isinstance(value, list):
        raise ModelGatewayProtocolError("Model provider response is missing output")
    for item in value:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    return text
    raise ModelGatewayProtocolError("Model provider response is missing output text")


def _usage_from_payload(value: object) -> ModelUsage:
    if not isinstance(value, dict):
        raise ModelGatewayProtocolError("Model provider response is missing usage")
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    total_tokens = value.get("total_tokens")
    if not all(
        isinstance(count, int) and count >= 0
        for count in (input_tokens, output_tokens, total_tokens)
    ):
        raise ModelGatewayProtocolError("Model provider response has invalid usage")
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
