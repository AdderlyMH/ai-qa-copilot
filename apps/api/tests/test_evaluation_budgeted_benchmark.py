from __future__ import annotations

import json
from decimal import ROUND_CEILING, Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest
import yaml

from ai_qa_copilot_api.evaluation_budgeted_benchmark import (
    BUDGETED_CASE_MAXIMUM_EXPECTED_COST_USD,
    BUDGETED_EVALUATION_CORPUS_SUITE_ID,
    render_budgeted_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationObservation,
    EvaluationRunRejected,
    run_evaluation_cases,
)
from ai_qa_copilot_api.naive_baseline import (
    B0_SIDE_EFFECTS,
    DEFAULT_B0_CONFIG_PATH,
    NaiveBaselineExecutor,
    NaiveBaselineModelResponse,
    load_naive_baseline_config,
)


ROOT = Path(__file__).resolve().parents[3]
V1_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
V2_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v2.yaml"

# Pinned so a v2 change can never silently rewrite the v1 corpus or B1 evidence.
V1_FIXTURE_SHA256 = "25632db0fb444cbdc4c212a0f6bc44efc07b1536aa15e5e6e34eb5876913bd8e"

# Approved budget derivation inputs (USD, verified 2026-10-04).
INPUT_USD_PER_MILLION_TOKENS = Decimal("2")
OUTPUT_USD_PER_MILLION_TOKENS = Decimal("10")
CHARACTERS_PER_TOKEN = Decimal("2.1")
C1_MAX_OUTPUT_TOKENS = 4096
BUDGET_MARGIN = Decimal("1.10")

SMOKE_CASE_IDS = (
    "EVAL-001",
    "EVAL-013",
    "EVAL-025",
    "EVAL-034",
    "EVAL-043",
    "EVAL-049",
    "EVAL-055",
    "EVAL-058",
)


class PromptRecordingModel:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, *, prompt: str) -> NaiveBaselineModelResponse:
        self.prompts.append(prompt)
        return NaiveBaselineModelResponse(
            content=json.dumps(
                {"boundary": "b", "ground_truth_ids": [], "source_references": []}
            ),
            cost=0,
        )


class ZeroCostExecutor:
    def execute(self, case: EvaluationCase) -> EvaluationObservation:
        return EvaluationObservation(
            boundary="analysis_only",
            side_effects=dict(B0_SIDE_EFFECTS),
            ground_truth_ids=(),
            source_references=(),
            cost=0,
        )


def test_committed_v2_fixture_matches_the_deterministic_renderer() -> None:
    assert render_budgeted_evaluation_cases(ROOT) == V2_FIXTURE.read_text(
        encoding="utf-8"
    )


def test_v1_fixture_is_unchanged() -> None:
    assert sha256(V1_FIXTURE.read_bytes()).hexdigest() == V1_FIXTURE_SHA256


def test_v2_differs_from_v1_only_in_suite_id_and_case_budgets() -> None:
    v1 = cast(dict[str, object], yaml.safe_load(V1_FIXTURE.read_text("utf-8")))
    v2 = cast(dict[str, object], yaml.safe_load(V2_FIXTURE.read_text("utf-8")))

    assert v1["suite_id"] == "evaluation-corpus/v1"
    assert v2["suite_id"] == BUDGETED_EVALUATION_CORPUS_SUITE_ID

    v1_cases = cast(list[dict[str, dict[str, object]]], v1["cases"])
    v2_cases = cast(list[dict[str, dict[str, object]]], v2["cases"])
    assert len(v1_cases) == len(v2_cases) == 100
    for v1_case, v2_case in zip(v1_cases, v2_cases, strict=True):
        assert v1_case["expected"]["maximum_expected_cost"] == 0
        assert (
            v2_case["expected"]["maximum_expected_cost"]
            == BUDGETED_CASE_MAXIMUM_EXPECTED_COST_USD
        )
        v2_case["expected"]["maximum_expected_cost"] = 0
        assert v2_case == v1_case

    v2["suite_id"] = v1["suite_id"]
    assert v2 == v1


def test_v2_loads_with_the_approved_budget_on_every_case() -> None:
    suite = load_evaluation_case_suite(V2_FIXTURE)

    assert suite.suite_id == BUDGETED_EVALUATION_CORPUS_SUITE_ID
    assert {case.expected.maximum_expected_cost for case in suite.cases} == {0.09}


def test_budget_is_the_rounded_up_worst_case_plus_ten_percent() -> None:
    suite = load_evaluation_case_suite(V2_FIXTURE)
    model = PromptRecordingModel()
    executor = NaiveBaselineExecutor(
        configuration=load_naive_baseline_config(ROOT / DEFAULT_B0_CONFIG_PATH),
        repository_root=ROOT,
        model=model,
    )
    for case in suite.cases:
        executor.execute(case)

    largest_prompt_characters = max(len(prompt) for prompt in model.prompts)
    input_tokens = (
        Decimal(largest_prompt_characters) / CHARACTERS_PER_TOKEN
    ).to_integral_value(rounding=ROUND_CEILING)
    worst_case_usd = (
        input_tokens * INPUT_USD_PER_MILLION_TOKENS
        + C1_MAX_OUTPUT_TOKENS * OUTPUT_USD_PER_MILLION_TOKENS
    ) / Decimal(1_000_000)
    budget = (worst_case_usd * BUDGET_MARGIN).quantize(
        Decimal("0.01"), rounding=ROUND_CEILING
    )

    assert len(model.prompts) == 100
    assert largest_prompt_characters == 38_713
    assert input_tokens == 18_435
    assert worst_case_usd == Decimal("0.07783")
    assert budget == Decimal(str(BUDGETED_CASE_MAXIMUM_EXPECTED_COST_USD))


@pytest.mark.parametrize(
    ("case_ids", "splits", "exact_cap"),
    [
        (SMOKE_CASE_IDS, ("development",), 0.72),
        (None, ("development",), 5.40),
        (None, None, 9.00),
    ],
)
def test_runner_budget_preflight_accepts_exact_cap_and_rejects_one_cent_less(
    case_ids: tuple[str, ...] | None,
    splits: tuple[str, ...] | None,
    exact_cap: float,
) -> None:
    suite = load_evaluation_case_suite(V2_FIXTURE)

    with pytest.raises(EvaluationRunRejected, match="expected-cost budget"):
        run_evaluation_cases(
            suite,
            fixture_path=V2_FIXTURE,
            repository_root=ROOT,
            executor=ZeroCostExecutor(),
            case_ids=case_ids,
            splits=splits,
            max_expected_cost=round(exact_cap - 0.01, 2),
        )

    report = run_evaluation_cases(
        suite,
        fixture_path=V2_FIXTURE,
        repository_root=ROOT,
        executor=ZeroCostExecutor(),
        case_ids=case_ids,
        splits=splits,
        max_expected_cost=exact_cap,
    )
    assert report.suite_id == BUDGETED_EVALUATION_CORPUS_SUITE_ID
    assert len(report.results) == round(exact_cap / 0.09)
