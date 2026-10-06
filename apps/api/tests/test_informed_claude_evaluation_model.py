from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import cast

import pytest

from ai_qa_copilot_api.c1_evaluation_model import load_c1_pricing
from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_runner import run_evaluation_cases
from ai_qa_copilot_api.evaluation_spend_control import (
    Calibration,
    SpendControlRejected,
    SpendLimits,
    cost_microusd,
    estimate_input_tokens,
)
from ai_qa_copilot_api.informed_baseline import (
    DEFAULT_INFORMED_CONFIG_PATH,
    INFORMED_CONFIG_PATH_ENVIRONMENT_VARIABLE,
    INFORMED_MODEL_FACTORY_ENVIRONMENT_VARIABLE,
    INFORMED_REPOSITORY_ROOT_ENVIRONMENT_VARIABLE,
    InformedBaselineExecutor,
    InformedBaselineRejected,
    InformedModelResponse,
    create_informed_baseline_executor,
    load_informed_baseline_config,
)
from ai_qa_copilot_api.informed_claude_evaluation_model import (
    CLAUDE_INFORMED_CALIBRATION,
    INFORMED_LEDGER_PATH_ENVIRONMENT_VARIABLE,
    INFORMED_MAX_CALL_COST_ENVIRONMENT_VARIABLE,
    INFORMED_MAX_RUN_COST_ENVIRONMENT_VARIABLE,
    INFORMED_PRICING_PATH_ENVIRONMENT_VARIABLE,
    InformedClaudeModel,
    informed_claude_model_from_mapping,
)
from ai_qa_copilot_api.model_gateway import (
    ANTHROPIC_MESSAGES_URL,
    C1_MAX_TOKENS,
    C1_MODEL_ID,
    AnthropicGatewaySettings,
)


ROOT = Path(__file__).resolve().parents[3]
PRICING_PATH = ROOT / "fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml"
V3_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v3.yaml"
CONFIG_PATH = ROOT / DEFAULT_INFORMED_CONFIG_PATH
API_KEY = "test-anthropic-key-not-real"
VALID_OUTPUT = {
    "boundary": "analysis_only",
    "ground_truth_ids": ["GT-FIND-001"],
    "source_references": ["REQ-BASE-001#REQ-ORDER-004#statement"],
}
LIMIT_CALL = 100_000
LIMIT_RUN = 800_000


def anthropic_payload(
    *,
    input_tokens: int,
    output_tokens: int = 200,
    stop_reason: str = "end_turn",
    output: Mapping[str, object] = VALID_OUTPUT,
    usage_extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": C1_MODEL_ID,
        "stop_reason": stop_reason,
        "content": [{"type": "text", "text": json.dumps(dict(output))}],
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            **(usage_extra or {}),
        },
    }


def request_characters(body: Mapping[str, object]) -> int:
    messages = cast(list[dict[str, list[dict[str, str]]]], body["messages"])
    output_config = cast(dict[str, dict[str, object]], body["output_config"])
    schema = json.dumps(output_config["format"]["schema"], separators=(",", ":"))
    return (
        len(cast(str, body["system"]))
        + len(messages[0]["content"][0]["text"])
        + len(schema)
    )


def exact_input_tokens(body: Mapping[str, object], scale: Decimal = Decimal(1)) -> int:
    estimate = estimate_input_tokens(
        request_characters(body), CLAUDE_INFORMED_CALIBRATION
    )
    return int((Decimal(estimate) * scale).to_integral_value(rounding=ROUND_CEILING))


class FakeTransport:
    def __init__(
        self, respond: Callable[[Mapping[str, object]], Mapping[str, object]]
    ) -> None:
        self._respond = respond
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
        assert url == ANTHROPIC_MESSAGES_URL
        self.bodies.append(body)
        self.headers.append(headers)
        return self._respond(body)


def estimate_transport(
    *,
    scale: Decimal = Decimal(1),
    output_tokens: int = 200,
    stop_reason: str = "end_turn",
    output: Mapping[str, object] = VALID_OUTPUT,
    usage_extra: Mapping[str, object] | None = None,
) -> FakeTransport:
    return FakeTransport(
        lambda body: anthropic_payload(
            input_tokens=exact_input_tokens(body, scale),
            output_tokens=output_tokens,
            stop_reason=stop_reason,
            output=output,
            usage_extra=usage_extra,
        )
    )


