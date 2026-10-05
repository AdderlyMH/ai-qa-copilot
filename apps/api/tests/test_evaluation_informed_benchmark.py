from __future__ import annotations

import json
import re
from decimal import ROUND_CEILING, Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest
import yaml

from ai_qa_copilot_api.evaluation_budgeted_benchmark import (
    render_budgeted_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_informed_benchmark import (
    INFORMED_CASE_MAXIMUM_EXPECTED_COST_USD,
    INFORMED_EVALUATION_CORPUS_SUITE_ID,
    EvaluationInformedBenchmarkRejected,
    normalize_source_reference,
    render_informed_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_release_benchmark import (
    render_complete_evaluation_cases,
)
from ai_qa_copilot_api.informed_baseline import (
    DEFAULT_INFORMED_CONFIG_PATH,
    OPENAPI_REFERENCE_PATTERN,
    REQUIREMENT_REFERENCE_PATTERN,
    SCHEMA_REFERENCE_PATTERN,
    InformedBaselineExecutor,
    InformedModelResponse,
    load_informed_baseline_config,
)


ROOT = Path(__file__).resolve().parents[3]
V1_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
V2_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v2.yaml"
V3_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v3.yaml"

# Pinned so v3 work can never silently rewrite v1 (bound to B1 evidence) or v2.
V1_FIXTURE_SHA256 = "25632db0fb444cbdc4c212a0f6bc44efc07b1536aa15e5e6e34eb5876913bd8e"
V2_FIXTURE_SHA256 = "364e51bc009729c35d252c6c26d7a634b1edeecf07e70b53b9786a65ed7a25dc"

# Budget derivation inputs (USD per million tokens, verified 2026-10-05).
INPUT_USD_PER_MILLION_TOKENS = Decimal("2")
OUTPUT_USD_PER_MILLION_TOKENS = Decimal("10")
CHARACTERS_PER_TOKEN = Decimal("2.1")
OUTPUT_TOKEN_CAP = 4096
BUDGET_MARGIN = Decimal("1.10")
CALIBRATION_TOLERANCE = Decimal("0.15")

Case = dict[str, dict[str, object]]


class UnusedModel:
    def complete(
        self, *, developer_instruction: str, user_input: str
    ) -> InformedModelResponse:
        raise AssertionError("budget derivation must not call a model")


def _load(path: Path) -> dict[str, object]:
    return cast(dict[str, object], yaml.safe_load(path.read_text(encoding="utf-8")))


def _cases(corpus: dict[str, object]) -> list[Case]:
    return cast(list[Case], corpus["cases"])


def _references(corpus: dict[str, object]) -> list[str]:
    return [
        reference
        for case in _cases(corpus)
        for reference in cast(list[str], case["expected"]["expected_source_references"])
    ]


def test_v1_and_v2_fixture_bytes_are_pinned() -> None:
    assert sha256(V1_FIXTURE.read_bytes()).hexdigest() == V1_FIXTURE_SHA256
    assert sha256(V2_FIXTURE.read_bytes()).hexdigest() == V2_FIXTURE_SHA256


def test_v1_and_v2_renderers_still_produce_the_committed_bytes() -> None:
    assert render_complete_evaluation_cases(ROOT) == V1_FIXTURE.read_text(
        encoding="utf-8"
    )
    assert render_budgeted_evaluation_cases(ROOT) == V2_FIXTURE.read_text(
        encoding="utf-8"
    )


def test_committed_v3_fixture_matches_the_deterministic_renderer() -> None:
    assert render_informed_evaluation_cases(ROOT) == V3_FIXTURE.read_text(
        encoding="utf-8"
    )


def test_v2_still_contains_the_defects_that_v3_repairs() -> None:
    references = _references(_load(V2_FIXTURE))

    assert sum("OAS-BASE-001##" in reference for reference in references) == 45
    assert sum(":statement" in reference for reference in references) == 3
    assert (
        sum("OAS-BASE-001#OAS-BASE-001#" in reference for reference in references) == 1
    )


def test_v3_differs_from_v2_only_in_suite_id_references_and_budget() -> None:
    v2 = _load(V2_FIXTURE)
    v3 = _load(V3_FIXTURE)

    assert v2["suite_id"] == "evaluation-corpus/v2"
    assert v3["suite_id"] == INFORMED_EVALUATION_CORPUS_SUITE_ID
    assert len(_cases(v2)) == len(_cases(v3)) == 100

    changed_references = 0
    for v2_case, v3_case in zip(_cases(v2), _cases(v3), strict=True):
        assert v2_case["expected"]["maximum_expected_cost"] == 0.09
        assert (
            v3_case["expected"]["maximum_expected_cost"]
            == INFORMED_CASE_MAXIMUM_EXPECTED_COST_USD
        )
        v2_references = cast(
            list[str], v2_case["expected"]["expected_source_references"]
        )
        v3_references = cast(
            list[str], v3_case["expected"]["expected_source_references"]
        )
        changed_references += sum(
            old != new for old, new in zip(v2_references, v3_references, strict=True)
        )

        # Restore the three differing fields; everything else must be identical.
        v3_case["expected"]["expected_source_references"] = v2_references
        v3_case["expected"]["maximum_expected_cost"] = 0.09
        assert v3_case == v2_case

    assert changed_references > 0
    v3["suite_id"] = v2["suite_id"]
    assert v3 == v2


def test_v3_references_use_the_hash_form_everywhere() -> None:
    references = _references(_load(V3_FIXTURE))
    requirement = re.compile(REQUIREMENT_REFERENCE_PATTERN)
    openapi = re.compile(OPENAPI_REFERENCE_PATTERN)
    shared = re.compile(SCHEMA_REFERENCE_PATTERN)

    assert references
    for reference in references:
        assert "##" not in reference
        assert "OAS-BASE-001#OAS-BASE-001" not in reference
        assert "REQ-BASE-001#REQ-BASE-001" not in reference
        if reference.startswith("REQ-BASE-001#"):
            assert ":" not in reference
            assert requirement.fullmatch(reference)
        else:
            # A colon is legitimate only in the absence assertion's keyword.
            assert reference.replace("#absence:", "#absence-").count(":") == 0
            assert openapi.fullmatch(reference)
        assert shared.fullmatch(reference)


def test_the_three_colon_cases_use_the_hash_form_in_v3() -> None:
    cases = {case_id: case for case_id, case in _case_index(_load(V3_FIXTURE)).items()}

    for case_id in ("EVAL-001", "EVAL-061", "EVAL-081"):
        assert cases[case_id]["expected"]["expected_source_references"] == [
            "REQ-BASE-001#REQ-ORDER-004#statement"
        ]


def _case_index(corpus: dict[str, object]) -> dict[str, Case]:
    return {cast(str, case["id"]): case for case in _cases(corpus)}


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (
            "REQ-BASE-001#REQ-ORDER-004:statement",
            "REQ-BASE-001#REQ-ORDER-004#statement",
        ),
        ("REQ-BASE-001#REQ-REFUND-001#AC-5", "REQ-BASE-001#REQ-REFUND-001#AC-5"),
        (
            "OAS-BASE-001##/paths/~1orders/get/security",
            "OAS-BASE-001#/paths/~1orders/get/security",
        ),
        (
            "OAS-BASE-001#OAS-BASE-001#absence:X-Correlation-ID",
            "OAS-BASE-001#absence:X-Correlation-ID",
        ),
        (
            "OAS-BASE-001#absence:X-Correlation-ID",
            "OAS-BASE-001#absence:X-Correlation-ID",
        ),
    ],
)
def test_normalization_repairs_known_defects_and_keeps_good_references(
    reference: str, expected: str
) -> None:
    assert normalize_source_reference(reference) == expected


