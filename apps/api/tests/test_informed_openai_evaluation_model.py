"""O1/v1 OpenAI informed factory, its pricing loader and the spend-core options.

Fake transports only; no test makes a provider or network call.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import Callable, Mapping
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
import yaml

from ai_qa_copilot_api.c1_evaluation_model import load_c1_pricing
from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    EvaluationExpected,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_runner import run_evaluation_cases
from ai_qa_copilot_api.evaluation_spend_control import (
    Calibration,
    LedgerIdentity,
    SpendControlledCalls,
    SpendControlRejected,
    SpendLimits,
    estimate_input_tokens,
)
from ai_qa_copilot_api.informed_baseline import (
    DEFAULT_INFORMED_CONFIG_PATH,
    INFORMED_CONFIG_PATH_ENVIRONMENT_VARIABLE,
    INFORMED_MODEL_FACTORY_ENVIRONMENT_VARIABLE,
    INFORMED_REPOSITORY_ROOT_ENVIRONMENT_VARIABLE,
    InformedBaselineExecutor,
    InformedModelResponse,
    create_informed_baseline_executor,
    load_informed_baseline_config,
)
from ai_qa_copilot_api.informed_claude_evaluation_model import (
    INFORMED_LEDGER_PATH_ENVIRONMENT_VARIABLE,
    INFORMED_MAX_CALL_COST_ENVIRONMENT_VARIABLE,
    INFORMED_MAX_RUN_COST_ENVIRONMENT_VARIABLE,
    INFORMED_PRICING_PATH_ENVIRONMENT_VARIABLE,
    InformedClaudeModel,
)
from ai_qa_copilot_api.informed_openai_evaluation_model import (
    OPENAI_INFORMED_CALIBRATION,
    InformedOpenAIModel,
    OpenAIInformedEvaluationRejected,
    informed_openai_model_from_mapping,
    load_openai_informed_pricing,
)
from ai_qa_copilot_api.metrics import ProviderPricing
from ai_qa_copilot_api.model_gateway import (
    ANTHROPIC_MESSAGES_URL,
    OPENAI_RESPONSES_URL,
    AnthropicGatewaySettings,
    ModelUsage,
    StructuredModelResponse,
)
from ai_qa_copilot_api.openai_informed_evaluation_adapter import (
    OpenAIInformedSettings,
)


ROOT = Path(__file__).resolve().parents[3]
PRICING_PATH = ROOT / "fixtures/benchmark/pricing/openai-gpt-6-1-sol.v1.yaml"
CLAUDE_PRICING_PATH = (
    ROOT / "fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml"
)
V4_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v4.yaml"
CONFIG_PATH = ROOT / DEFAULT_INFORMED_CONFIG_PATH
API_KEY = "test-openai-key-not-real"
VALID_OUTPUT = {
    "boundary": "analysis_only",
    "ground_truth_ids": ["GT-FIND-001"],
    "source_references": ["REQ-BASE-001#REQ-ORDER-004#statement"],
}
LIMIT_CALL = 110_000
LIMIT_RUN = 880_000

# Ledger bytes written by the spend core on main before the additive change,
# for a fixed scenario (one success, one failed call). The core must still write
# exactly these bytes when the new options are left unset.
PRE_CHANGE_LEDGER = (
    '{"actual_input_tokens": 7000, "calibration_ratio": 0.7, "call_index": 1, '
    '"characters_per_token": "2.1", "charged_microusd": 17000, '
    '"configuration_version": "C1/v1", "estimated_input_tokens": 10000, '
    '"failure": null, "max_call_microusd": 100000, "max_run_microusd": 800000, '
    '"model_id": "claude-sonnet-5-5", "outcome": "succeeded", "output_tokens": 300, '
    '"pricing_version": "pricing-v", "prompt_version": "informed-single-prompt/v1", '
    '"provider": "anthropic", "response_id": "resp_1", '
    '"running_total_microusd": 17000, "schema_version": "informed-call-ledger/v1", '
    '"tolerance": "0.15", "worst_case_microusd": 60960}\n'
    '{"actual_input_tokens": null, "calibration_ratio": null, "call_index": 2, '
    '"characters_per_token": "2.1", "charged_microusd": 60960, '
    '"configuration_version": "C1/v1", "estimated_input_tokens": 10000, '
    '"failure": "provider_call_failed:RuntimeError", "max_call_microusd": 100000, '
    '"max_run_microusd": 800000, "model_id": "claude-sonnet-5-5", '
    '"outcome": "failed", "output_tokens": null, "pricing_version": "pricing-v", '
    '"prompt_version": "informed-single-prompt/v1", "provider": "anthropic", '
    '"response_id": null, "running_total_microusd": 77960, '
    '"schema_version": "informed-call-ledger/v1", "tolerance": "0.15", '
    '"worst_case_microusd": 60960}\n'
)


def openai_payload(
    *,
    input_tokens: int,
    output_tokens: int = 300,
    reasoning_tokens: int | None = 120,
    output: Mapping[str, object] = VALID_OUTPUT,
    cache_write_tokens: int = 0,
    status: str = "completed",
    incomplete_reason: str | None = None,
) -> dict[str, object]:
    usage: dict[str, object] = {
        "input_tokens": input_tokens,
        "input_tokens_details": {
            "cached_tokens": 0,
            "cache_write_tokens": cache_write_tokens,
        },
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if reasoning_tokens is not None:
        usage["output_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return {
        "id": "resp_test",
        "object": "response",
        "model": "gpt-6.1-sol",
        "status": status,
        "error": None,
        "incomplete_details": (
            {"reason": incomplete_reason} if incomplete_reason else None
        ),
        "service_tier": "default",
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(dict(output))}],
            },
        ],
        "usage": usage,
    }


def request_characters(body: Mapping[str, object]) -> int:
    messages = cast(list[dict[str, list[dict[str, str]]]], body["input"])
    text_format = cast(dict[str, dict[str, object]], body["text"])["format"]
    schema = json.dumps(text_format["schema"], separators=(",", ":"))
    return (
        len(messages[0]["content"][0]["text"])
        + len(messages[1]["content"][0]["text"])
        + len(schema)
    )


def exact_input_tokens(body: Mapping[str, object], scale: Decimal = Decimal(1)) -> int:
    estimate = estimate_input_tokens(
        request_characters(body), OPENAI_INFORMED_CALIBRATION
    )
    return int((Decimal(estimate) * scale).to_integral_value(rounding=ROUND_CEILING))


class FakeTransport:
    def __init__(
        self,
        respond: Callable[[Mapping[str, object]], Mapping[str, object]],
        url: str = OPENAI_RESPONSES_URL,
    ) -> None:
        self._respond = respond
        self._url = url
        self.bodies: list[Mapping[str, object]] = []
        self.headers: list[Mapping[str, str]] = []

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        assert url == self._url
        self.bodies.append(body)
        self.headers.append(headers)
        return self._respond(body)


def estimate_transport(*, scale: Decimal = Decimal(1), **payload: Any) -> FakeTransport:
    return FakeTransport(
        lambda body: openai_payload(
            input_tokens=exact_input_tokens(body, scale), **payload
        )
    )


def make_model(
    tmp_path: Path,
    transport: FakeTransport,
    *,
    max_call: int = LIMIT_CALL,
    max_run: int = LIMIT_RUN,
    ledger_name: str = "informed-ledger.jsonl",
) -> InformedOpenAIModel:
    return InformedOpenAIModel(
        settings=OpenAIInformedSettings(api_key=API_KEY),
        pricing=load_openai_informed_pricing(PRICING_PATH),
        limits=SpendLimits(max_call_microusd=max_call, max_run_microusd=max_run),
        ledger_path=tmp_path / ledger_name,
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        transport=transport,
    )


def ledger(
    tmp_path: Path, name: str = "informed-ledger.jsonl"
) -> list[dict[str, object]]:
    text = (tmp_path / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def v4_case(case_id: str) -> EvaluationCase:
    return next(
        case
        for case in load_evaluation_case_suite(V4_FIXTURE).cases
        if case.id == case_id
    )


class UnusedModel:
    def complete(self, **_: str) -> InformedModelResponse:
        raise AssertionError("prompt construction must not call a model")


def executor(model: object = None) -> InformedBaselineExecutor:
    return InformedBaselineExecutor(
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        model=cast(InformedOpenAIModel, model or UnusedModel()),
    )


def prompt_for(case_id: str = "EVAL-101") -> tuple[str, str]:
    prompt = executor().build_prompt(v4_case(case_id))
    return prompt.developer_instruction, prompt.user_input


def characters_for(case_id: str) -> int:
    developer, user = prompt_for(case_id)
    schema = json.dumps(executor().output_schema, separators=(",", ":"))
    return len(developer) + len(user) + len(schema)


def worst_case_microusd(case_id: str = "EVAL-101") -> int:
    tokens = estimate_input_tokens(characters_for(case_id), OPENAI_INFORMED_CALIBRATION)
    return -(-(tokens * 2_500_000 + 4096 * 10_000_000) // 1_000_000)


# --- Request shape --------------------------------------------------------


def test_request_carries_the_claude_texts_and_a_byte_identical_schema(
    tmp_path: Path,
) -> None:
    developer, user = prompt_for()
    openai = estimate_transport()
    make_model(tmp_path, openai).complete(
        developer_instruction=developer, user_input=user
    )

    def claude_payload(body: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(VALID_OUTPUT)}],
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }

    claude = FakeTransport(claude_payload, url=ANTHROPIC_MESSAGES_URL)
    InformedClaudeModel(
        settings=AnthropicGatewaySettings(api_key="test-anthropic-key-not-real"),
        pricing=load_c1_pricing(CLAUDE_PRICING_PATH),
        limits=SpendLimits(max_call_microusd=100_000, max_run_microusd=800_000),
        ledger_path=tmp_path / "claude-ledger.jsonl",
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        transport=claude,
    ).complete(developer_instruction=developer, user_input=user)

    openai_body = openai.bodies[0]
    claude_body = claude.bodies[0]
    openai_input = cast(list[dict[str, list[dict[str, str]]]], openai_body["input"])
    claude_messages = cast(
        list[dict[str, list[dict[str, str]]]], claude_body["messages"]
    )
    openai_schema = cast(dict[str, dict[str, object]], openai_body["text"])["format"][
        "schema"
    ]
    claude_schema = cast(dict[str, dict[str, object]], claude_body["output_config"])[
        "format"
    ]["schema"]

    assert openai_input[0]["content"][0]["text"] == claude_body["system"] == developer
    assert (
        openai_input[1]["content"][0]["text"]
        == claude_messages[0]["content"][0]["text"]
        == user
    )
    assert json.dumps(openai_schema).encode() == json.dumps(claude_schema).encode()
    assert (
        json.dumps(openai_schema).encode()
        == json.dumps(executor().output_schema).encode()
    )
    assert set(openai_body) == {
        "model",
        "input",
        "reasoning",
        "max_output_tokens",
        "text",
        "store",
        "service_tier",
        "prompt_cache_options",
    }
    assert openai_body["model"] == "gpt-6.1-sol"
    assert openai_body["reasoning"] == {"effort": "medium"}
    assert openai_body["max_output_tokens"] == 4096
    assert openai_body["prompt_cache_options"] == {"mode": "explicit"}
    assert openai_body["store"] is False
    assert openai_body["service_tier"] == "default"
    assert (
        cast(dict[str, dict[str, object]], openai_body["text"])["format"]["strict"]
        is True
    )
    for forbidden in ("tools", "tool_choice", "stream", "temperature", "top_p"):
        assert forbidden not in openai_body


# --- Ledger and charges ---------------------------------------------------


def test_success_writes_one_content_free_openai_ledger_record(tmp_path: Path) -> None:
    developer, user = prompt_for()
    model = make_model(tmp_path, estimate_transport(scale=Decimal("0.7")))

    response = model.complete(developer_instruction=developer, user_input=user)

    (record,) = ledger(tmp_path)
    assert record["schema_version"] == "informed-call-ledger/v1"
    assert record["provider"] == "openai"
    assert record["model_id"] == "gpt-6.1-sol"
    assert record["configuration_version"] == "O1/v1"
    assert record["prompt_version"] == "informed-single-prompt/v1"
    assert record["pricing_version"] == (
        "openai-gpt-6.1-sol/2026-10-08/standard-short-context-cache-disabled"
    )
    assert record["outcome"] == "succeeded"
    assert record["reasoning_tokens"] == 120
    assert record["calibration_ratio"] == pytest.approx(0.7, abs=0.001)
    actual = cast(int, record["actual_input_tokens"])
    # Charged at the 2 USD input rate, not the 2.50 worst-case rate.
    assert record["charged_microusd"] == -(
        -(actual * 2_000_000 + 300 * 10_000_000) // 1_000_000
    )
    assert record["worst_case_microusd"] == worst_case_microusd()
    assert response.cost == record["charged_microusd"] / 1_000_000
    assert json.loads(response.content) == VALID_OUTPUT


def test_reasoning_tokens_are_null_in_the_ledger_when_not_reported(
    tmp_path: Path,
) -> None:
    developer, user = prompt_for()
    make_model(tmp_path, estimate_transport(reasoning_tokens=None)).complete(
        developer_instruction=developer, user_input=user
    )

    assert ledger(tmp_path)[0]["reasoning_tokens"] is None


def test_ledger_holds_no_prompt_output_or_credential(tmp_path: Path) -> None:
    developer, user = prompt_for()
    make_model(tmp_path, estimate_transport()).complete(
        developer_instruction=developer, user_input=user
    )
    with pytest.raises(SpendControlRejected):
        make_model(
            tmp_path,
            estimate_transport(status="incomplete", incomplete_reason="content_filter"),
            ledger_name="second.jsonl",
        ).complete(developer_instruction=developer, user_input=user)

    raw = (tmp_path / "informed-ledger.jsonl").read_text(encoding="utf-8") + (
        tmp_path / "second.jsonl"
    ).read_text(encoding="utf-8")
    for secret in (
        API_KEY,
        "GT-FIND-001",
        "REQ-ORDER-004",
        "You are a QA analyst",
        user[:60],
        "Objective:",
        "analysis_only",
    ):
        assert secret not in raw


@pytest.mark.parametrize(
    ("payload", "failure"),
    [
        (
            {"status": "incomplete", "incomplete_reason": "content_filter"},
            "ModelGatewayRefusal",
        ),
        (
            {"status": "incomplete", "incomplete_reason": "max_output_tokens"},
            "ModelGatewayTruncated",
        ),
        ({"cache_write_tokens": 50}, "ModelGatewayProtocolError"),
    ],
)
def test_provider_failures_latch_and_charge_the_cache_write_worst_case(
    tmp_path: Path, payload: dict[str, Any], failure: str
) -> None:
    transport = estimate_transport(**payload)
    developer, user = prompt_for()
    model = make_model(tmp_path, transport)

    with pytest.raises(SpendControlRejected, match=failure):
        model.complete(developer_instruction=developer, user_input=user)
    with pytest.raises(SpendControlRejected, match="closed after an earlier failure"):
        model.complete(developer_instruction=developer, user_input=user)

    assert len(transport.bodies) == 1
    (record,) = ledger(tmp_path)
    assert record["failure"] == f"provider_call_failed:{failure}"
    assert (
        record["charged_microusd"]
        == record["worst_case_microusd"]
        == worst_case_microusd()
    )
    assert record["reasoning_tokens"] is None


def test_worst_case_for_the_largest_v4_case_equals_the_adr_016_figure(
    tmp_path: Path,
) -> None:
    assert characters_for("EVAL-111") == 43_253
    assert estimate_input_tokens(43_253, OPENAI_INFORMED_CALIBRATION) == 20_597
    # 20,597 x 2.50 + 4,096 x 10 = 92,452.5 micro-USD, rounded up: 0.0924525 USD.
    assert worst_case_microusd("EVAL-111") == 92_453

    developer, user = prompt_for("EVAL-111")
    exact = make_model(tmp_path, estimate_transport(), max_call=92_453)
    exact.complete(developer_instruction=developer, user_input=user)
    assert ledger(tmp_path)[0]["worst_case_microusd"] == 92_453

    below_dir = tmp_path / "below"
    below_dir.mkdir()
    transport = estimate_transport()
    below = make_model(below_dir, transport, max_call=92_452)
    with pytest.raises(SpendControlRejected, match="worst_case_exceeds_call_limit"):
        below.complete(developer_instruction=developer, user_input=user)
    assert transport.bodies == []
    assert ledger(below_dir)[0]["charged_microusd"] == 0


# --- Limits, calibration, latch, single flight ----------------------------


def test_calibration_constants_are_the_unverified_claude_values() -> None:
    assert OPENAI_INFORMED_CALIBRATION == Calibration(Decimal("2.1"), Decimal("0.15"))


def test_calibration_accepts_exactly_fifteen_percent_over_and_rejects_more(
    tmp_path: Path,
) -> None:
    developer, user = prompt_for()

    def boundary_transport(extra_tokens: int) -> FakeTransport:
        def respond(body: Mapping[str, object]) -> Mapping[str, object]:
            estimate = estimate_input_tokens(
                request_characters(body), OPENAI_INFORMED_CALIBRATION
            )
            limit = int(Decimal(estimate) * Decimal("1.15"))
            return openai_payload(input_tokens=limit + extra_tokens)

        return FakeTransport(respond)

    make_model(tmp_path, boundary_transport(0)).complete(
        developer_instruction=developer, user_input=user
    )
    over_dir = tmp_path / "over"
    over_dir.mkdir()
    over = make_model(over_dir, boundary_transport(1))
    with pytest.raises(SpendControlRejected, match="input_token_estimate_exceeded"):
        over.complete(developer_instruction=developer, user_input=user)
    with pytest.raises(SpendControlRejected, match="closed after an earlier failure"):
        over.complete(developer_instruction=developer, user_input=user)


def test_run_limit_blocks_the_call_that_cannot_fit(tmp_path: Path) -> None:
    transport = estimate_transport(scale=Decimal("0.7"))
    developer, user = prompt_for()
    worst = worst_case_microusd()
    model = make_model(tmp_path, transport, max_call=worst, max_run=worst)

    model.complete(developer_instruction=developer, user_input=user)
    with pytest.raises(
        SpendControlRejected, match="worst_case_exceeds_remaining_run_budget"
    ):
        model.complete(developer_instruction=developer, user_input=user)

    assert len(transport.bodies) == 1


def test_a_call_within_calibration_never_costs_more_than_its_worst_case(
    tmp_path: Path,
) -> None:
    # Input at most 1.15 x the estimate costs at most 2.30 USD per million, below
    # the 2.50 worst-case rate, so with the full 4,096 output tokens the actual
    # charge still fits: an after-call run-limit breach cannot follow a passed
    # pre-call check.
    developer, user = prompt_for()
    worst = worst_case_microusd()

    def respond(body: Mapping[str, object]) -> Mapping[str, object]:
        estimate = estimate_input_tokens(
            request_characters(body), OPENAI_INFORMED_CALIBRATION
        )
        return openai_payload(
            input_tokens=int(Decimal(estimate) * Decimal("1.15")),
            output_tokens=4096,
            reasoning_tokens=4000,
        )

    model = make_model(tmp_path, FakeTransport(respond), max_call=worst, max_run=worst)
    model.complete(developer_instruction=developer, user_input=user)

    (record,) = ledger(tmp_path)
    assert record["outcome"] == "succeeded"
    assert cast(int, record["charged_microusd"]) < worst
    assert model.running_total_microusd <= worst


def test_invalid_output_latches_so_queued_calls_cannot_spend(tmp_path: Path) -> None:
    transport = estimate_transport(
        output={**VALID_OUTPUT, "ground_truth_ids": ["GT-FIND-099"]}
    )
    developer, user = prompt_for()
    model = make_model(tmp_path, transport)

    with pytest.raises(SpendControlRejected, match="invalid_output"):
        model.complete(developer_instruction=developer, user_input=user)
    with pytest.raises(SpendControlRejected, match="closed after an earlier failure"):
        model.complete(developer_instruction=developer, user_input=user)
    assert len(transport.bodies) == 1


@pytest.mark.parametrize(
    "output",
    [
        {**VALID_OUTPUT, "extra": 1},
        {"boundary": "analysis_only", "ground_truth_ids": []},
    ],
    ids=["extra field", "missing field"],
)
def test_extra_or_missing_output_fields_fail_closed(
    tmp_path: Path, output: dict[str, object]
) -> None:
    developer, user = prompt_for()
    with pytest.raises(SpendControlRejected, match="invalid_output"):
        make_model(tmp_path, estimate_transport(output=output)).complete(
            developer_instruction=developer, user_input=user
        )


def test_overlapping_calls_are_rejected_and_close_the_model(tmp_path: Path) -> None:
    developer, user = prompt_for()
    entered = threading.Event()
    release = threading.Event()

    def respond(body: Mapping[str, object]) -> Mapping[str, object]:
        entered.set()
        assert release.wait(timeout=10)
        return openai_payload(input_tokens=exact_input_tokens(body))

    transport = FakeTransport(respond)
    model = make_model(tmp_path, transport)
    thread = threading.Thread(
        target=lambda: model.complete(developer_instruction=developer, user_input=user)
    )
    thread.start()
    assert entered.wait(timeout=10)

    with pytest.raises(SpendControlRejected, match="max_concurrency 1"):
        model.complete(developer_instruction=developer, user_input=user)
    release.set()
    thread.join(timeout=10)

    assert len(transport.bodies) == 1
    with pytest.raises(SpendControlRejected, match="concurrent_call"):
        model.complete(developer_instruction=developer, user_input=user)


def test_existing_ledger_is_never_reused(tmp_path: Path) -> None:
    (tmp_path / "informed-ledger.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(SpendControlRejected, match="already exists"):
        make_model(tmp_path, estimate_transport())


def test_requests_that_could_leave_the_short_context_tier_are_refused(
    tmp_path: Path,
) -> None:
    transport = estimate_transport()
    model = make_model(tmp_path, transport)
    developer, _ = prompt_for()

    with pytest.raises(OpenAIInformedEvaluationRejected, match="272,000"):
        model.complete(developer_instruction=developer, user_input="x" * 500_000)

    assert transport.bodies == []
    assert (tmp_path / "informed-ledger.jsonl").read_text(encoding="utf-8") == ""


# --- Never reads expected values; runs through the executor ----------------


def test_requests_are_identical_when_expected_values_are_sentinels(
    tmp_path: Path,
) -> None:
    sentinel = EvaluationExpected(
        required_ground_truth_ids=("SENTINEL-GT-ID",),
        prohibited_ground_truth_ids=("SENTINEL-PROHIBITED-ID",),
        expected_source_references=("SENTINEL-ARTIFACT#SENTINEL-REFERENCE",),
        policy_boundary="SENTINEL_BOUNDARY",
        side_effects={"model_calls": 999},
        scorer_version="SENTINEL-SCORER",
        maximum_expected_cost=999,
    )
    for case_id in ("EVAL-101", "EVAL-120", "EVAL-131"):
        bodies = []
        for index, case in enumerate(
            (v4_case(case_id), dataclasses.replace(v4_case(case_id), expected=sentinel))
        ):
            transport = estimate_transport()
            model = make_model(
                tmp_path, transport, ledger_name=f"{case_id}-{index}.jsonl"
            )
            executor(model).execute(case)
            bodies.append(json.dumps(transport.bodies[0], sort_keys=True))
        assert bodies[0] == bodies[1]
        assert "SENTINEL" not in bodies[1]


def test_executor_runs_v4_cases_through_the_model_serially(tmp_path: Path) -> None:
    model = make_model(tmp_path, estimate_transport(scale=Decimal("0.7")))
    suite = load_evaluation_case_suite(V4_FIXTURE)

    run = run_evaluation_cases(
        suite,
        executor=executor(model),
        fixture_path=V4_FIXTURE,
        repository_root=ROOT,
        case_ids=("EVAL-101", "EVAL-111"),
        max_expected_cost=0.22,
        max_concurrency=1,
    )

    assert [result.case_id for result in run.results] == ["EVAL-101", "EVAL-111"]
    assert [record["call_index"] for record in ledger(tmp_path)] == [1, 2]
    assert model.running_total_microusd == sum(
        cast(int, record["charged_microusd"]) for record in ledger(tmp_path)
    )


# --- Factory from environment ---------------------------------------------


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "OPENAI_API_KEY": API_KEY,
        INFORMED_PRICING_PATH_ENVIRONMENT_VARIABLE: str(PRICING_PATH),
        INFORMED_MAX_CALL_COST_ENVIRONMENT_VARIABLE: "0.11",
        INFORMED_MAX_RUN_COST_ENVIRONMENT_VARIABLE: "0.88",
        INFORMED_LEDGER_PATH_ENVIRONMENT_VARIABLE: str(tmp_path / "ledger.jsonl"),
        INFORMED_CONFIG_PATH_ENVIRONMENT_VARIABLE: str(CONFIG_PATH),
        INFORMED_REPOSITORY_ROOT_ENVIRONMENT_VARIABLE: str(ROOT),
    }


def test_factory_reads_only_explicit_environment(tmp_path: Path) -> None:
    model = informed_openai_model_from_mapping(
        _environment(tmp_path), transport=estimate_transport()
    )

    assert model.running_total_microusd == 0
    assert (tmp_path / "ledger.jsonl").is_file()


@pytest.mark.parametrize(
    "missing",
    [
        "OPENAI_API_KEY",
        INFORMED_PRICING_PATH_ENVIRONMENT_VARIABLE,
        INFORMED_MAX_CALL_COST_ENVIRONMENT_VARIABLE,
        INFORMED_MAX_RUN_COST_ENVIRONMENT_VARIABLE,
        INFORMED_LEDGER_PATH_ENVIRONMENT_VARIABLE,
    ],
)
def test_factory_refuses_missing_settings(tmp_path: Path, missing: str) -> None:
    environment = _environment(tmp_path)
    del environment[missing]

    with pytest.raises(Exception, match=r"must be (set|configured)"):
        informed_openai_model_from_mapping(environment, transport=estimate_transport())


def test_factory_refuses_the_claude_pricing_file(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment[INFORMED_PRICING_PATH_ENVIRONMENT_VARIABLE] = str(CLAUDE_PRICING_PATH)

    with pytest.raises(
        OpenAIInformedEvaluationRejected, match="fields must be exactly"
    ):
        informed_openai_model_from_mapping(environment, transport=estimate_transport())


def test_cli_executor_factory_loads_the_openai_model_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in _environment(tmp_path).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(
        INFORMED_MODEL_FACTORY_ENVIRONMENT_VARIABLE,
        "ai_qa_copilot_api.informed_openai_evaluation_model:create_informed_openai_model",
    )

    assert isinstance(create_informed_baseline_executor(), InformedBaselineExecutor)
    assert (tmp_path / "ledger.jsonl").is_file()


# --- Pricing loader --------------------------------------------------------


def test_pricing_loader_accepts_the_verified_file() -> None:
    pricing = load_openai_informed_pricing(PRICING_PATH)

    assert pricing.pricing.provider == "openai"
    assert pricing.pricing.model_id == "gpt-6.1-sol"
    assert pricing.pricing.input_microusd_per_million_tokens == 2_000_000
    assert pricing.pricing.output_microusd_per_million_tokens == 10_000_000
    assert pricing.worst_case_input_microusd_per_million_tokens == 2_500_000
    assert pricing.cached_input_microusd_per_million_tokens == 100_000
    assert pricing.short_context_max_input_tokens == 272_000
    assert pricing.long_context_input_and_cache_multiplier == Decimal("2")
    assert pricing.long_context_output_multiplier == Decimal("1.5")


def _pricing_document() -> dict[str, object]:
    return cast(
        dict[str, object], yaml.safe_load(PRICING_PATH.read_text(encoding="utf-8"))
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"unexpected": 1}, "fields must be exactly"),
        ({"output_microusd_per_million_tokens": None}, "fields must be exactly"),
        ({"schema_version": "provider-pricing/v1"}, "schema"),
        ({"provider": "anthropic"}, "for openai"),
        ({"model_id": "gpt-6-sol"}, "gpt-6.1-sol"),
        ({"processing_tier": "flex"}, "standard processing"),
        ({"processing_tier": "batch"}, "standard processing"),
        ({"pricing_version": "openai-gpt-6.1-sol/2026-10-08"}, "pricing_version"),
        (
            {
                "pricing_version": "openai-gpt-6.1-sol/standard-short-context-cache-disabled"
            },
            "pricing_version",
        ),
        ({"source_reference": "https://example.com/pricing"}, "developers.openai.com"),
        ({"short_context_max_input_tokens": 300000}, "272,000"),
        ({"cache_write_microusd_per_million_tokens": 1_000_000}, "not be below"),
        ({"input_microusd_per_million_tokens": True}, "non-negative integer"),
        ({"output_microusd_per_million_tokens": -1}, "non-negative integer"),
        ({"long_context_output_multiplier": "0.5"}, "at least 1"),
        ({"long_context_output_multiplier": 1.5}, "decimal string"),
    ],
)
def test_pricing_loader_refuses_unsafe_variants(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    document = _pricing_document()
    for key, value in change.items():
        if value is None:
            del document[key]
        else:
            document[key] = value
    path = tmp_path / "pricing.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(OpenAIInformedEvaluationRejected, match=message):
        load_openai_informed_pricing(path)


# --- Spend-core options (additive, default off) ----------------------------


_CLAUDE_IDENTITY = LedgerIdentity(
    "informed-call-ledger/v1",
    "anthropic",
    "claude-sonnet-5-5",
    "C1/v1",
    "informed-single-prompt/v1",
    "pricing-v",
)
_PRICING = ProviderPricing(
    "anthropic",
    "claude-sonnet-5-5",
    "pricing-v",
    "https://example.invalid/pricing",
    2_000_000,
    10_000_000,
)
_RESPONSE = StructuredModelResponse(
    correlation_id=UUID(int=1),
    response_id="resp_1",
    model_id="claude-sonnet-5-5",
    output_json={},
    usage=ModelUsage(7000, 300, 7300),
)


def _calls(path: Path, **options: object) -> SpendControlledCalls:
    return SpendControlledCalls(
        identity=_CLAUDE_IDENTITY,
        pricing=_PRICING,
        limits=SpendLimits(100_000, 800_000),
        calibration=Calibration(Decimal("2.1"), Decimal("0.15")),
        output_token_cap=4096,
        ledger_path=path,
        **options,  # type: ignore[arg-type]
    )


def _fail() -> StructuredModelResponse:
    raise RuntimeError("provider failure")


def test_default_core_writes_byte_identical_pre_change_ledger_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    calls = _calls(path)
    calls.run(
        estimated_characters=21_000, invoke=lambda: _RESPONSE, validate=lambda _: None
    )
    with pytest.raises(SpendControlRejected):
        calls.run(estimated_characters=21_000, invoke=_fail, validate=lambda _: None)

    assert path.read_bytes() == PRE_CHANGE_LEDGER.encode("utf-8")


def test_claude_factory_ledger_rows_have_no_extra_fields(tmp_path: Path) -> None:
    developer, user = prompt_for()

    def respond(body: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(VALID_OUTPUT)}],
            "usage": {"input_tokens": 9000, "output_tokens": 10},
        }

    InformedClaudeModel(
        settings=AnthropicGatewaySettings(api_key="test-anthropic-key-not-real"),
        pricing=load_c1_pricing(CLAUDE_PRICING_PATH),
        limits=SpendLimits(max_call_microusd=100_000, max_run_microusd=800_000),
        ledger_path=tmp_path / "claude.jsonl",
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        transport=FakeTransport(respond, url=ANTHROPIC_MESSAGES_URL),
    ).complete(developer_instruction=developer, user_input=user)

    (record,) = ledger(tmp_path, "claude.jsonl")
    assert set(record) == set(json.loads(PRE_CHANGE_LEDGER.splitlines()[0]))
    assert "reasoning_tokens" not in record


def test_worst_case_rate_prices_only_the_pre_call_check_and_failures(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    calls = _calls(path, worst_case_input_microusd_per_million_tokens=2_500_000)
    calls.run(
        estimated_characters=21_000, invoke=lambda: _RESPONSE, validate=lambda _: None
    )
    with pytest.raises(SpendControlRejected):
        calls.run(estimated_characters=21_000, invoke=_fail, validate=lambda _: None)

    success, failure = (json.loads(line) for line in path.read_text().splitlines())
    # 10,000 x 2.50 + 4,096 x 10 = 65,960 micro-USD; success charged at 2 USD input.
    assert success["worst_case_microusd"] == 65_960
    assert success["charged_microusd"] == 7000 * 2 + 300 * 10
    assert failure["charged_microusd"] == 65_960


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"worst_case_input_microusd_per_million_tokens": 1_999_999}, "not below"),
        ({"worst_case_input_microusd_per_million_tokens": True}, "not below"),
        ({"extra_ledger_fields": ("reasoning_tokens",)}, "set together"),
        ({"usage_details": lambda _: {}}, "set together"),
        (
            {"extra_ledger_fields": ("outcome",), "usage_details": lambda _: {}},
            "must not replace",
        ),
        (
            {"extra_ledger_fields": ("a", "a"), "usage_details": lambda _: {}},
            "unique",
        ),
    ],
)
def test_core_options_refuse_unsafe_configuration(
    tmp_path: Path, options: dict[str, object], message: str
) -> None:
    with pytest.raises(SpendControlRejected, match=message):
        _calls(tmp_path / "ledger.jsonl", **options)


@pytest.mark.parametrize(
    "details",
    [
        lambda _: {"reasoning_tokens": -1},
        lambda _: {"reasoning_tokens": True},
        lambda _: {"reasoning_tokens": "prompt text"},
        lambda _: {"other": 1},
        lambda _: (_ for _ in ()).throw(TypeError("boom")),
    ],
    ids=["negative", "bool", "text", "wrong key", "raises"],
)
def test_invalid_usage_details_fail_closed_and_latch(
    tmp_path: Path, details: Callable[[StructuredModelResponse], Mapping[str, object]]
) -> None:
    path = tmp_path / "ledger.jsonl"
    calls = _calls(
        path, extra_ledger_fields=("reasoning_tokens",), usage_details=details
    )

    with pytest.raises(SpendControlRejected, match="invalid_usage_details"):
        calls.run(
            estimated_characters=21_000,
            invoke=lambda: _RESPONSE,
            validate=lambda _: None,
        )
    with pytest.raises(SpendControlRejected, match="closed after an earlier failure"):
        calls.run(
            estimated_characters=21_000,
            invoke=lambda: _RESPONSE,
            validate=lambda _: None,
        )

    (record,) = (json.loads(line) for line in path.read_text().splitlines())
    assert record["failure"] == "invalid_usage_details"
    assert "prompt text" not in path.read_text()