def make_model(
    tmp_path: Path,
    transport: FakeTransport,
    *,
    max_call: int = LIMIT_CALL,
    max_run: int = LIMIT_RUN,
) -> InformedClaudeModel:
    return InformedClaudeModel(
        settings=AnthropicGatewaySettings(api_key=API_KEY),
        pricing=load_c1_pricing(PRICING_PATH),
        limits=SpendLimits(max_call_microusd=max_call, max_run_microusd=max_run),
        ledger_path=tmp_path / "informed-ledger.jsonl",
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        transport=transport,
    )


def ledger(tmp_path: Path) -> list[dict[str, object]]:
    text = (tmp_path / "informed-ledger.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def a_case(case_id: str = "EVAL-001") -> EvaluationCase:
    return next(
        c for c in load_evaluation_case_suite(V3_FIXTURE).cases if c.id == case_id
    )


def prompt_for(case_id: str = "EVAL-001") -> tuple[str, str]:
    class Unused:
        def complete(self, **_: str) -> InformedModelResponse:
            raise AssertionError

    executor = InformedBaselineExecutor(
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        model=Unused(),
    )
    prompt = executor.build_prompt(a_case(case_id))
    return prompt.developer_instruction, prompt.user_input


def worst_case_microusd(case_id: str = "EVAL-001") -> int:
    developer, user = prompt_for(case_id)
    schema = InformedBaselineExecutor(
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        model=cast(object, None),  # type: ignore[arg-type]
    ).output_schema
    characters = (
        len(developer) + len(user) + len(json.dumps(schema, separators=(",", ":")))
    )
    return cost_microusd(
        load_c1_pricing(PRICING_PATH),
        input_tokens=estimate_input_tokens(characters, CLAUDE_INFORMED_CALIBRATION),
        output_tokens=C1_MAX_TOKENS,
    )


def test_request_shape_is_the_pinned_c1_request_with_the_shared_schema(
    tmp_path: Path,
) -> None:
    transport = estimate_transport()
    developer, user = prompt_for()
    model = make_model(tmp_path, transport)

    response = model.complete(developer_instruction=developer, user_input=user)

    body = transport.bodies[0]
    executor_schema = InformedBaselineExecutor(
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        model=cast(object, None),  # type: ignore[arg-type]
    ).output_schema
    assert set(body) == {"model", "max_tokens", "system", "messages", "output_config"}
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 4096
    assert body["system"] == developer
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": user}]}
    ]
    assert body["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": executor_schema},
    }
    # Keys only: the prompt prose legitimately mentions "tools".
    output_config = cast(dict[str, object], body["output_config"])
    assert set(output_config) == {"effort", "format"}
    for forbidden in (
        "inference_geo",
        "tools",
        "tool_choice",
        "cache_control",
        "stream",
        "thinking",
    ):
        assert forbidden not in body
    assert transport.headers[0]["x-api-key"] == API_KEY
    assert json.loads(response.content) == VALID_OUTPUT
    assert response.cost > 0


def test_success_writes_one_content_free_ledger_record(tmp_path: Path) -> None:
    transport = estimate_transport(scale=Decimal("0.7"))
    developer, user = prompt_for()
    make_model(tmp_path, transport).complete(
        developer_instruction=developer, user_input=user
    )

    (record,) = ledger(tmp_path)
    assert record["schema_version"] == "informed-call-ledger/v1"
    assert record["provider"] == "anthropic"
    assert record["model_id"] == "claude-sonnet-5-5"
    assert record["configuration_version"] == "C1/v1"
    assert record["prompt_version"] == "informed-single-prompt/v1"
    assert record["outcome"] == "succeeded"
    assert record["failure"] is None
    assert record["calibration_ratio"] == pytest.approx(0.7, abs=0.001)
    assert record["characters_per_token"] == "2.1"
    assert record["tolerance"] == "0.15"
    assert record["max_call_microusd"] == LIMIT_CALL
    assert record["max_run_microusd"] == LIMIT_RUN
    assert cast(int, record["charged_microusd"]) <= cast(
        int, record["worst_case_microusd"]
    )


def test_ledger_holds_no_prompt_output_or_credential(tmp_path: Path) -> None:
    transport = estimate_transport()
    developer, user = prompt_for()
    model = make_model(tmp_path, transport)
    model.complete(developer_instruction=developer, user_input=user)
    transport_failure = estimate_transport(stop_reason="refusal")
    with pytest.raises(SpendControlRejected):
        make_model_second(tmp_path, transport_failure).complete(
            developer_instruction=developer, user_input=user
        )

    raw = (tmp_path / "informed-ledger.jsonl").read_text(encoding="utf-8") + (
        tmp_path / "second-ledger.jsonl"
    ).read_text(encoding="utf-8")
    for secret in (
        API_KEY,
        "GT-FIND-001",
        "REQ-ORDER-004",
        "You are a QA analyst",
        user[:60],
        "analysis_only",
    ):
        assert secret not in raw


