"""C1/v1 model for the B0 evaluation baseline, with fail-closed spend limits.

Select it for B0 runs with
``AI_QA_COPILOT_B0_MODEL_FACTORY=ai_qa_copilot_api.c1_evaluation_model:create_c1_b0_model``.
The B0 prompt is sent unchanged through the pinned C1/v1 Anthropic adapter, so a
C1 result differs from an OpenAI B0 result only by provider configuration. C1
results are never B1 evidence.

Spend controls, all fail closed:

- Explicit, versioned pricing input (ADR-012); nothing is priced by default.
- Before each call: the worst case (estimated input tokens, including the
  system field and output schema, plus the C1/v1 ``max_tokens``) must fit the
  per-call limit and the remaining run budget.
- After each call: actual cost is added to the running total, which must not
  exceed the run limit, and actual input tokens must not exceed the estimate by
  more than ``C1_INPUT_TOKEN_ESTIMATE_TOLERANCE``.
- One call at a time: an overlapping call is rejected before any network access,
  because the runner's ``max_concurrency`` is not visible to a model factory.
- Any failure latches the model closed. The shared runner still executes cases
  that were already queued, so every later call is rejected without a request.
- A failed provider call reports no usage, so it is charged at its worst case.

Every call attempt is appended to a content-free JSON Lines ledger.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from threading import Lock
from typing import Final, NoReturn, cast
from uuid import uuid4

import yaml

from ai_qa_copilot_api.evaluation_runner import EvaluationRunRejected
from ai_qa_copilot_api.metrics import InMemoryWorkflowMetrics, ProviderPricing
from ai_qa_copilot_api.model_gateway import (
    C1_CONFIGURATION_VERSION,
    C1_MAX_TOKENS,
    C1_MODEL_ID,
    MODEL_PROVIDER_ANTHROPIC,
    AnthropicGatewaySettings,
    AnthropicMessagesAdapter,
    JsonHttpTransport,
    ModelGateway,
    StructuredModelRequest,
    StructuredModelResponse,
)
from ai_qa_copilot_api.naive_baseline import NaiveBaselineModelResponse


C1_PRICING_PATH_ENVIRONMENT_VARIABLE: Final = "AI_QA_COPILOT_C1_PRICING_PATH"
C1_MAX_CALL_COST_ENVIRONMENT_VARIABLE: Final = "AI_QA_COPILOT_C1_MAX_CALL_COST_USD"
C1_MAX_RUN_COST_ENVIRONMENT_VARIABLE: Final = "AI_QA_COPILOT_C1_MAX_RUN_COST_USD"
C1_LEDGER_PATH_ENVIRONMENT_VARIABLE: Final = "AI_QA_COPILOT_C1_CALL_LEDGER_PATH"

PROVIDER_PRICING_SCHEMA_VERSION: Final = "provider-pricing/v1"
C1_PRICING_ROUTING: Final = "standard_global_no_inference_geo"
C1_CALL_LEDGER_SCHEMA_VERSION: Final = "c1-call-ledger/v1"

# Estimation and calibration constants.
CHARACTERS_PER_TOKEN: Final = Decimal("2.1")
C1_INPUT_TOKEN_ESTIMATE_TOLERANCE: Final = Decimal("0.15")

C1_B0_SYSTEM_INSTRUCTION: Final = (
    "Follow the user message exactly and return only the requested JSON object."
)
C1_B0_SCHEMA_NAME: Final = "b0_observation_v1"
C1_B0_OUTPUT_SCHEMA: Final[Mapping[str, object]] = {
    "type": "object",
    "properties": {
        "boundary": {"type": "string"},
        "ground_truth_ids": {"type": "array", "items": {"type": "string"}},
        "source_references": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["boundary", "ground_truth_ids", "source_references"],
    "additionalProperties": False,
}

_MICROUSD_PER_USD: Final = 1_000_000
_TOKENS_PER_MILLION: Final = 1_000_000


class C1EvaluationRejected(EvaluationRunRejected):
    """Raised when a C1 evaluation call is refused or the model has latched closed."""


@dataclass(frozen=True)
class C1SpendLimits:
    """Per-call and per-run spend limits in micro-USD."""

    max_call_microusd: int
    max_run_microusd: int

    def __post_init__(self) -> None:
        for label, value in (
            ("max_call_microusd", self.max_call_microusd),
            ("max_run_microusd", self.max_run_microusd),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise C1EvaluationRejected(f"{label} must be a positive integer")
        if self.max_call_microusd > self.max_run_microusd:
            raise C1EvaluationRejected("The per-call limit cannot exceed the run limit")


def load_c1_pricing(path: Path) -> ProviderPricing:
    """Load the explicit, versioned C1 pricing input; nothing is assumed."""

    try:
        raw = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError) as error:
        raise C1EvaluationRejected("C1 pricing input could not be read") from error
    if not isinstance(raw, dict):
        raise C1EvaluationRejected("C1 pricing input must be a mapping")
    pricing = cast(dict[str, object], raw)
    expected_fields = {
        "schema_version",
        "provider",
        "model_id",
        "pricing_version",
        "source_reference",
        "verified_on",
        "routing",
        "input_microusd_per_million_tokens",
        "output_microusd_per_million_tokens",
    }
    if set(pricing) != expected_fields:
        raise C1EvaluationRejected(
            f"C1 pricing fields must be exactly {sorted(expected_fields)}"
        )
    if pricing["schema_version"] != PROVIDER_PRICING_SCHEMA_VERSION:
        raise C1EvaluationRejected("Unsupported C1 pricing schema version")
    if pricing["provider"] != MODEL_PROVIDER_ANTHROPIC:
        raise C1EvaluationRejected("C1 pricing must be for provider anthropic")
    if pricing["model_id"] != C1_MODEL_ID:
        raise C1EvaluationRejected(f"C1 pricing must be for model {C1_MODEL_ID}")
    if pricing["routing"] != C1_PRICING_ROUTING:
        # The adapter never sets inference_geo; other routing is priced differently.
        raise C1EvaluationRejected(
            f"C1 pricing must declare routing {C1_PRICING_ROUTING}"
        )
    pricing_version = pricing["pricing_version"]
    if not isinstance(pricing_version, str) or C1_PRICING_ROUTING.replace(
        "_", "-"
    ) not in pricing_version.replace("_", "-"):
        raise C1EvaluationRejected(
            "C1 pricing_version must state the no-inference-geo routing assumption"
        )
    source_reference = pricing["source_reference"]
    if not isinstance(source_reference, str) or not source_reference.startswith(
        "https://"
    ):
        raise C1EvaluationRejected("C1 pricing source_reference must be an HTTPS URL")
    if not isinstance(pricing["verified_on"], str) or not pricing["verified_on"]:
        raise C1EvaluationRejected("C1 pricing verified_on must be a date string")

    try:
        return ProviderPricing(
            provider=MODEL_PROVIDER_ANTHROPIC,
            model_id=C1_MODEL_ID,
            pricing_version=pricing_version,
            source_reference=source_reference,
            input_microusd_per_million_tokens=cast(
                int, pricing["input_microusd_per_million_tokens"]
            ),
            output_microusd_per_million_tokens=cast(
                int, pricing["output_microusd_per_million_tokens"]
            ),
        )
    except ValueError as error:
        raise C1EvaluationRejected("C1 pricing values are invalid") from error


def estimate_input_tokens(prompt: str) -> int:
    """Estimate input tokens for the prompt plus the request wrapper."""

    characters = (
        len(prompt)
        + len(C1_B0_SYSTEM_INSTRUCTION)
        + len(json.dumps(C1_B0_OUTPUT_SCHEMA, separators=(",", ":")))
    )
    return int(
        (Decimal(characters) / CHARACTERS_PER_TOKEN).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


def cost_microusd(
    pricing: ProviderPricing, *, input_tokens: int, output_tokens: int
) -> int:
    """Cost of one call, rounded up to the next micro-USD."""

    numerator = (
        input_tokens * pricing.input_microusd_per_million_tokens
        + output_tokens * pricing.output_microusd_per_million_tokens
    )
    return -(-numerator // _TOKENS_PER_MILLION)


def exceeds_estimate_tolerance(*, estimated: int, actual: int) -> bool:
    """Whether actual input tokens exceed the estimate by more than the tolerance."""

    return Decimal(actual) > Decimal(estimated) * (
        1 + C1_INPUT_TOKEN_ESTIMATE_TOLERANCE
    )


class C1B0Model:
    """``NaiveBaselineModel`` backed by the pinned C1/v1 Anthropic adapter."""

    def __init__(
        self,
        *,
        settings: AnthropicGatewaySettings,
        pricing: ProviderPricing,
        limits: C1SpendLimits,
        ledger_path: Path,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        if (
            pricing.provider != MODEL_PROVIDER_ANTHROPIC
            or pricing.model_id != C1_MODEL_ID
        ):
            raise C1EvaluationRejected("C1 pricing does not match the C1/v1 model")
        self._gateway = ModelGateway(
            AnthropicMessagesAdapter(settings, transport),
            metrics=InMemoryWorkflowMetrics(),
            pricing=pricing,
        )
        self._pricing = pricing
        self._limits = limits
        self._ledger_path = ledger_path
        self._call_lock = Lock()
        self._closed_reason: str | None = None
        self._call_count = 0
        self._running_total_microusd = 0

        try:
            # Exclusive creation: an existing ledger is evidence and is never reused.
            with ledger_path.open("x", encoding="utf-8"):
                pass
        except FileExistsError as error:
            raise C1EvaluationRejected(
                "C1 call ledger already exists; choose a new ledger path"
            ) from error
        except OSError as error:
            raise C1EvaluationRejected("C1 call ledger could not be created") from error

    @property
    def running_total_microusd(self) -> int:
        return self._running_total_microusd

    def complete(self, *, prompt: str) -> NaiveBaselineModelResponse:
        if not self._call_lock.acquire(blocking=False):
            self._closed_reason = "concurrent_call"
            raise C1EvaluationRejected(
                "C1 evaluation requires max_concurrency 1; an overlapping call was "
                "rejected and the model is closed"
            )
        try:
            return self._complete_one(prompt)
        finally:
            self._call_lock.release()

    def _complete_one(self, prompt: str) -> NaiveBaselineModelResponse:
        if self._closed_reason is not None:
            raise C1EvaluationRejected(
                f"C1 model is closed after an earlier failure ({self._closed_reason})"
            )

        self._call_count += 1
        estimated_input_tokens = estimate_input_tokens(prompt)
        worst_case_microusd = cost_microusd(
            self._pricing,
            input_tokens=estimated_input_tokens,
            output_tokens=C1_MAX_TOKENS,
        )
        entry: dict[str, object] = {
            "call_index": self._call_count,
            "estimated_input_tokens": estimated_input_tokens,
            "worst_case_microusd": worst_case_microusd,
        }

        if worst_case_microusd > self._limits.max_call_microusd:
            self._fail(entry, "worst_case_exceeds_call_limit", charged=0)
        if (
            self._running_total_microusd + worst_case_microusd
            > self._limits.max_run_microusd
        ):
            self._fail(entry, "worst_case_exceeds_remaining_run_budget", charged=0)

        try:
            response = self._gateway.generate_structured(
                StructuredModelRequest(
                    correlation_id=uuid4(),
                    developer_instruction=C1_B0_SYSTEM_INSTRUCTION,
                    user_input=prompt,
                    schema_name=C1_B0_SCHEMA_NAME,
                    schema=C1_B0_OUTPUT_SCHEMA,
                )
            )
        except Exception as error:
            # Failed calls report no usage but may be billed: charge the worst case.
            self._fail(
                entry,
                f"provider_call_failed:{type(error).__name__}",
                charged=worst_case_microusd,
                cause=error,
            )

        charged = cost_microusd(
            self._pricing,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        entry.update(
            actual_input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            response_id=response.response_id,
        )

        if self._running_total_microusd + charged > self._limits.max_run_microusd:
            self._fail(entry, "run_limit_exceeded_after_call", charged=charged)
        if exceeds_estimate_tolerance(
            estimated=estimated_input_tokens,
            actual=response.usage.input_tokens,
        ):
            self._fail(entry, "input_token_estimate_exceeded", charged=charged)
        content = self._validated_content(response, entry, charged)

        self._running_total_microusd += charged
        self._write_ledger(entry, outcome="succeeded", charged=charged, failure=None)
        return NaiveBaselineModelResponse(
            content=content,
            cost=charged / _MICROUSD_PER_USD,
        )

    def _validated_content(
        self,
        response: StructuredModelResponse,
        entry: dict[str, object],
        charged: int,
    ) -> str:
        output = response.output_json
        lists = (output.get("ground_truth_ids"), output.get("source_references"))
        if (
            set(output) != {"boundary", "ground_truth_ids", "source_references"}
            or not isinstance(output.get("boundary"), str)
            or not str(output.get("boundary")).strip()
            or not all(
                isinstance(items, list)
                and all(isinstance(item, str) and item.strip() for item in items)
                and len(set(items)) == len(items)
                for items in lists
            )
        ):
            # Fail here, not in the B0 executor, so later queued calls cannot spend.
            self._fail(entry, "invalid_b0_output", charged=charged)
        return json.dumps(dict(output), sort_keys=True)

    def _fail(
        self,
        entry: dict[str, object],
        reason: str,
        *,
        charged: int,
        cause: BaseException | None = None,
    ) -> NoReturn:
        self._closed_reason = reason
        self._running_total_microusd += charged
        self._write_ledger(entry, outcome="failed", charged=charged, failure=reason)
        raise C1EvaluationRejected(
            f"C1 evaluation call {entry['call_index']} failed closed: {reason}"
        ) from cause

    def _write_ledger(
        self,
        entry: Mapping[str, object],
        *,
        outcome: str,
        charged: int,
        failure: str | None,
    ) -> None:
        record = {
            "schema_version": C1_CALL_LEDGER_SCHEMA_VERSION,
            "provider": MODEL_PROVIDER_ANTHROPIC,
            "model_id": C1_MODEL_ID,
            "configuration_version": C1_CONFIGURATION_VERSION,
            "pricing_version": self._pricing.pricing_version,
            "call_index": entry["call_index"],
            "outcome": outcome,
            "failure": failure,
            "estimated_input_tokens": entry["estimated_input_tokens"],
            "actual_input_tokens": entry.get("actual_input_tokens"),
            "output_tokens": entry.get("output_tokens"),
            "response_id": entry.get("response_id"),
            "worst_case_microusd": entry["worst_case_microusd"],
            "charged_microusd": charged,
            "running_total_microusd": self._running_total_microusd,
            "max_call_microusd": self._limits.max_call_microusd,
            "max_run_microusd": self._limits.max_run_microusd,
        }
        with self._ledger_path.open("a", encoding="utf-8", newline="\n") as ledger:
            ledger.write(json.dumps(record, sort_keys=True) + "\n")


def create_c1_b0_model() -> C1B0Model:
    """Create the C1 model from explicit environment configuration only."""

    return c1_b0_model_from_mapping(os.environ)


def c1_b0_model_from_mapping(
    environment: Mapping[str, str],
    *,
    transport: JsonHttpTransport | None = None,
) -> C1B0Model:
    pricing_path = _required(environment, C1_PRICING_PATH_ENVIRONMENT_VARIABLE)
    ledger_path = _required(environment, C1_LEDGER_PATH_ENVIRONMENT_VARIABLE)
    limits = C1SpendLimits(
        max_call_microusd=_usd_to_microusd(
            environment, C1_MAX_CALL_COST_ENVIRONMENT_VARIABLE
        ),
        max_run_microusd=_usd_to_microusd(
            environment, C1_MAX_RUN_COST_ENVIRONMENT_VARIABLE
        ),
    )
    return C1B0Model(
        settings=AnthropicGatewaySettings.from_mapping(environment),
        pricing=load_c1_pricing(Path(pricing_path)),
        limits=limits,
        ledger_path=Path(ledger_path),
        transport=transport,
    )


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise C1EvaluationRejected(f"{name} must be set for C1 evaluation")
    return value


def _usd_to_microusd(environment: Mapping[str, str], name: str) -> int:
    text = _required(environment, name)
    try:
        amount = Decimal(text)
    except InvalidOperation as error:
        raise C1EvaluationRejected(f"{name} must be a USD amount") from error
    if not amount.is_finite() or amount <= 0:
        raise C1EvaluationRejected(f"{name} must be a positive USD amount")
    microusd = amount * _MICROUSD_PER_USD
    if microusd != microusd.to_integral_value():
        raise C1EvaluationRejected(f"{name} must not be finer than one micro-USD")
    return int(microusd)
