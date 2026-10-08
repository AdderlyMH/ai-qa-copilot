"""O1/v1 OpenAI gpt-6.1-sol model for the informed baseline, with fail-closed spend limits.

Select it for informed runs with::

    AI_QA_COPILOT_INFORMED_MODEL_FACTORY=\\
        ai_qa_copilot_api.informed_openai_evaluation_model:create_informed_openai_model

and ``--executor ai_qa_copilot_api.informed_baseline:create_informed_baseline_executor``,
mirroring ``informed_claude_evaluation_model.py``. The same developer text, user
text and JSON Schema go through the pinned ``OpenAIInformedResponsesAdapter``
(see that module for the request settings). Results are never B1 evidence.

Spend control is the provider-neutral ``evaluation_spend_control`` core, with
these rules (ADR-016):

- **Worst case, checked before each call:** estimated input tokens (developer
  text, user text and schema at 2.1 characters per token) priced at the
  cache-write rate, 2.50 USD per million, plus the 4,096-token output cap at 10
  USD per million. A failed call is charged at this worst case.
- **Actual charge for a successful call:** ``input_tokens`` at the input rate (2
  USD per million) plus ``output_tokens`` (which include reasoning tokens) at the
  output rate (10 USD per million). Because any nonzero cached or cache-write
  token count fails closed in the adapter, no other rate ever applies.
- **Short context only:** a request whose estimated input, raised by the
  calibration tolerance, could exceed 272,000 tokens is refused before any
  request, because longer prompts are billed at long-context rates.
- **Calibration:** 2.1 characters per token with a 15 percent tolerance.
  UNVERIFIED for OpenAI's tokenizer until the live probe measures it.
- Ledger rows use ``informed-call-ledger/v1`` with provider ``openai`` and an
  extra ``reasoning_tokens`` field (content-free; null when not reported).

The strict pricing loader is deliberately separate from ``load_c1_pricing``,
which stays specific to the C1/v1 Anthropic input.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast
from uuid import uuid4

import yaml

from ai_qa_copilot_api.evaluation_runner import EvaluationRunRejected
from ai_qa_copilot_api.evaluation_spend_control import (
    MICROUSD_PER_USD,
    Calibration,
    LedgerIdentity,
    SpendControlledCalls,
    SpendLimits,
    cost_microusd,
    estimate_input_tokens,
    required_setting,
    usd_setting_to_microusd,
)
from ai_qa_copilot_api.informed_baseline import (
    INFORMED_SCHEMA_NAME,
    InformedBaselineConfig,
    InformedModelResponse,
    informed_configuration_from_environment,
    informed_output_schema,
    load_informed_catalog,
    validate_informed_output,
)
from ai_qa_copilot_api.informed_claude_evaluation_model import (
    INFORMED_CALL_LEDGER_SCHEMA_VERSION,
    INFORMED_LEDGER_PATH_ENVIRONMENT_VARIABLE,
    INFORMED_MAX_CALL_COST_ENVIRONMENT_VARIABLE,
    INFORMED_MAX_RUN_COST_ENVIRONMENT_VARIABLE,
    INFORMED_PRICING_PATH_ENVIRONMENT_VARIABLE,
)
from ai_qa_copilot_api.metrics import InMemoryWorkflowMetrics, ProviderPricing
from ai_qa_copilot_api.model_gateway import (
    MODEL_PROVIDER_OPENAI,
    JsonHttpTransport,
    ModelGateway,
    StructuredModelRequest,
    StructuredModelResponse,
)
from ai_qa_copilot_api.openai_informed_evaluation_adapter import (
    OPENAI_INFORMED_CONFIGURATION_VERSION,
    OPENAI_INFORMED_MAX_OUTPUT_TOKENS,
    OPENAI_INFORMED_MODEL_ID,
    OpenAIInformedResponse,
    OpenAIInformedResponsesAdapter,
    OpenAIInformedSettings,
)


# UNVERIFIED for OpenAI: the 2.1 characters-per-token estimate was measured on
# Claude. The live probe (PR 5) measures OpenAI's ratio before any larger run.
OPENAI_INFORMED_CALIBRATION: Final = Calibration(
    characters_per_token=Decimal("2.1"), tolerance=Decimal("0.15")
)
OPENAI_REASONING_LEDGER_FIELD: Final = "reasoning_tokens"

OPENAI_PRICING_SCHEMA_VERSION: Final = "openai-provider-pricing/v1"
OPENAI_PROCESSING_TIER: Final = "standard"
OPENAI_PRICING_VERSION_ASSUMPTION: Final = "standard-short-context-cache-disabled"
OPENAI_SHORT_CONTEXT_MAX_INPUT_TOKENS: Final = 272_000

_PRICING_FIELDS: Final = frozenset(
    {
        "schema_version",
        "provider",
        "model_id",
        "pricing_version",
        "source_reference",
        "verified_on",
        "processing_tier",
        "short_context_max_input_tokens",
        "input_microusd_per_million_tokens",
        "cached_input_microusd_per_million_tokens",
        "cache_write_microusd_per_million_tokens",
        "output_microusd_per_million_tokens",
        "long_context_input_and_cache_multiplier",
        "long_context_output_multiplier",
    }
)


class OpenAIInformedEvaluationRejected(EvaluationRunRejected):
    """Raised when the OpenAI informed configuration or a request is refused."""


@dataclass(frozen=True)
class OpenAIInformedPricing:
    """The verified gpt-6.1-sol rates used by the OpenAI informed factory.

    ``pricing`` carries the rates actually charged for a successful call (input
    and output). ``worst_case_input_microusd_per_million_tokens`` is the
    cache-write rate, used only for the pre-call worst case and for a failed call.
    """

    pricing: ProviderPricing
    worst_case_input_microusd_per_million_tokens: int
    cached_input_microusd_per_million_tokens: int
    short_context_max_input_tokens: int
    long_context_input_and_cache_multiplier: Decimal
    long_context_output_multiplier: Decimal


def load_openai_informed_pricing(path: Path) -> OpenAIInformedPricing:
    """Load the explicit, versioned gpt-6.1-sol pricing input; nothing is assumed."""

    try:
        raw = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError) as error:
        raise OpenAIInformedEvaluationRejected(
            "OpenAI pricing input could not be read"
        ) from error
    if not isinstance(raw, dict):
        raise OpenAIInformedEvaluationRejected("OpenAI pricing input must be a mapping")
    pricing = cast(dict[str, object], raw)
    if set(pricing) != _PRICING_FIELDS:
        raise OpenAIInformedEvaluationRejected(
            f"OpenAI pricing fields must be exactly {sorted(_PRICING_FIELDS)}"
        )
    if pricing["schema_version"] != OPENAI_PRICING_SCHEMA_VERSION:
        raise OpenAIInformedEvaluationRejected("Unsupported OpenAI pricing schema")
    if pricing["provider"] != MODEL_PROVIDER_OPENAI:
        raise OpenAIInformedEvaluationRejected("OpenAI pricing must be for openai")
    if pricing["model_id"] != OPENAI_INFORMED_MODEL_ID:
        raise OpenAIInformedEvaluationRejected(
            f"OpenAI pricing must be for model {OPENAI_INFORMED_MODEL_ID}"
        )
    if pricing["processing_tier"] != OPENAI_PROCESSING_TIER:
        # Flex, Batch, priority/fast and regional processing are priced differently.
        raise OpenAIInformedEvaluationRejected(
            "OpenAI pricing must be for standard processing"
        )
    pricing_version = pricing["pricing_version"]
    if (
        not isinstance(pricing_version, str)
        or OPENAI_PRICING_VERSION_ASSUMPTION not in pricing_version
        or str(pricing["verified_on"]) not in pricing_version
    ):
        raise OpenAIInformedEvaluationRejected(
            "OpenAI pricing_version must state its date and "
            f"{OPENAI_PRICING_VERSION_ASSUMPTION}"
        )
    source_reference = pricing["source_reference"]
    if not isinstance(source_reference, str) or not source_reference.startswith(
        "https://developers.openai.com/"
    ):
        raise OpenAIInformedEvaluationRejected(
            "OpenAI pricing source_reference must be an official developers.openai.com URL"
        )
    if not isinstance(pricing["verified_on"], str) or not pricing["verified_on"]:
        raise OpenAIInformedEvaluationRejected(
            "OpenAI pricing verified_on must be a date string"
        )
    if (
        pricing["short_context_max_input_tokens"]
        != OPENAI_SHORT_CONTEXT_MAX_INPUT_TOKENS
    ):
        raise OpenAIInformedEvaluationRejected(
            "OpenAI pricing must declare the 272,000-token short-context threshold"
        )

    rates = {
        name: _non_negative_int(pricing[name], name)
        for name in (
            "input_microusd_per_million_tokens",
            "cached_input_microusd_per_million_tokens",
            "cache_write_microusd_per_million_tokens",
            "output_microusd_per_million_tokens",
        )
    }
    if (
        rates["cache_write_microusd_per_million_tokens"]
        < rates["input_microusd_per_million_tokens"]
    ):
        raise OpenAIInformedEvaluationRejected(
            "The cache-write rate must not be below the input rate"
        )

    return OpenAIInformedPricing(
        pricing=ProviderPricing(
            provider=MODEL_PROVIDER_OPENAI,
            model_id=OPENAI_INFORMED_MODEL_ID,
            pricing_version=pricing_version,
            source_reference=source_reference,
            input_microusd_per_million_tokens=rates[
                "input_microusd_per_million_tokens"
            ],
            output_microusd_per_million_tokens=rates[
                "output_microusd_per_million_tokens"
            ],
        ),
        worst_case_input_microusd_per_million_tokens=rates[
            "cache_write_microusd_per_million_tokens"
        ],
        cached_input_microusd_per_million_tokens=rates[
            "cached_input_microusd_per_million_tokens"
        ],
        short_context_max_input_tokens=OPENAI_SHORT_CONTEXT_MAX_INPUT_TOKENS,
        long_context_input_and_cache_multiplier=_multiplier(
            pricing["long_context_input_and_cache_multiplier"],
            "long_context_input_and_cache_multiplier",
        ),
        long_context_output_multiplier=_multiplier(
            pricing["long_context_output_multiplier"], "long_context_output_multiplier"
        ),
    )


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpenAIInformedEvaluationRejected(
            f"{label} must be a non-negative integer"
        )
    return value


def _multiplier(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise OpenAIInformedEvaluationRejected(f"{label} must be a decimal string")
    try:
        multiplier = Decimal(value)
    except InvalidOperation as error:
        raise OpenAIInformedEvaluationRejected(f"{label} must be a decimal") from error
    if not multiplier.is_finite() or multiplier < 1:
        raise OpenAIInformedEvaluationRejected(f"{label} must be at least 1")
    return multiplier


class InformedOpenAIModel:
    """``InformedBaselineModel`` backed by the pinned O1/v1 OpenAI adapter."""

    def __init__(
        self,
        *,
        settings: OpenAIInformedSettings,
        pricing: OpenAIInformedPricing,
        limits: SpendLimits,
        ledger_path: Path,
        configuration: InformedBaselineConfig,
        repository_root: Path,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        if (
            pricing.pricing.provider != MODEL_PROVIDER_OPENAI
            or pricing.pricing.model_id != OPENAI_INFORMED_MODEL_ID
        ):
            raise ValueError("Pricing does not match the O1/v1 model")
        self._pricing = pricing
        self._configuration = configuration
        self._catalog = load_informed_catalog(configuration, repository_root)
        self._schema = informed_output_schema(configuration, self._catalog)
        self._schema_characters = len(json.dumps(self._schema, separators=(",", ":")))
        self._gateway = ModelGateway(
            OpenAIInformedResponsesAdapter(settings, transport),
            metrics=InMemoryWorkflowMetrics(),
            pricing=pricing.pricing,
        )
        self._calls = SpendControlledCalls(
            identity=LedgerIdentity(
                schema_version=INFORMED_CALL_LEDGER_SCHEMA_VERSION,
                provider=MODEL_PROVIDER_OPENAI,
                model_id=OPENAI_INFORMED_MODEL_ID,
                configuration_version=OPENAI_INFORMED_CONFIGURATION_VERSION,
                prompt_version=configuration.prompt_version,
                pricing_version=pricing.pricing.pricing_version,
            ),
            pricing=pricing.pricing,
            limits=limits,
            calibration=OPENAI_INFORMED_CALIBRATION,
            output_token_cap=OPENAI_INFORMED_MAX_OUTPUT_TOKENS,
            ledger_path=ledger_path,
            worst_case_input_microusd_per_million_tokens=(
                pricing.worst_case_input_microusd_per_million_tokens
            ),
            extra_ledger_fields=(OPENAI_REASONING_LEDGER_FIELD,),
            usage_details=_reasoning_details,
        )

    @property
    def running_total_microusd(self) -> int:
        return self._calls.running_total_microusd

    def complete(
        self, *, developer_instruction: str, user_input: str
    ) -> InformedModelResponse:
        request = StructuredModelRequest(
            correlation_id=uuid4(),
            developer_instruction=developer_instruction,
            user_input=user_input,
            schema_name=INFORMED_SCHEMA_NAME,
            schema=self._schema,
        )
        # The estimate covers the developer message, the user message and the schema.
        estimated_characters = (
            len(developer_instruction) + len(user_input) + self._schema_characters
        )
        estimated_tokens = estimate_input_tokens(
            estimated_characters, OPENAI_INFORMED_CALIBRATION
        )
        if (
            Decimal(estimated_tokens) * (1 + OPENAI_INFORMED_CALIBRATION.tolerance)
            > self._pricing.short_context_max_input_tokens
        ):
            raise OpenAIInformedEvaluationRejected(
                "The estimated input could exceed the 272,000-token short-context "
                "threshold; the request was refused before any call"
            )
        response = self._calls.run(
            estimated_characters=estimated_characters,
            invoke=lambda: self._gateway.generate_structured(request),
            validate=self._validate,
        )
        # Cost is reported in USD; the ledger holds the exact micro-USD.
        return InformedModelResponse(
            content=json.dumps(dict(response.output_json), sort_keys=True),
            cost=self._last_charge_usd(response),
        )

    def _validate(self, response: StructuredModelResponse) -> None:
        validate_informed_output(
            json.dumps(dict(response.output_json)), self._configuration, self._catalog
        )

    def _last_charge_usd(self, response: StructuredModelResponse) -> float:
        return (
            cost_microusd(
                self._pricing.pricing,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            / MICROUSD_PER_USD
        )


def _reasoning_details(response: StructuredModelResponse) -> Mapping[str, int | None]:
    if not isinstance(response, OpenAIInformedResponse):
        raise TypeError("Expected an O1/v1 OpenAI response")
    return {OPENAI_REASONING_LEDGER_FIELD: response.reasoning_tokens}


def create_informed_openai_model() -> InformedOpenAIModel:
    """Create the model from explicit environment configuration only."""

    return informed_openai_model_from_mapping(os.environ)


def informed_openai_model_from_mapping(
    environment: Mapping[str, str],
    *,
    transport: JsonHttpTransport | None = None,
) -> InformedOpenAIModel:
    configuration, repository_root = informed_configuration_from_environment(
        environment
    )
    return InformedOpenAIModel(
        settings=OpenAIInformedSettings.from_mapping(environment),
        pricing=load_openai_informed_pricing(
            Path(
                required_setting(
                    environment, INFORMED_PRICING_PATH_ENVIRONMENT_VARIABLE
                )
            )
        ),
        limits=SpendLimits(
            max_call_microusd=usd_setting_to_microusd(
                environment, INFORMED_MAX_CALL_COST_ENVIRONMENT_VARIABLE
            ),
            max_run_microusd=usd_setting_to_microusd(
                environment, INFORMED_MAX_RUN_COST_ENVIRONMENT_VARIABLE
            ),
        ),
        ledger_path=Path(
            required_setting(environment, INFORMED_LEDGER_PATH_ENVIRONMENT_VARIABLE)
        ),
        configuration=configuration,
        repository_root=repository_root,
        transport=transport,
    )