def make_model_second(tmp_path: Path, transport: FakeTransport) -> InformedClaudeModel:
    return InformedClaudeModel(
        settings=AnthropicGatewaySettings(api_key=API_KEY),
        pricing=load_c1_pricing(PRICING_PATH),
        limits=SpendLimits(max_call_microusd=LIMIT_CALL, max_run_microusd=LIMIT_RUN),
        ledger_path=tmp_path / "second-ledger.jsonl",
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        transport=transport,
    )


def test_refusal_latches_charges_worst_case_and_blocks_later_calls(
    tmp_path: Path,
) -> None:
    transport = estimate_transport(stop_reason="refusal")
    developer, user = prompt_for()
    model = make_model(tmp_path, transport)

    with pytest.raises(SpendControlRejected, match="provider_call_failed"):
        model.complete(developer_instruction=developer, user_input=user)
    with pytest.raises(SpendControlRejected, match="closed after an earlier failure"):
        model.complete(developer_instruction=developer, user_input=user)

    assert len(transport.bodies) == 1
    first, second = ledger(tmp_path)[0], ledger(tmp_path)
    assert first["outcome"] == "failed"
    assert str(first["failure"]).startswith("provider_call_failed:ModelGatewayRefusal")
    assert first["charged_microusd"] == first["worst_case_microusd"]
    assert len(second) == 1


def test_truncation_fails_closed(tmp_path: Path) -> None:
    transport = estimate_transport(stop_reason="max_tokens", output_tokens=4096)
    developer, user = prompt_for()
    model = make_model(tmp_path, transport)

    with pytest.raises(SpendControlRejected, match="ModelGatewayTruncated"):
        model.complete(developer_instruction=developer, user_input=user)

    assert (
        ledger(tmp_path)[0]["failure"] == "provider_call_failed:ModelGatewayTruncated"
    )


def test_nonzero_cache_tokens_fail_closed(tmp_path: Path) -> None:
    transport = estimate_transport(usage_extra={"cache_read_input_tokens": 5})
    developer, user = prompt_for()

    with pytest.raises(SpendControlRejected, match="ModelGatewayProtocolError"):
        make_model(tmp_path, transport).complete(
            developer_instruction=developer, user_input=user
        )


def test_calibration_accepts_exactly_fifteen_percent_over_and_rejects_more(
    tmp_path: Path,
) -> None:
    developer, user = prompt_for()

    def boundary_transport(extra_tokens: int) -> FakeTransport:
        def respond(body: Mapping[str, object]) -> Mapping[str, object]:
            estimate = estimate_input_tokens(
                request_characters(body), CLAUDE_INFORMED_CALIBRATION
            )
            limit = int(Decimal(estimate) * Decimal("1.15"))  # floor
            return anthropic_payload(input_tokens=limit + extra_tokens)

        return FakeTransport(respond)

    at_limit = make_model(tmp_path, boundary_transport(0))
    at_limit.complete(developer_instruction=developer, user_input=user)

    over_dir = tmp_path / "over"
    over_dir.mkdir()
    over = make_model(over_dir, boundary_transport(1))
    with pytest.raises(SpendControlRejected, match="input_token_estimate_exceeded"):
        over.complete(developer_instruction=developer, user_input=user)
    with pytest.raises(SpendControlRejected, match="closed after an earlier failure"):
        over.complete(developer_instruction=developer, user_input=user)
    assert ledger(over_dir)[0]["outcome"] == "failed"


def test_calibration_is_a_per_provider_value() -> None:
    assert CLAUDE_INFORMED_CALIBRATION == Calibration(Decimal("2.1"), Decimal("0.15"))
    with pytest.raises(SpendControlRejected):
        Calibration(Decimal("0"), Decimal("0.15"))


def test_per_call_limit_blocks_before_any_request(tmp_path: Path) -> None:
    transport = estimate_transport()
    developer, user = prompt_for()
    model = make_model(tmp_path, transport, max_call=worst_case_microusd() - 1)

    with pytest.raises(SpendControlRejected, match="worst_case_exceeds_call_limit"):
        model.complete(developer_instruction=developer, user_input=user)

    assert transport.bodies == []
    assert ledger(tmp_path)[0]["charged_microusd"] == 0


def test_exact_per_call_limit_is_accepted(tmp_path: Path) -> None:
    transport = estimate_transport()
    developer, user = prompt_for()
    model = make_model(tmp_path, transport, max_call=worst_case_microusd())

    model.complete(developer_instruction=developer, user_input=user)

    assert len(transport.bodies) == 1


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
    assert model.running_total_microusd == cast(
        int, ledger(tmp_path)[0]["charged_microusd"]
    )


