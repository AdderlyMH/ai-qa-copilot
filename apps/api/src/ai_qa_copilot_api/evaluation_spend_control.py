"""Provider-neutral, fail-closed spend control for paid evaluation model calls.

Standalone by design: ``c1_evaluation_model.py`` keeps its own copy of this
machinery for the B0 run and is unchanged. This module is used by the informed
baseline's model factories (ADR-015) and is intended to be reused unchanged by a
later OpenAI factory, so nothing here names a provider.

Controls, all fail closed:

- Before each call: the worst case (estimated input tokens plus the output-token
  cap) must fit the per-call limit and the remaining run budget.
- After each call: actual cost is added to the running total, which must not
  exceed the run limit; actual input tokens must not exceed the estimate by more
  than the provider's calibration tolerance; the output must pass validation.
- One call at a time: an overlapping call is rejected before any request.
- Any failure latches the caller closed; later calls are rejected without a
  request.
- A failed provider call reports no usage, so it is charged at its worst case.

Every call attempt appends one content-free JSON Lines record to the ledger: no
prompt, model output, or credential.

Two optional settings exist for providers that need them (ADR-016); both default
to off, which keeps the original behaviour and ledger records byte-identical:

- ``worst_case_input_microusd_per_million_tokens``: a higher input rate used
  only for the pre-call worst case and for the charge of a failed call (for
  example a cache-write rate that a request might incur). A successful call is
  still charged at ``pricing``.
- ``extra_ledger_fields`` with ``usage_details``: named, non-negative integer
  usage counts (for example reasoning tokens) added to every ledger record,
  ``null`` when no response was received.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from threading import Lock
from typing import Final, NoReturn

from ai_qa_copilot_api.evaluation_runner import EvaluationRunRejected
from ai_qa_copilot_api.metrics import ProviderPricing
from ai_qa_copilot_api.model_gateway import StructuredModelResponse


MICROUSD_PER_USD: Final = 1_000_000
_TOKENS_PER_MILLION: Final = 1_000_000
_BASE_LEDGER_FIELDS: Final = frozenset(
    {
        "schema_version",
        "provider",
        "model_id",
        "configuration_version",
        "prompt_version",
        "pricing_version",
        "call_index",
        "outcome",
        "failure",
        "estimated_input_tokens",
        "actual_input_tokens",
        "output_tokens",
        "calibration_ratio",
        "response_id",
        "worst_case_microusd",
        "charged_microusd",
        "running_total_microusd",
        "max_call_microusd",
        "max_run_microusd",
        "characters_per_token",
        "tolerance",
    }
)


class SpendControlRejected(EvaluationRunRejected):
    """Raised when a call is refused or the caller has latched closed."""


@dataclass(frozen=True)
class SpendLimits:
    """Per-call and per-run spend limits in micro-USD."""

    max_call_microusd: int
    max_run_microusd: int

    def __post_init__(self) -> None:
        for label, value in (
            ("max_call_microusd", self.max_call_microusd),
            ("max_run_microusd", self.max_run_microusd),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SpendControlRejected(f"{label} must be a positive integer")
        if self.max_call_microusd > self.max_run_microusd:
            raise SpendControlRejected("The per-call limit cannot exceed the run limit")


@dataclass(frozen=True)
class Calibration:
    """Per-provider token estimate and tolerance, established by measurement."""

    characters_per_token: Decimal
    tolerance: Decimal

    def __post_init__(self) -> None:
        if self.characters_per_token <= 0 or self.tolerance < 0:
            raise SpendControlRejected("Calibration values must be positive")


@dataclass(frozen=True)
class LedgerIdentity:
    """Constant identifiers written on every ledger record."""

    schema_version: str
    provider: str
    model_id: str
    configuration_version: str
    prompt_version: str
    pricing_version: str


def estimate_input_tokens(characters: int, calibration: Calibration) -> int:
    return int(
        (Decimal(characters) / calibration.characters_per_token).to_integral_value(
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


def exceeds_tolerance(*, estimated: int, actual: int, calibration: Calibration) -> bool:
    return Decimal(actual) > Decimal(estimated) * (1 + calibration.tolerance)


class SpendControlledCalls:
    """Runs provider calls one at a time under the spend limits and ledger."""

    def __init__(
        self,
        *,
        identity: LedgerIdentity,
        pricing: ProviderPricing,
        limits: SpendLimits,
        calibration: Calibration,
        output_token_cap: int,
        ledger_path: Path,
        worst_case_input_microusd_per_million_tokens: int | None = None,
        extra_ledger_fields: tuple[str, ...] = (),
        usage_details: Callable[[StructuredModelResponse], Mapping[str, int | None]]
        | None = None,
    ) -> None:
        if output_token_cap <= 0:
            raise SpendControlRejected("output_token_cap must be positive")
        if worst_case_input_microusd_per_million_tokens is not None and (
            isinstance(worst_case_input_microusd_per_million_tokens, bool)
            or not isinstance(worst_case_input_microusd_per_million_tokens, int)
            or worst_case_input_microusd_per_million_tokens
            < pricing.input_microusd_per_million_tokens
        ):
            raise SpendControlRejected(
                "The worst-case input rate must be an integer not below the input rate"
            )
        if (usage_details is None) != (not extra_ledger_fields):
            raise SpendControlRejected(
                "extra_ledger_fields and usage_details must be set together"
            )
        if len(set(extra_ledger_fields)) != len(extra_ledger_fields) or (
            set(extra_ledger_fields) & _BASE_LEDGER_FIELDS
        ):
            raise SpendControlRejected(
                "extra_ledger_fields must be unique and must not replace ledger fields"
            )
        self._worst_case_pricing = (
            pricing
            if worst_case_input_microusd_per_million_tokens is None
            else replace(
                pricing,
                input_microusd_per_million_tokens=(
                    worst_case_input_microusd_per_million_tokens
                ),
            )
        )
        self._extra_ledger_fields = extra_ledger_fields
        self._usage_details = usage_details
        self._identity = identity
        self._pricing = pricing
        self._limits = limits
        self._calibration = calibration
        self._output_token_cap = output_token_cap
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
            raise SpendControlRejected(
                "Call ledger already exists; choose a new ledger path"
            ) from error
        except OSError as error:
            raise SpendControlRejected("Call ledger could not be created") from error

    @property
    def running_total_microusd(self) -> int:
        return self._running_total_microusd

    def run(
        self,
        *,
        estimated_characters: int,
        invoke: Callable[[], StructuredModelResponse],
        validate: Callable[[StructuredModelResponse], None],
    ) -> StructuredModelResponse:
        """Make one controlled call; ``validate`` raises to reject the output."""

        if not self._call_lock.acquire(blocking=False):
            self._closed_reason = "concurrent_call"
            raise SpendControlRejected(
                "Evaluation requires max_concurrency 1; an overlapping call was "
                "rejected and the model is closed"
            )
        try:
            return self._run_one(estimated_characters, invoke, validate)
        finally:
            self._call_lock.release()

    def _run_one(
        self,
        estimated_characters: int,
        invoke: Callable[[], StructuredModelResponse],
        validate: Callable[[StructuredModelResponse], None],
    ) -> StructuredModelResponse:
        if self._closed_reason is not None:
            raise SpendControlRejected(
                f"Model is closed after an earlier failure ({self._closed_reason})"
            )

        self._call_count += 1
        estimated_input_tokens = estimate_input_tokens(
            estimated_characters, self._calibration
        )
        worst_case_microusd = cost_microusd(
            self._worst_case_pricing,
            input_tokens=estimated_input_tokens,
            output_tokens=self._output_token_cap,
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
            response = invoke()
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
            calibration_ratio=round(
                response.usage.input_tokens / max(estimated_input_tokens, 1), 4
            ),
            response_id=response.response_id,
        )
        if self._usage_details is not None:
            try:
                details = dict(self._usage_details(response))
            except Exception as error:
                self._fail(entry, "invalid_usage_details", charged=charged, cause=error)
            if set(details) != set(self._extra_ledger_fields) or any(
                value is not None
                and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
                for value in details.values()
            ):
                self._fail(entry, "invalid_usage_details", charged=charged)
            entry.update(details)

        if self._running_total_microusd + charged > self._limits.max_run_microusd:
            self._fail(entry, "run_limit_exceeded_after_call", charged=charged)
        if exceeds_tolerance(
            estimated=estimated_input_tokens,
            actual=response.usage.input_tokens,
            calibration=self._calibration,
        ):
            self._fail(entry, "input_token_estimate_exceeded", charged=charged)
        try:
            validate(response)
        except Exception as error:
            # Fail here, not in the executor, so later queued calls cannot spend.
            self._fail(entry, "invalid_output", charged=charged, cause=error)

        self._running_total_microusd += charged
        self._write_ledger(entry, outcome="succeeded", charged=charged, failure=None)
        return response

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
        raise SpendControlRejected(
            f"Evaluation call {entry['call_index']} failed closed: {reason}"
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
            "schema_version": self._identity.schema_version,
            "provider": self._identity.provider,
            "model_id": self._identity.model_id,
            "configuration_version": self._identity.configuration_version,
            "prompt_version": self._identity.prompt_version,
            "pricing_version": self._identity.pricing_version,
            "call_index": entry["call_index"],
            "outcome": outcome,
            "failure": failure,
            "estimated_input_tokens": entry["estimated_input_tokens"],
            "actual_input_tokens": entry.get("actual_input_tokens"),
            "output_tokens": entry.get("output_tokens"),
            "calibration_ratio": entry.get("calibration_ratio"),
            "response_id": entry.get("response_id"),
            "worst_case_microusd": entry["worst_case_microusd"],
            "charged_microusd": charged,
            "running_total_microusd": self._running_total_microusd,
            "max_call_microusd": self._limits.max_call_microusd,
            "max_run_microusd": self._limits.max_run_microusd,
            "characters_per_token": str(self._calibration.characters_per_token),
            "tolerance": str(self._calibration.tolerance),
        }
        for name in self._extra_ledger_fields:
            record[name] = entry.get(name)
        with self._ledger_path.open("a", encoding="utf-8", newline="\n") as ledger:
            ledger.write(json.dumps(record, sort_keys=True) + "\n")


def required_setting(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise SpendControlRejected(f"{name} must be set for evaluation")
    return value


def usd_setting_to_microusd(environment: Mapping[str, str], name: str) -> int:
    text = required_setting(environment, name)
    try:
        amount = Decimal(text)
    except InvalidOperation as error:
        raise SpendControlRejected(f"{name} must be a USD amount") from error
    if not amount.is_finite() or amount <= 0:
        raise SpendControlRejected(f"{name} must be a positive USD amount")
    microusd = amount * MICROUSD_PER_USD
    if microusd != microusd.to_integral_value():
        raise SpendControlRejected(f"{name} must not be finer than one micro-USD")
    return int(microusd)
