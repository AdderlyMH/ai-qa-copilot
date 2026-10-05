from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import cast

import pytest

from ai_qa_copilot_api.c1_evaluation_model import (
    C1_B0_OUTPUT_SCHEMA,
    C1_B0_SYSTEM_INSTRUCTION,
    C1_INPUT_TOKEN_ESTIMATE_TOLERANCE,
    C1B0Model,
    C1EvaluationRejected,
    C1SpendLimits,
    c1_b0_model_from_mapping,
    cost_microusd,
    estimate_input_tokens,
    exceeds_estimate_tolerance,
    load_c1_pricing,
)
from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_runner import run_evaluation_cases
from ai_qa_copilot_api.model_gateway import (
    ANTHROPIC_MESSAGES_URL,
    C1_MAX_TOKENS,
    C1_MODEL_ID,
    AnthropicGatewaySettings,
    ModelGatewayConfigurationError,
)
from ai_qa_copilot_api.naive_baseline import (
    DEFAULT_B0_CONFIG_PATH,
    NaiveBaselineExecutor,
    load_naive_baseline_config,
)


ROOT = Path(__file__).resolve().parents[3]
PRICING_PATH = ROOT / "fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml"
V2_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v2.yaml"
API_KEY = "test-anthropic-key-not-real"
VALID_OUTPUT = {
    "boundary": "analysis_only",
    "ground_truth_ids": ["GT-FIND-001"],
    "source_references": ["REQ-BASE-001#REQ-ORDER-004:statement"],
}


def anthropic_payload(
    *,
    input_tokens: int,
    output_tokens: int = 200,
    stop_reason: str = "end_turn",
    output: Mapping[str, object] = VALID_OUTPUT,
) -> dict[str, object]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": C1_MODEL_ID,
        "stop_reason": stop_reason,
        "content": [{"type": "text", "text": json.dumps(dict(output))}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


class FakeTransport:
    def __init__(
        self,
        respond: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> None:
        self._respond = respond
        self.bodies: list[Mapping[str, object]] = []

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        assert url == ANTHROPIC_MESSAGES_URL
        self.bodies.append(body)
        return self._respond(body)


def prompt_of(body: Mapping[str, object]) -> str:
    messages = cast(list[dict[str, list[dict[str, str]]]], body["messages"])
    return messages[0]["content"][0]["text"]


def exact_estimate_transport(
    *, output_tokens: int = 200, scale: Decimal = Decimal(1)
) -> FakeTransport:
    """Report input tokens equal to (a multiple of) the factory's own estimate."""

    def respond(body: Mapping[str, object]) -> Mapping[str, object]:
        estimate = estimate_input_tokens(prompt_of(body))
        actual = int(
            (Decimal(estimate) * scale).to_integral_value(rounding=ROUND_CEILING)
        )
        return anthropic_payload(input_tokens=actual, output_tokens=output_tokens)

    return FakeTransport(respond)


def make_model(
    tmp_path: Path,
    transport: FakeTransport,
    *,
    max_call_microusd: int = 90_000,
    max_run_microusd: int = 720_000,
) -> C1B0Model:
    return C1B0Model(
        settings=AnthropicGatewaySettings(api_key=API_KEY),
        pricing=load_c1_pricing(PRICING_PATH),
        limits=C1SpendLimits(
            max_call_microusd=max_call_microusd,
            max_run_microusd=max_run_microusd,
        ),
        ledger_path=tmp_path / "c1-ledger.jsonl",
        transport=transport,
    )


def ledger(tmp_path: Path) -> list[dict[str, object]]:
    text = (tmp_path / "c1-ledger.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def worst_case(prompt: str) -> int:
    return cost_microusd(
        load_c1_pricing(PRICING_PATH),
        input_tokens=estimate_input_tokens(prompt),
        output_tokens=C1_MAX_TOKENS,
    )


# Pricing input


def test_committed_pricing_input_is_explicit_and_versioned() -> None:
    pricing = load_c1_pricing(PRICING_PATH)

    assert pricing.provider == "anthropic"
    assert pricing.model_id == C1_MODEL_ID
    assert pricing.input_microusd_per_million_tokens == 2_000_000
    assert pricing.output_microusd_per_million_tokens == 10_000_000
    assert pricing.source_reference == (
        "https://platform.claude.com/docs/en/about-claude/pricing"
    )
    assert "2026-10-04" in pricing.pricing_version
    assert "no-inference-geo" in pricing.pricing_version


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "openai"),
        ("model_id", "claude-opus-5-5"),
        ("routing", "us_inference_geo"),
        ("pricing_version", "anthropic-claude-sonnet-5-5/2026-10-04"),
        ("source_reference", "platform.claude.com/pricing"),
        ("input_microusd_per_million_tokens", -1),
    ],
)
def test_pricing_input_rejects_unapproved_values(
    tmp_path: Path, field: str, value: object
) -> None:
    text = PRICING_PATH.read_text(encoding="utf-8")
    lines = [
        f"{field}: {json.dumps(value)}" if line.startswith(f"{field}:") else line
        for line in text.splitlines()
    ]
    path = tmp_path / "pricing.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(C1EvaluationRejected):
        load_c1_pricing(path)