def test_run_limit_exceeded_after_a_call_latches(tmp_path: Path) -> None:
    developer, user = prompt_for()
    worst = worst_case_microusd()
    # Worst case just fits, but the real call costs more than the run limit allows.
    transport = estimate_transport(scale=Decimal("1.15"), output_tokens=4096)
    model = make_model(tmp_path, transport, max_call=worst, max_run=worst)

    with pytest.raises(SpendControlRejected, match="run_limit_exceeded_after_call"):
        model.complete(developer_instruction=developer, user_input=user)


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
    assert ledger(tmp_path)[0]["failure"] == "invalid_output"


def test_overlapping_calls_are_rejected_and_close_the_model(tmp_path: Path) -> None:
    developer, user = prompt_for()
    entered = threading.Event()
    release = threading.Event()

    def respond(body: Mapping[str, object]) -> Mapping[str, object]:
        entered.set()
        assert release.wait(timeout=10)
        return anthropic_payload(input_tokens=exact_input_tokens(body))

    transport = FakeTransport(respond)
    model = make_model(tmp_path, transport)
    results: list[object] = []
    thread = threading.Thread(
        target=lambda: results.append(
            model.complete(developer_instruction=developer, user_input=user)
        )
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


def test_executor_runs_two_cases_through_the_model_serially(tmp_path: Path) -> None:
    transport = estimate_transport(scale=Decimal("0.7"))
    model = make_model(tmp_path, transport)
    executor = InformedBaselineExecutor(
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        model=model,
    )
    suite = load_evaluation_case_suite(V3_FIXTURE)

    run = run_evaluation_cases(
        suite,
        executor=executor,
        fixture_path=V3_FIXTURE,
        repository_root=ROOT,
        case_ids=("EVAL-001", "EVAL-002"),
        max_expected_cost=0.20,
        max_concurrency=1,
    )

    assert [r.case_id for r in run.results] == ["EVAL-001", "EVAL-002"]
    assert [r["call_index"] for r in ledger(tmp_path)] == [1, 2]
    assert model.running_total_microusd == sum(
        cast(int, r["charged_microusd"]) for r in ledger(tmp_path)
    )


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "ANTHROPIC_API_KEY": API_KEY,
        INFORMED_PRICING_PATH_ENVIRONMENT_VARIABLE: str(PRICING_PATH),
        INFORMED_MAX_CALL_COST_ENVIRONMENT_VARIABLE: "0.10",
        INFORMED_MAX_RUN_COST_ENVIRONMENT_VARIABLE: "0.80",
        INFORMED_LEDGER_PATH_ENVIRONMENT_VARIABLE: str(tmp_path / "ledger.jsonl"),
        INFORMED_CONFIG_PATH_ENVIRONMENT_VARIABLE: str(CONFIG_PATH),
        INFORMED_REPOSITORY_ROOT_ENVIRONMENT_VARIABLE: str(ROOT),
    }


def test_factory_reads_only_explicit_environment(tmp_path: Path) -> None:
    model = informed_claude_model_from_mapping(
        _environment(tmp_path), transport=estimate_transport()
    )

    assert model.running_total_microusd == 0
    assert (tmp_path / "ledger.jsonl").is_file()


@pytest.mark.parametrize(
    "missing",
    [
        "ANTHROPIC_API_KEY",
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
        informed_claude_model_from_mapping(environment, transport=estimate_transport())


def test_factory_refuses_a_per_call_limit_above_the_run_limit(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment[INFORMED_MAX_CALL_COST_ENVIRONMENT_VARIABLE] = "0.90"

    with pytest.raises(SpendControlRejected, match="cannot exceed the run limit"):
        informed_claude_model_from_mapping(environment, transport=estimate_transport())


def test_cli_executor_factory_loads_the_model_factory_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in _environment(tmp_path).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(
        INFORMED_MODEL_FACTORY_ENVIRONMENT_VARIABLE,
        "ai_qa_copilot_api.informed_claude_evaluation_model:create_informed_claude_model",
    )

    executor = create_informed_baseline_executor()

    assert isinstance(executor, InformedBaselineExecutor)
    assert (tmp_path / "ledger.jsonl").is_file()


def test_cli_executor_factory_requires_a_model_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(INFORMED_MODEL_FACTORY_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setenv(INFORMED_REPOSITORY_ROOT_ENVIRONMENT_VARIABLE, str(ROOT))

    with pytest.raises(
        InformedBaselineRejected, match="must be set to module:attribute"
    ):
        create_informed_baseline_executor()
