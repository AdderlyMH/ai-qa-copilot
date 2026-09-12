"""Create and verify the frozen EVAL-006 independent-review selection."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Final, cast

import yaml

from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_release_benchmark import (
    EVALUATION_CORPUS_SUITE_ID,
)


RELEASE_REVIEW_SELECTION_SCHEMA_VERSION: Final = "release-review-selection/v1"
RELEASE_REVIEW_SELECTION_ID: Final = "EVAL-006-RELEASE-REVIEW-SELECTION-V1"
RELEASE_REVIEW_SELECTION_METHOD: Final = "stratified_sha256_rank/v1"
RELEASE_REVIEW_SELECTION_SEED: Final = "eval-006-release-review-selection-v1"
RELEASE_REVIEW_SELECTION_RECORDED_AT: Final = "2026-09-12T00:00:00Z"
SECURITY_POLICY_ID_PREFIX: Final = "GT-POL-"

CASE_FIXTURE_RELATIVE_PATH = Path("fixtures/benchmark/evaluation-cases.v1.yaml")
GROUND_TRUTH_FIXTURE_RELATIVE_PATH = Path("fixtures/benchmark/ground-truth.v1.yaml")
SELECTION_FIXTURE_RELATIVE_PATH = Path(
    "fixtures/benchmark/release-review-selection.v1.yaml"
)

NON_SECURITY_REVIEW_CATEGORY_QUOTAS: dict[str, dict[str, int]] = {
    "validation": {
        "requirement_quality": 3,
        "test_generation": 3,
        "requirement_openapi_consistency": 2,
        "retrieval_citation": 1,
        "failure_analysis": 1,
    },
    "holdout": {
        "requirement_quality": 3,
        "test_generation": 3,
        "requirement_openapi_consistency": 2,
        "retrieval_citation": 1,
        "failure_analysis": 1,
    },
}


class ReleaseReviewSelectionRejected(ValueError):
    """Raised when the frozen selection contract is absent or inconsistent."""


@dataclass(frozen=True)
class ReleaseReviewSelectionCase:
    """One non-security case selected for mandatory independent review."""

    case_id: str
    split: str
    category: str


@dataclass(frozen=True)
class ReleaseReviewSelection:
    """The immutable selection contract consumed by the later release workflow."""

    schema_version: str
    selection_id: str
    case_fixture_semantic_sha256: str
    ground_truth_fixture_semantic_sha256: str
    seed: str
    selected_cases: tuple[ReleaseReviewSelectionCase, ...]


def render_release_review_selection(repository_root: Path) -> str:
    """Render the canonical static selection contract as YAML."""

    return yaml.safe_dump(
        _selection_mapping(build_release_review_selection(repository_root)),
        sort_keys=False,
        allow_unicode=False,
    )


def build_release_review_selection(repository_root: Path) -> ReleaseReviewSelection:
    """Select exactly ten non-policy validation and holdout cases deterministically."""

    case_fixture = repository_root / CASE_FIXTURE_RELATIVE_PATH
    ground_truth_fixture = repository_root / GROUND_TRUTH_FIXTURE_RELATIVE_PATH
    suite = load_evaluation_case_suite(case_fixture)

    if suite.suite_id != EVALUATION_CORPUS_SUITE_ID:
        raise ReleaseReviewSelectionRejected(
            f"Expected suite {EVALUATION_CORPUS_SUITE_ID}, found {suite.suite_id}"
        )

    selected_cases: list[ReleaseReviewSelectionCase] = []
    for split, category_quotas in NON_SECURITY_REVIEW_CATEGORY_QUOTAS.items():
        for category, quota in category_quotas.items():
            eligible_cases = [
                case
                for case in suite.cases
                if case.split == split
                and case.category == category
                and _is_non_security_case(case)
            ]
            ranked_cases = sorted(
                eligible_cases,
                key=lambda case: _selection_rank(split, category, case.id),
            )

            if len(ranked_cases) < quota:
                raise ReleaseReviewSelectionRejected(
                    f"{split}/{category} has {len(ranked_cases)} eligible cases; "
                    f"{quota} are required"
                )

            selected_cases.extend(
                ReleaseReviewSelectionCase(
                    case_id=case.id,
                    split=case.split,
                    category=case.category,
                )
                for case in ranked_cases[:quota]
            )

    _validate_selected_cases(selected_cases)

    return ReleaseReviewSelection(
        schema_version=RELEASE_REVIEW_SELECTION_SCHEMA_VERSION,
        selection_id=RELEASE_REVIEW_SELECTION_ID,
        case_fixture_semantic_sha256=_semantic_yaml_sha256(case_fixture),
        ground_truth_fixture_semantic_sha256=_semantic_yaml_sha256(
            ground_truth_fixture
        ),
        seed=RELEASE_REVIEW_SELECTION_SEED,
        selected_cases=tuple(selected_cases),
    )


def load_release_review_selection(repository_root: Path) -> ReleaseReviewSelection:
    """Load only the exact deterministic selection contract committed to the repo."""

    selection_path = repository_root / SELECTION_FIXTURE_RELATIVE_PATH
    raw = cast(object, yaml.safe_load(selection_path.read_text(encoding="utf-8")))
    expected_selection = build_release_review_selection(repository_root)
    expected = _selection_mapping(expected_selection)

    if raw != expected:
        raise ReleaseReviewSelectionRejected(
            "Release-review selection must match the deterministic frozen contract"
        )

    return expected_selection


def _selection_mapping(selection: ReleaseReviewSelection) -> dict[str, object]:
    return {
        "schema_version": selection.schema_version,
        "selection_id": selection.selection_id,
        "case_fixture": str(CASE_FIXTURE_RELATIVE_PATH).replace("\\", "/"),
        "case_fixture_semantic_sha256": selection.case_fixture_semantic_sha256,
        "ground_truth_fixture": str(GROUND_TRUTH_FIXTURE_RELATIVE_PATH).replace(
            "\\", "/"
        ),
        "ground_truth_fixture_semantic_sha256": (
            selection.ground_truth_fixture_semantic_sha256
        ),
        "selection": {
            "method": RELEASE_REVIEW_SELECTION_METHOD,
            "seed": selection.seed,
            "recorded_at": RELEASE_REVIEW_SELECTION_RECORDED_AT,
            "selected_before_candidate_execution": True,
            "replacement_policy": "no_replacement",
            "security_policy_ground_truth_id_prefix": SECURITY_POLICY_ID_PREFIX,
            "per_split_category_quotas": NON_SECURITY_REVIEW_CATEGORY_QUOTAS,
        },
        "selected_cases": [
            {
                "case_id": case.case_id,
                "split": case.split,
                "category": case.category,
            }
            for case in selection.selected_cases
        ],
    }


def _is_non_security_case(case: EvaluationCase) -> bool:
    return all(
        not ground_truth_id.startswith(SECURITY_POLICY_ID_PREFIX)
        for ground_truth_id in case.expected.required_ground_truth_ids
    )


def _selection_rank(split: str, category: str, case_id: str) -> str:
    value = f"{RELEASE_REVIEW_SELECTION_SEED}\x00{split}\x00{category}\x00{case_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_selected_cases(
    selected_cases: list[ReleaseReviewSelectionCase],
) -> None:
    if len(selected_cases) != 20:
        raise ReleaseReviewSelectionRejected(
            f"Expected 20 selected cases, found {len(selected_cases)}"
        )

    case_ids = [case.case_id for case in selected_cases]
    if len(set(case_ids)) != len(case_ids):
        raise ReleaseReviewSelectionRejected("Selected cases must be unique")

    split_counts = Counter(case.split for case in selected_cases)
    if split_counts != {"validation": 10, "holdout": 10}:
        raise ReleaseReviewSelectionRejected(
            f"Unexpected selected split totals: {dict(sorted(split_counts.items()))}"
        )

    for split, expected_quotas in NON_SECURITY_REVIEW_CATEGORY_QUOTAS.items():
        actual_quotas = Counter(
            case.category for case in selected_cases if case.split == split
        )
        if actual_quotas != expected_quotas:
            raise ReleaseReviewSelectionRejected(
                f"Unexpected {split} selection: {dict(sorted(actual_quotas.items()))}"
            )


def _semantic_yaml_sha256(path: Path) -> str:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    canonical_json = json.dumps(
        raw,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
