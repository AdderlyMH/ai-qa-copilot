"""Fail-closed preflight contracts for evaluation GitHub Actions workflows."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    EvaluationCaseSuite,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_development_benchmark import (
    DEVELOPMENT_CATEGORY_TARGETS,
)
from ai_qa_copilot_api.evaluation_release_benchmark import (
    EVALUATION_CORPUS_SUITE_ID,
    RELEASE_SPLIT_CATEGORY_TARGETS,
)
from ai_qa_copilot_api.evaluation_release_review_selection import (
    load_release_review_selection,
)
from ai_qa_copilot_api.evaluation_scoring import load_ground_truth_catalog
from ai_qa_copilot_api.naive_baseline import load_naive_baseline_config


CASE_FIXTURE_RELATIVE_PATH: Final = Path("fixtures/benchmark/evaluation-cases.v1.yaml")
GROUND_TRUTH_RELATIVE_PATH: Final = Path("fixtures/benchmark/ground-truth.v1.yaml")
B0_CONFIG_RELATIVE_PATH: Final = Path(
    "fixtures/benchmark/baselines/b0-naive-single-prompt.v1.yaml"
)
DEFAULT_RELEASE_REVIEW_MANIFEST_RELATIVE_PATH: Final = Path(
    "evaluation/reviews/release-review-manifest.v1.yaml"
)

SMOKE_CASE_IDS: Final = (
    "EVAL-001",
    "EVAL-013",
    "EVAL-025",
    "EVAL-034",
    "EVAL-043",
    "EVAL-049",
    "EVAL-055",
    "EVAL-058",
)


class EvaluationWorkflowContractRejected(ValueError):
    """Raised when a workflow lacks required immutable evaluation evidence."""


@dataclass(frozen=True)
class EvaluationWorkflowPreflight:
    """Validated non-secret metadata for one workflow invocation."""

    mode: str
    suite_id: str
    selected_case_ids: tuple[str, ...]
    declared_expected_cost: int | float


def verify_smoke_workflow_preflight(
    repository_root: Path,
    *,
    baseline_executor: str,
    grounded_executor: str,
    require_positive_case_budgets: bool = False,
) -> EvaluationWorkflowPreflight:
    """Verify the fixed representative development smoke selection."""

    suite = _load_complete_suite(repository_root)
    _load_shared_evidence(repository_root)
    _validate_executor_specification(baseline_executor, "baseline executor")
    _validate_executor_specification(grounded_executor, "grounded executor")

    cases_by_id = {case.id: case for case in suite.cases}
    try:
        selected_cases = tuple(cases_by_id[case_id] for case_id in SMOKE_CASE_IDS)
    except KeyError as error:
        raise EvaluationWorkflowContractRejected(
            f"Smoke case is missing from the corpus: {error.args[0]}"
        ) from error

    if any(case.split != "development" for case in selected_cases):
        raise EvaluationWorkflowContractRejected(
            "Smoke selection must contain only development cases"
        )

    if len(selected_cases) < 5 or len(selected_cases) > 10:
        raise EvaluationWorkflowContractRejected(
            "Smoke selection must contain between 5 and 10 cases"
        )

    categories = {case.category for case in selected_cases}
    if len(categories) != len(selected_cases):
        raise EvaluationWorkflowContractRejected(
            "Smoke selection must represent distinct benchmark categories"
        )

    declared_expected_cost = _declared_expected_cost(selected_cases)
    _require_positive_case_budgets(
        selected_cases,
        required=require_positive_case_budgets,
    )

    return EvaluationWorkflowPreflight(
        mode="smoke",
        suite_id=suite.suite_id,
        selected_case_ids=SMOKE_CASE_IDS,
        declared_expected_cost=declared_expected_cost,
    )


def verify_release_workflow_preflight(
    repository_root: Path,
    *,
    baseline_executor: str,
    grounded_executor: str,
    release_review_manifest: Path,
    require_positive_case_budgets: bool = False,
) -> EvaluationWorkflowPreflight:
    """Verify immutable corpus, baseline, selection, and review prerequisites."""

    suite = _load_complete_suite(repository_root)
    _load_shared_evidence(repository_root)
    _validate_executor_specification(baseline_executor, "baseline executor")
    _validate_executor_specification(grounded_executor, "grounded executor")

    selection = load_release_review_selection(repository_root)
    if len(selection.selected_cases) != 20:
        raise EvaluationWorkflowContractRejected(
            "Frozen independent-review selection must contain 20 cases"
        )

    if not release_review_manifest.is_file():
        raise EvaluationWorkflowContractRejected(
            f"Release review manifest does not exist: {release_review_manifest}"
        )

    _require_positive_case_budgets(
        suite.cases,
        required=require_positive_case_budgets,
    )

    return EvaluationWorkflowPreflight(
        mode="release",
        suite_id=suite.suite_id,
        selected_case_ids=tuple(case.id for case in suite.cases),
        declared_expected_cost=_declared_expected_cost(suite.cases),
    )


def _load_complete_suite(repository_root: Path) -> EvaluationCaseSuite:
    suite = load_evaluation_case_suite(repository_root / CASE_FIXTURE_RELATIVE_PATH)

    if suite.suite_id != EVALUATION_CORPUS_SUITE_ID:
        raise EvaluationWorkflowContractRejected(
            f"Expected suite {EVALUATION_CORPUS_SUITE_ID}, found {suite.suite_id}"
        )

    if Counter(case.split for case in suite.cases) != {
        "development": 60,
        "validation": 20,
        "holdout": 20,
    }:
        raise EvaluationWorkflowContractRejected(
            "Evaluation corpus must retain the exact 60/20/20 split"
        )

    development_categories = Counter(
        case.category for case in suite.cases if case.split == "development"
    )
    if development_categories != DEVELOPMENT_CATEGORY_TARGETS:
        raise EvaluationWorkflowContractRejected(
            "Development category totals do not match the evaluation plan"
        )

    for split, expected_categories in RELEASE_SPLIT_CATEGORY_TARGETS.items():
        actual_categories = Counter(
            case.category for case in suite.cases if case.split == split
        )
        if actual_categories != expected_categories:
            raise EvaluationWorkflowContractRejected(
                f"{split} category totals do not match the evaluation plan"
            )

    return suite


def _load_shared_evidence(repository_root: Path) -> None:
    load_ground_truth_catalog(repository_root / GROUND_TRUTH_RELATIVE_PATH)
    load_naive_baseline_config(repository_root / B0_CONFIG_RELATIVE_PATH)
    load_release_review_selection(repository_root)


def _validate_executor_specification(value: str, label: str) -> None:
    module_name, separator, attribute_name = value.partition(":")
    if (
        not separator
        or not module_name.strip()
        or not attribute_name.strip()
        or ":" in attribute_name
    ):
        raise EvaluationWorkflowContractRejected(
            f"{label} must use module:attribute form"
        )


def _declared_expected_cost(cases: tuple[EvaluationCase, ...]) -> int | float:
    return sum(case.expected.maximum_expected_cost for case in cases)


def _require_positive_case_budgets(
    cases: tuple[EvaluationCase, ...],
    *,
    required: bool,
) -> None:
    if not required:
        return

    zero_budget_case_ids = tuple(
        case.id for case in cases if case.expected.maximum_expected_cost <= 0
    )
    if zero_budget_case_ids:
        raise EvaluationWorkflowContractRejected(
            "Live workflow execution requires positive maximum_expected_cost "
            f"for every selected case; zero-budget cases={list(zero_budget_case_ids)}"
        )