def test_pricing_input_rejects_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "pricing.yaml"
    path.write_text(
        PRICING_PATH.read_text(encoding="utf-8") + "cache_read: 200000\n",
        encoding="utf-8",
    )

    with pytest.raises(C1EvaluationRejected, match="fields"):
        load_c1_pricing(path)


# Request shape and estimation


def test_request_is_the_pinned_c1_shape_without_inference_geo(tmp_path: Path) -> None:
    transport = exact_estimate_transport()
    model = make_model(tmp_path, transport)

    model.complete(prompt="Analyze the synthetic artifact.")

    (body,) = transport.bodies
    assert set(body) == {"model", "max_tokens", "system", "messages", "output_config"}
    assert "inference_geo" not in body
    assert body["model"] == C1_MODEL_ID
    assert body["max_tokens"] == C1_MAX_TOKENS
    assert body["system"] == C1_B0_SYSTEM_INSTRUCTION
    assert prompt_of(body) == "Analyze the synthetic artifact."
    assert body["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": dict(C1_B0_OUTPUT_SCHEMA)},
    }


def test_estimate_counts_the_system_field_and_output_schema() -> None:
    wrapper_characters = len(C1_B0_SYSTEM_INSTRUCTION) + len(
        json.dumps(C1_B0_OUTPUT_SCHEMA, separators=(",", ":"))
    )
    prompt = "x" * 2_100

    expected = (
        Decimal(len(prompt) + wrapper_characters) / Decimal("2.1")
    ).to_integral_value(rounding=ROUND_CEILING)
    assert estimate_input_tokens(prompt) == int(expected)
    assert estimate_input_tokens(prompt) > 1_000


# Successful call and ledger


