"""Deterministically derive the budgeted v2 corpus from the v1 benchmark corpus.

The v2 corpus is the v1 corpus with a new suite identifier and one approved,
nonzero USD ``maximum_expected_cost`` per case. Every other case field is
identical, so v1 (and any B1 evidence bound to it) stays unchanged.

Per-case budget derivation (approved 2026-10-04):

- Pricing: Claude Sonnet 5.5, 2 USD input and 10 USD output per million
  tokens, from https://platform.claude.com/docs/en/about-claude/pricing,
  verified 2026-10-04.
- Most expensive case: the largest B0 single-prompt request, 38,713 characters,
  estimated at 2.1 characters per token (18,435 input tokens), plus the C1/v1
  ``max_tokens`` limit of 4,096 output tokens.
- Worst case 0.07783 USD, plus 10 percent, rounded up to the cent: 0.09 USD.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Final, cast

import yaml

from ai_qa_copilot_api.evaluation_release_benchmark import (
    build_complete_evaluation_cases,
)


BUDGETED_EVALUATION_CORPUS_SUITE_ID: Final = "evaluation-corpus/v2"
BUDGETED_CASE_MAXIMUM_EXPECTED_COST_USD: Final = 0.09


class EvaluationBudgetedBenchmarkRejected(ValueError):
    """Raised when the budgeted corpus cannot be derived safely."""


def render_budgeted_evaluation_cases(repository_root: Path) -> str:
    """Render the budgeted 100-case corpus with the v1 YAML conventions."""

    return yaml.safe_dump(
        build_budgeted_evaluation_cases(repository_root),
        sort_keys=False,
        allow_unicode=False,
    )


def build_budgeted_evaluation_cases(repository_root: Path) -> dict[str, object]:
    """Copy the v1 corpus, changing only the suite ID and per-case budgets."""

    corpus = deepcopy(build_complete_evaluation_cases(repository_root))
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationBudgetedBenchmarkRejected("v1 corpus must contain cases")

    for case in cast(list[object], cases):
        if not isinstance(case, dict):
            raise EvaluationBudgetedBenchmarkRejected("v1 case must be a mapping")
        expected = cast(Mapping[str, object], case).get("expected")
        if not isinstance(expected, dict) or "maximum_expected_cost" not in expected:
            raise EvaluationBudgetedBenchmarkRejected(
                "v1 case must declare expected.maximum_expected_cost"
            )
        cast(dict[str, object], expected)["maximum_expected_cost"] = (
            BUDGETED_CASE_MAXIMUM_EXPECTED_COST_USD
        )

    corpus["suite_id"] = BUDGETED_EVALUATION_CORPUS_SUITE_ID
    return corpus
