"""OpenAI gpt-6.1-sol model for the informed baseline, with fail-closed spend limits.

This module holds the strict OpenAI pricing loader. It is deliberately separate
from ``load_c1_pricing``, which stays specific to the C1/v1 Anthropic input.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

import yaml

from ai_qa_copilot_api.evaluation_runner import EvaluationRunRejected
from ai_qa_copilot_api.metrics import ProviderPricing
from ai_qa_copilot_api.model_gateway import MODEL_PROVIDER_OPENAI


OPENAI_INFORMED_MODEL_ID: Final = "gpt-6.1-sol"
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
