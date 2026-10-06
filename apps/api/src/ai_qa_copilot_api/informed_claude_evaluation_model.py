"""C1/v1 Claude model for the informed baseline, with fail-closed spend limits.

Select it for informed runs with::

    AI_QA_COPILOT_INFORMED_MODEL_FACTORY=\\
        ai_qa_copilot_api.informed_claude_evaluation_model:create_informed_claude_model

and ``--executor ai_qa_copilot_api.informed_baseline:create_informed_baseline_executor``.
The static developer text goes in the Anthropic ``system`` field and the case in
the single user message, through the pinned C1/v1 ``AnthropicMessagesAdapter``:
``claude-sonnet-5-5``, effort ``medium``, ``max_tokens`` 4096, no tools, no
streaming, no retry or repair, standard global routing (no ``inference_geo``),
and the one JSON Schema shared with every provider. The adapter rejects nonzero
cache tokens. Results are never B1 evidence (ADR-015).

Spend control is the provider-neutral ``evaluation_spend_control`` core.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Final
from uuid import uuid4

from ai_qa_copilot_api.c1_evaluation_model import load_c1_pricing
from ai_qa_copilot_api.evaluation_spend_control import (
    MICROUSD_PER_USD,
    Calibration,
    LedgerIdentity,
    SpendControlledCalls,
    SpendLimits,
    cost_microusd,
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


INFORMED_PRICING_PATH_ENVIRONMENT_VARIABLE: Final = (
    "AI_QA_COPILOT_INFORMED_PRICING_PATH"
)
INFORMED_MAX_CALL_COST_ENVIRONMENT_VARIABLE: Final = (
    "AI_QA_COPILOT_INFORMED_MAX_CALL_COST_USD"
)
INFORMED_MAX_RUN_COST_ENVIRONMENT_VARIABLE: Final = (
    "AI_QA_COPILOT_INFORMED_MAX_RUN_COST_USD"
)
INFORMED_LEDGER_PATH_ENVIRONMENT_VARIABLE: Final = (
    "AI_QA_COPILOT_INFORMED_CALL_LEDGER_PATH"
)

INFORMED_CALL_LEDGER_SCHEMA_VERSION: Final = "informed-call-ledger/v1"

# Measured on B0 prompts in the first C1 smoke run (65 to 77 percent of this
# estimate). To be re-measured on informed prompts by the informed smoke run.
CLAUDE_INFORMED_CALIBRATION: Final = Calibration(
    characters_per_token=Decimal("2.1"), tolerance=Decimal("0.15")
)


class InformedClaudeModel:
    """``InformedBaselineModel`` backed by the pinned C1/v1 Anthropic adapter."""

    def __init__(
        self,
        *,
        settings: AnthropicGatewaySettings,
        pricing: ProviderPricing,
        limits: SpendLimits,
        ledger_path: Path,
        configuration: InformedBaselineConfig,
        repository_root: Path,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        if (
            pricing.provider != MODEL_PROVIDER_ANTHROPIC
            or pricing.model_id != C1_MODEL_ID
        ):
            raise ValueError("Pricing does not match the C1/v1 model")
        self._pricing = pricing
        self._configuration = configuration
        self._catalog = load_informed_catalog(configuration, repository_root)
        self._schema = informed_output_schema(configuration, self._catalog)
        self._schema_characters = len(json.dumps(self._schema, separators=(",", ":")))
        self._gateway = ModelGateway(
            AnthropicMessagesAdapter(settings, transport),
            metrics=InMemoryWorkflowMetrics(),
            pricing=pricing,
        )
        self._calls = SpendControlledCalls(
            identity=LedgerIdentity(
                schema_version=INFORMED_CALL_LEDGER_SCHEMA_VERSION,
                provider=MODEL_PROVIDER_ANTHROPIC,
                model_id=C1_MODEL_ID,
                configuration_version=C1_CONFIGURATION_VERSION,
                prompt_version=configuration.prompt_version,
                pricing_version=pricing.pricing_version,
            ),
            pricing=pricing,
            limits=limits,
            calibration=CLAUDE_INFORMED_CALIBRATION,
            output_token_cap=C1_MAX_TOKENS,
            ledger_path=ledger_path,
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
        # The estimate covers the system field, the user message, and the schema.
        response = self._calls.run(
            estimated_characters=(
                len(developer_instruction) + len(user_input) + self._schema_characters
            ),
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
                self._pricing,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            / MICROUSD_PER_USD
        )


def create_informed_claude_model() -> InformedClaudeModel:
    """Create the model from explicit environment configuration only."""

    return informed_claude_model_from_mapping(os.environ)


def informed_claude_model_from_mapping(
    environment: Mapping[str, str],
    *,
    transport: JsonHttpTransport | None = None,
) -> InformedClaudeModel:
    configuration, repository_root = informed_configuration_from_environment(
        environment
    )
    return InformedClaudeModel(
        settings=AnthropicGatewaySettings.from_mapping(environment),
        pricing=load_c1_pricing(
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