def test_successful_call_reports_priced_cost_and_writes_a_content_free_ledger(
    tmp_path: Path,
) -> None:
    model = make_model(tmp_path, exact_estimate_transport(output_tokens=500))
    prompt = "Secret-free synthetic prompt " * 50

    response = model.complete(prompt=prompt)

    estimate = estimate_input_tokens(prompt)
    expected_microusd = -(-(estimate * 2_000_000 + 500 * 10_000_000) // 1_000_000)
    assert json.loads(response.content) == VALID_OUTPUT
    assert response.cost == expected_microusd / 1_000_000
    assert model.running_total_microusd == expected_microusd

    (entry,) = ledger(tmp_path)
    assert entry["outcome"] == "succeeded"
    assert entry["estimated_input_tokens"] == estimate
    assert entry["actual_input_tokens"] == estimate
    assert entry["charged_microusd"] == expected_microusd
    assert entry["configuration_version"] == "C1/v1"
    raw_ledger = (tmp_path / "c1-ledger.jsonl").read_text(encoding="utf-8")
    assert API_KEY not in raw_ledger
    assert "Secret-free synthetic prompt" not in raw_ledger


def test_ledger_contains_no_prompt_output_or_credentials(tmp_path: Path) -> None:
    prompt = "PROMPT-MARKER-7f3a synthetic request text"
    output_marker = "OUTPUT-MARKER-91c2"
    responses = iter(
        [
            anthropic_payload(
                input_tokens=estimate_input_tokens(prompt),
                output={
                    "boundary": output_marker,
                    "ground_truth_ids": [f"{output_marker}-GT"],
                    "source_references": [f"{output_marker}#ref"],
                },
            ),
            anthropic_payload(
                input_tokens=estimate_input_tokens(prompt),
                stop_reason="refusal",
            ),
        ]
    )
    model = make_model(tmp_path, FakeTransport(lambda body: next(responses)))

    model.complete(prompt=prompt)
    with pytest.raises(C1EvaluationRejected):
        model.complete(prompt=prompt)

    raw_ledger = (tmp_path / "c1-ledger.jsonl").read_text(encoding="utf-8")
    assert [entry["outcome"] for entry in ledger(tmp_path)] == ["succeeded", "failed"]
    for forbidden in (
        "PROMPT-MARKER-7f3a",
        output_marker,
        C1_B0_SYSTEM_INSTRUCTION,
        API_KEY,
        "x-api-key",
    ):
        assert forbidden not in raw_ledger


def test_existing_ledger_is_never_reused(tmp_path: Path) -> None:
    (tmp_path / "c1-ledger.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(C1EvaluationRejected, match="ledger already exists"):
        make_model(tmp_path, exact_estimate_transport())


# Spend limits


def test_worst_case_above_call_limit_is_refused_before_the_request(
    tmp_path: Path,
) -> None:
    transport = exact_estimate_transport()
    prompt = "x" * 2_100
    model = make_model(tmp_path, transport, max_call_microusd=worst_case(prompt) - 1)

    with pytest.raises(C1EvaluationRejected, match="worst_case_exceeds_call_limit"):
        model.complete(prompt=prompt)

    assert transport.bodies == []
    assert ledger(tmp_path)[0]["charged_microusd"] == 0


def test_worst_case_above_remaining_run_budget_is_refused_before_the_request(
    tmp_path: Path,
) -> None:
    transport = exact_estimate_transport(output_tokens=100)
    prompt = "x" * 2_100
    limit = worst_case(prompt)
    model = make_model(
        tmp_path, transport, max_call_microusd=limit, max_run_microusd=limit
    )

    model.complete(prompt=prompt)
    with pytest.raises(
        C1EvaluationRejected, match="worst_case_exceeds_remaining_run_budget"
    ):
        model.complete(prompt=prompt)

    assert len(transport.bodies) == 1


def test_running_total_above_run_limit_after_a_call_fails_closed(
    tmp_path: Path,
) -> None:
    # Actual input is 10% above the estimate (within calibration tolerance) and
    # output hits max_tokens, so the actual cost exceeds the reserved worst case.
    transport = exact_estimate_transport(
        output_tokens=C1_MAX_TOKENS, scale=Decimal("1.10")
    )
    prompt = "x" * 2_100
    limit = worst_case(prompt)
    model = make_model(
        tmp_path, transport, max_call_microusd=limit, max_run_microusd=limit
    )

    with pytest.raises(C1EvaluationRejected, match="run_limit_exceeded_after_call"):
        model.complete(prompt=prompt)

    assert model.running_total_microusd > limit
    with pytest.raises(C1EvaluationRejected, match="closed"):
        model.complete(prompt=prompt)
    assert len(transport.bodies) == 1


# Calibration


def test_input_token_estimate_tolerance_is_fifteen_percent() -> None:
    assert C1_INPUT_TOKEN_ESTIMATE_TOLERANCE == Decimal("0.15")
    assert not exceeds_estimate_tolerance(estimated=1_000, actual=1_150)
    assert exceeds_estimate_tolerance(estimated=1_000, actual=1_151)


def test_actual_input_at_the_tolerance_boundary_is_accepted(tmp_path: Path) -> None:
    def respond(body: Mapping[str, object]) -> Mapping[str, object]:
        estimate = estimate_input_tokens(prompt_of(body))
        boundary = int(Decimal(estimate) * (1 + C1_INPUT_TOKEN_ESTIMATE_TOLERANCE))
        return anthropic_payload(input_tokens=boundary)

    model = make_model(tmp_path, FakeTransport(respond))

    model.complete(prompt="x" * 2_100)

    (entry,) = ledger(tmp_path)
    assert entry["outcome"] == "succeeded"
    assert cast(int, entry["actual_input_tokens"]) > cast(
        int, entry["estimated_input_tokens"]
    )


def test_actual_input_above_tolerance_fails_closed_and_is_charged(
    tmp_path: Path,
) -> None:
    transport = exact_estimate_transport(scale=Decimal("1.16"))
    model = make_model(tmp_path, transport)
    prompt = "x" * 2_100

    with pytest.raises(C1EvaluationRejected, match="input_token_estimate_exceeded"):
        model.complete(prompt=prompt)
    with pytest.raises(C1EvaluationRejected, match="closed"):
        model.complete(prompt=prompt)

    (entry,) = ledger(tmp_path)
    assert entry["outcome"] == "failed"
    assert cast(int, entry["actual_input_tokens"]) > cast(
        int, entry["estimated_input_tokens"]
    )
    assert entry["charged_microusd"] == model.running_total_microusd > 0
    assert len(transport.bodies) == 1


# Concurrency and latching


def test_overlapping_call_is_rejected_before_any_request(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    def respond(body: Mapping[str, object]) -> Mapping[str, object]:
        entered.set()
        assert release.wait(timeout=5)
        return anthropic_payload(input_tokens=estimate_input_tokens(prompt_of(body)))

    transport = FakeTransport(respond)
    model = make_model(tmp_path, transport)
    first_result: list[object] = []
    first = threading.Thread(
        target=lambda: first_result.append(model.complete(prompt="first"))
    )
    first.start()
    assert entered.wait(timeout=5)

    with pytest.raises(C1EvaluationRejected, match="max_concurrency 1"):
        model.complete(prompt="second")

    release.set()
    first.join(timeout=5)
    assert len(first_result) == 1
    assert len(transport.bodies) == 1
    with pytest.raises(C1EvaluationRejected, match="closed"):
        model.complete(prompt="third")
    assert len(transport.bodies) == 1


def test_failure_latches_so_queued_runner_cases_make_no_more_requests(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(
        lambda body: anthropic_payload(
            input_tokens=estimate_input_tokens(prompt_of(body)),
            stop_reason="refusal",
        )
    )
    model = make_model(tmp_path, transport, max_run_microusd=5_400_000)
    executor = NaiveBaselineExecutor(
        configuration=load_naive_baseline_config(ROOT / DEFAULT_B0_CONFIG_PATH),
        repository_root=ROOT,
        model=model,
    )

    with pytest.raises(C1EvaluationRejected, match="ModelGatewayRefusal"):
        run_evaluation_cases(
            load_evaluation_case_suite(V2_FIXTURE),
            fixture_path=V2_FIXTURE,
            repository_root=ROOT,
            executor=executor,
            case_ids=("EVAL-001", "EVAL-002", "EVAL-003"),
            max_expected_cost=0.27,
            max_concurrency=1,
        )

    assert len(transport.bodies) == 1
    (entry,) = ledger(tmp_path)
    assert entry["failure"] == "provider_call_failed:ModelGatewayRefusal"
    assert entry["charged_microusd"] == entry["worst_case_microusd"]
    assert model.running_total_microusd == entry["worst_case_microusd"]


def test_invalid_b0_output_fails_closed(tmp_path: Path) -> None:
    transport = FakeTransport(
        lambda body: anthropic_payload(
            input_tokens=estimate_input_tokens(prompt_of(body)),
            output={
                "boundary": "analysis_only",
                "ground_truth_ids": ["GT-1", "GT-1"],
                "source_references": [],
            },
        )
    )
    model = make_model(tmp_path, transport)

    with pytest.raises(C1EvaluationRejected, match="invalid_b0_output"):
        model.complete(prompt="prompt")
    with pytest.raises(C1EvaluationRejected, match="closed"):
        model.complete(prompt="prompt")


def test_b0_executor_end_to_end_cost_is_within_the_v2_case_budget(
    tmp_path: Path,
) -> None:
    model = make_model(tmp_path, exact_estimate_transport(output_tokens=C1_MAX_TOKENS))
    executor = NaiveBaselineExecutor(
        configuration=load_naive_baseline_config(ROOT / DEFAULT_B0_CONFIG_PATH),
        repository_root=ROOT,
        model=model,
    )
    suite = load_evaluation_case_suite(V2_FIXTURE)

    report = run_evaluation_cases(
        suite,
        fixture_path=V2_FIXTURE,
        repository_root=ROOT,
        executor=executor,
        case_ids=("EVAL-025",),  # uses both artifacts
        max_expected_cost=0.09,
        max_concurrency=1,
    )

    (result,) = report.results
    assert 0 < result.observation.cost <= 0.09


# Environment composition


def environment(tmp_path: Path, **overrides: str) -> dict[str, str]:
    values = {
        "ANTHROPIC_API_KEY": API_KEY,
        "AI_QA_COPILOT_C1_PRICING_PATH": str(PRICING_PATH),
        "AI_QA_COPILOT_C1_CALL_LEDGER_PATH": str(tmp_path / "c1-ledger.jsonl"),
        "AI_QA_COPILOT_C1_MAX_CALL_COST_USD": "0.09",
        "AI_QA_COPILOT_C1_MAX_RUN_COST_USD": "0.72",
    }
    values.update(overrides)
    return values


def test_environment_composition_converts_usd_limits(tmp_path: Path) -> None:
    transport = exact_estimate_transport()
    model = c1_b0_model_from_mapping(environment(tmp_path), transport=transport)

    model.complete(prompt="prompt")

    (entry,) = ledger(tmp_path)
    assert entry["max_call_microusd"] == 90_000
    assert entry["max_run_microusd"] == 720_000


@pytest.mark.parametrize(
    "missing",
    [
        "AI_QA_COPILOT_C1_PRICING_PATH",
        "AI_QA_COPILOT_C1_CALL_LEDGER_PATH",
        "AI_QA_COPILOT_C1_MAX_CALL_COST_USD",
        "AI_QA_COPILOT_C1_MAX_RUN_COST_USD",
    ],
)
def test_environment_composition_requires_every_spend_control(
    tmp_path: Path, missing: str
) -> None:
    values = environment(tmp_path)
    del values[missing]

    with pytest.raises(C1EvaluationRejected, match=missing):
        c1_b0_model_from_mapping(values)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AI_QA_COPILOT_C1_MAX_RUN_COST_USD", "0"),
        ("AI_QA_COPILOT_C1_MAX_RUN_COST_USD", "-1"),
        ("AI_QA_COPILOT_C1_MAX_RUN_COST_USD", "NaN"),
        ("AI_QA_COPILOT_C1_MAX_CALL_COST_USD", "ninety cents"),
        ("AI_QA_COPILOT_C1_MAX_CALL_COST_USD", "0.0000001"),
        ("AI_QA_COPILOT_C1_MAX_CALL_COST_USD", "1.00"),
    ],
)
def test_environment_composition_rejects_invalid_limits(
    tmp_path: Path, name: str, value: str
) -> None:
    with pytest.raises(C1EvaluationRejected):
        c1_b0_model_from_mapping(environment(tmp_path, **{name: value}))


def test_missing_api_key_fails_without_echoing_credentials(tmp_path: Path) -> None:
    with pytest.raises(ModelGatewayConfigurationError) as error:
        c1_b0_model_from_mapping(environment(tmp_path, ANTHROPIC_API_KEY=""))

    assert API_KEY not in str(error.value)
