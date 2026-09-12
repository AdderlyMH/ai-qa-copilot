from __future__ import annotations

from collections import Counter
from pathlib import Path
import shutil

import pytest
import yaml

from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_release_review_selection import (
    NON_SECURITY_REVIEW_CATEGORY_QUOTAS,
    SECURITY_POLICY_ID_PREFIX,
    SELECTION_FIXTURE_RELATIVE_PATH,
    ReleaseReviewSelectionRejected,
    load_release_review_selection,
    render_release_review_selection,
)


ROOT = Path(__file__).resolve().parents[3]
CASE_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
SELECTION_FIXTURE = ROOT / SELECTION_FIXTURE_RELATIVE_PATH


def test_committed_selection_matches_the_deterministic_frozen_contract() -> None:
    selection = load_release_review_selection(ROOT)

    assert render_release_review_selection(ROOT) == SELECTION_FIXTURE.read_text(
        encoding="utf-8"
    )
    assert len(selection.selected_cases) == 20
    assert Counter(case.split for case in selection.selected_cases) == {
        "validation": 10,
        "holdout": 10,
    }

    for split, expected_quotas in NON_SECURITY_REVIEW_CATEGORY_QUOTAS.items():
        assert (
            Counter(
                case.category
                for case in selection.selected_cases
                if case.split == split
            )
            == expected_quotas
        )


def test_committed_selection_contains_only_non_policy_cases() -> None:
    selection = load_release_review_selection(ROOT)
    cases_by_id = {
        case.id: case for case in load_evaluation_case_suite(CASE_FIXTURE).cases
    }

    assert len({case.case_id for case in selection.selected_cases}) == 20

    for selected_case in selection.selected_cases:
        case = cases_by_id[selected_case.case_id]

        assert case.split == selected_case.split
        assert case.category == selected_case.category
        assert all(
            not ground_truth_id.startswith(SECURITY_POLICY_ID_PREFIX)
            for ground_truth_id in case.expected.required_ground_truth_ids
        )


def test_selection_rejects_any_tampered_contract(tmp_path: Path) -> None:
    fixture_directory = tmp_path / "fixtures/benchmark"
    fixture_directory.mkdir(parents=True)

    for fixture in (
        ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml",
        ROOT / "fixtures/benchmark/ground-truth.v1.yaml",
        ROOT / "fixtures/benchmark/release-review-selection.v1.yaml",
    ):
        shutil.copy(fixture, fixture_directory / fixture.name)

    selection_path = fixture_directory / "release-review-selection.v1.yaml"
    raw = yaml.safe_load(selection_path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)

    raw["selection"]["seed"] = "tampered"
    selection_path.write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(
        ReleaseReviewSelectionRejected,
        match="deterministic frozen contract",
    ):
        load_release_review_selection(tmp_path)
