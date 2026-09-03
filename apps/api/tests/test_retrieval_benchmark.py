from __future__ import annotations

from pathlib import Path

import pytest

from ai_qa_copilot_api.retrieval_benchmark import (
    evaluate_retrieval_benchmark,
    load_retrieval_benchmark,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures/benchmark/retrieval-benchmark.v1.yaml"
REPORT = ROOT / "fixtures/benchmark/retrieval-baseline.v1.json"


def test_development_retrieval_baseline_has_fifteen_visible_queries() -> None:
    benchmark = load_retrieval_benchmark(FIXTURE)

    assert len(benchmark.cases) == 15
    assert {case.split for case in benchmark.cases} == {"development"}
    assert sum(case.expected_outcome == "no_answer" for case in benchmark.cases) == 1


def test_committed_retrieval_baseline_matches_deterministic_metrics() -> None:
    baseline = evaluate_retrieval_benchmark(load_retrieval_benchmark(FIXTURE))

    assert baseline.answerable_query_count == 14
    assert baseline.no_answer_query_count == 1
    assert baseline.recall_at_k == {
        "1": 0.5,
        "3": pytest.approx(11 / 14),
        "5": pytest.approx(13 / 14),
        "10": pytest.approx(13 / 14),
    }
    assert baseline.mean_reciprocal_rank == pytest.approx(9.283333333333333 / 14)
    assert baseline.no_answer_false_positive_rate == 0
    assert REPORT.read_text(encoding="utf-8") == baseline.as_json()
