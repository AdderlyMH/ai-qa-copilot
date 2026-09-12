from __future__ import annotations

from collections import Counter
from pathlib import Path

from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_release_benchmark import (
    EVALUATION_CORPUS_SUITE_ID,
    RELEASE_SPLIT_CATEGORY_TARGETS,
    render_complete_evaluation_cases,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"


def test_committed_fixture_matches_the_complete_deterministic_renderer() -> None:
    assert render_complete_evaluation_cases(ROOT) == FIXTURE.read_text(encoding="utf-8")


def test_complete_fixture_has_exact_evaluation_plan_shape() -> None:
    suite = load_evaluation_case_suite(FIXTURE)

    assert suite.suite_id == EVALUATION_CORPUS_SUITE_ID
    assert [case.id for case in suite.cases] == [
        f"EVAL-{number:03}" for number in range(1, 101)
    ]
    assert Counter(case.split for case in suite.cases) == {
        "development": 60,
        "validation": 20,
        "holdout": 20,
    }

    for split, expected_categories in RELEASE_SPLIT_CATEGORY_TARGETS.items():
        assert (
            Counter(case.category for case in suite.cases if case.split == split)
            == expected_categories
        )