@pytest.mark.parametrize(
    "reference",
    ["", "statement", "REQ-BASE-001#statement", "OAS-OTHER#/paths", "REQ-BASE-001:x#y"],
)
def test_normalization_refuses_references_it_cannot_repair(reference: str) -> None:
    with pytest.raises(EvaluationInformedBenchmarkRejected):
        normalize_source_reference(reference)


def test_v3_loads_with_the_approved_budget_and_split_counts() -> None:
    suite = load_evaluation_case_suite(V3_FIXTURE)

    assert suite.suite_id == INFORMED_EVALUATION_CORPUS_SUITE_ID
    assert {case.expected.maximum_expected_cost for case in suite.cases} == {0.10}
    assert {
        split: sum(case.split == split for case in suite.cases)
        for split in ("development", "validation", "holdout")
    } == {"development": 60, "validation": 20, "holdout": 20}


def test_budget_is_the_rounded_up_worst_case_plus_ten_percent() -> None:
    suite = load_evaluation_case_suite(V3_FIXTURE)
    executor = InformedBaselineExecutor(
        configuration=load_informed_baseline_config(
            ROOT / DEFAULT_INFORMED_CONFIG_PATH
        ),
        repository_root=ROOT,
        model=UnusedModel(),
    )
    schema_characters = len(json.dumps(executor.output_schema, separators=(",", ":")))
    largest_characters = max(
        executor.build_prompt(case).characters + schema_characters
        for case in suite.cases
    )

    input_tokens = int(
        (Decimal(largest_characters) / CHARACTERS_PER_TOKEN).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    worst_case = (
        Decimal(input_tokens) * INPUT_USD_PER_MILLION_TOKENS
        + Decimal(OUTPUT_TOKEN_CAP) * OUTPUT_USD_PER_MILLION_TOKENS
    ) / Decimal(1_000_000)
    budget = (worst_case * BUDGET_MARGIN * 100).to_integral_value(
        rounding=ROUND_CEILING
    ) / 100

    assert (largest_characters, input_tokens) == (43_197, 20_570)
    assert worst_case == Decimal("0.08210")
    assert budget == Decimal("0.10")
    assert float(budget) == INFORMED_CASE_MAXIMUM_EXPECTED_COST_USD

    # One cent lower would not cover the margin, and the calibration tolerance
    # (input 15 percent over the estimate) still fits under the budget.
    assert worst_case * BUDGET_MARGIN > Decimal("0.09")
    over_estimate = (
        Decimal(input_tokens)
        * (1 + CALIBRATION_TOLERANCE)
        * INPUT_USD_PER_MILLION_TOKENS
        + Decimal(OUTPUT_TOKEN_CAP) * OUTPUT_USD_PER_MILLION_TOKENS
    ) / Decimal(1_000_000)
    assert over_estimate <= budget


def test_generator_accepts_the_v3_corpus_option() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_evaluation_cases", ROOT / "scripts/generate_evaluation_cases.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    renderer, output = module.CORPUS_RENDERERS["v3"]
    assert renderer is render_informed_evaluation_cases
    assert output == V3_FIXTURE
