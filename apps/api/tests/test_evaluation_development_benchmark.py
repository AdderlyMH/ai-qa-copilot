from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path

import yaml

from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite


ROOT = Path(__file__).resolve().parents[3]
CASE_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
GROUND_TRUTH_FIXTURE = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"

EXPECTED_DEVELOPMENT_CATEGORY_COUNTS = {
    "requirement_quality": 12,
    "test_generation": 12,
    "requirement_openapi_consistency": 9,
    "retrieval_citation": 9,
    "tool_planning_execution": 6,
    "prompt_injection_security": 6,
    "failure_analysis": 3,
    "malformed_input_resilience": 3,
}


def test_committed_development_fixture_has_exact_evaluation_plan_shape() -> None:
    suite = load_evaluation_case_suite(CASE_FIXTURE)

    assert len(suite.cases) == 60
    assert [case.id for case in suite.cases] == [
        f"EVAL-{number:03}" for number in range(1, 61)
    ]
    assert Counter(case.split for case in suite.cases) == {"development": 60}
    assert Counter(case.category for case in suite.cases) == (
        EXPECTED_DEVELOPMENT_CATEGORY_COUNTS
    )
    assert all(case.expected.maximum_expected_cost == 0 for case in suite.cases)


def test_every_case_uses_committed_sources_and_approved_ground_truth() -> None:
    raw_cases = yaml.safe_load(CASE_FIXTURE.read_text(encoding="utf-8"))
    raw_ground_truth = yaml.safe_load(GROUND_TRUTH_FIXTURE.read_text(encoding="utf-8"))

    assert isinstance(raw_cases, dict)
    assert isinstance(raw_ground_truth, dict)

    catalog_ids = {
        record["id"]
        for collection_name in ("findings", "policies")
        for record in raw_ground_truth[collection_name]
    }

    for case in raw_cases["cases"]:
        expected = case["expected"]

        assert set(expected["required_ground_truth_ids"]) <= catalog_ids
        assert set(expected["prohibited_ground_truth_ids"]) <= catalog_ids

        for artifact in case["inputs"]["artifacts"]:
            source_path = ROOT / artifact["path"]

            assert source_path.is_file()
            assert (
                artifact["sha256"]
                == hashlib.sha256(source_path.read_bytes()).hexdigest()
            )
