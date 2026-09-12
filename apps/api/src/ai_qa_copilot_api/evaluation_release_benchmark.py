"""Deterministically build the complete EVAL-006 benchmark corpus."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import cast

import yaml

from ai_qa_copilot_api.evaluation_development_benchmark import (
    EVALUATION_CASES_SCHEMA_VERSION,
    build_development_evaluation_cases,
)


EVALUATION_CORPUS_SUITE_ID = "evaluation-corpus/v1"

RELEASE_SPLIT_CATEGORY_TARGETS: dict[str, dict[str, int]] = {
    "validation": {
        "requirement_quality": 4,
        "test_generation": 4,
        "requirement_openapi_consistency": 3,
        "retrieval_citation": 3,
        "tool_planning_execution": 2,
        "prompt_injection_security": 2,
        "failure_analysis": 1,
        "malformed_input_resilience": 1,
    },
    "holdout": {
        "requirement_quality": 4,
        "test_generation": 4,
        "requirement_openapi_consistency": 3,
        "retrieval_citation": 3,
        "tool_planning_execution": 2,
        "prompt_injection_security": 2,
        "failure_analysis": 1,
        "malformed_input_resilience": 1,
    },
}


class EvaluationReleaseBenchmarkRejected(ValueError):
    """Raised when the complete benchmark cannot be built safely."""


def render_complete_evaluation_cases(repository_root: Path) -> str:
    """Render the canonical 100-case corpus as stable YAML."""

    return yaml.safe_dump(
        build_complete_evaluation_cases(repository_root),
        sort_keys=False,
        allow_unicode=False,
    )


def build_complete_evaluation_cases(repository_root: Path) -> dict[str, object]:
    """Build 60 development, 20 validation, and 20 holdout cases."""

    development_fixture = build_development_evaluation_cases(repository_root)
    development_cases = _case_records(
        development_fixture.get("cases"),
        "development cases",
    )

    _validate_development_cases(development_cases)

    cases = deepcopy(development_cases)
    cases_by_category: dict[str, list[dict[str, object]]] = {}

    for case in development_cases:
        category = _text(case.get("category"), "development case category")
        cases_by_category.setdefault(category, []).append(case)

    next_case_number = 61
    for split, category_targets in RELEASE_SPLIT_CATEGORY_TARGETS.items():
        for category, target_count in category_targets.items():
            templates = cases_by_category.get(category)
            if not templates:
                raise EvaluationReleaseBenchmarkRejected(
                    f"No development template exists for {category}"
                )

            for scenario_number in range(1, target_count + 1):
                cases.append(
                    _release_case(
                        template=templates[(scenario_number - 1) % len(templates)],
                        case_number=next_case_number,
                        split=split,
                        scenario_number=scenario_number,
                    )
                )
                next_case_number += 1

    _validate_complete_cases(cases)

    return {
        "schema_version": EVALUATION_CASES_SCHEMA_VERSION,
        "suite_id": EVALUATION_CORPUS_SUITE_ID,
        "cases": cases,
    }


def _release_case(
    *,
    template: Mapping[str, object],
    case_number: int,
    split: str,
    scenario_number: int,
) -> dict[str, object]:
    case = deepcopy(dict(template))
    category = _text(case.get("category"), "release case category")
    inputs = _mapping(case.get("inputs"), f"{category} inputs")
    user_request = _text(inputs.get("user_request"), f"{category} user request")
    tags = _text_list(case.get("tags"), f"{category} tags")

    release_inputs = dict(inputs)
    release_inputs["user_request"] = (
        f"For {split} scenario {scenario_number}, {user_request}"
    )

    case["id"] = f"EVAL-{case_number:03}"
    case["split"] = split
    case["tags"] = [*tags, split]
    case["inputs"] = release_inputs
    return case


def _validate_development_cases(cases: list[dict[str, object]]) -> None:
    if len(cases) != 60:
        raise EvaluationReleaseBenchmarkRejected(
            f"Expected 60 development cases, found {len(cases)}"
        )

    if any(
        _text(case.get("split"), "development split") != "development" for case in cases
    ):
        raise EvaluationReleaseBenchmarkRejected(
            "Development builder returned a non-development case"
        )


def _validate_complete_cases(cases: list[dict[str, object]]) -> None:
    if len(cases) != 100:
        raise EvaluationReleaseBenchmarkRejected(
            f"Complete corpus must contain 100 cases, found {len(cases)}"
        )

    expected_case_ids = [f"EVAL-{number:03}" for number in range(1, 101)]
    actual_case_ids = [_text(case.get("id"), "case id") for case in cases]
    if actual_case_ids != expected_case_ids:
        raise EvaluationReleaseBenchmarkRejected(
            "Complete corpus case IDs must be EVAL-001 through EVAL-100"
        )

    split_counts = Counter(_text(case.get("split"), "case split") for case in cases)
    if split_counts != {"development": 60, "validation": 20, "holdout": 20}:
        raise EvaluationReleaseBenchmarkRejected(
            f"Unexpected split totals: {dict(sorted(split_counts.items()))}"
        )

    for split, expected_categories in RELEASE_SPLIT_CATEGORY_TARGETS.items():
        actual_categories = Counter(
            _text(case.get("category"), "case category")
            for case in cases
            if _text(case.get("split"), "case split") == split
        )
        if actual_categories != expected_categories:
            raise EvaluationReleaseBenchmarkRejected(
                f"Unexpected {split} category totals: "
                f"{dict(sorted(actual_categories.items()))}"
            )


def _case_records(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise EvaluationReleaseBenchmarkRejected(f"{label} must be a list")

    records: list[dict[str, object]] = []
    for index, record in enumerate(value):
        records.append(dict(_mapping(record, f"{label}[{index}]")))
    return records


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise EvaluationReleaseBenchmarkRejected(f"{label} must be a mapping")
    return cast(Mapping[str, object], value)


def _text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise EvaluationReleaseBenchmarkRejected(f"{label} must be a list")
    return [_text(item, label) for item in value]


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationReleaseBenchmarkRejected(f"{label} must be non-empty text")
    return value.strip()
