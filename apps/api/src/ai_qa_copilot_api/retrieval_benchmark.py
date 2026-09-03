"""Deterministic scoring for the versioned development retrieval baseline."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import yaml


BENCHMARK_SCHEMA_VERSION = "retrieval-benchmark/v1"
BASELINE_SCHEMA_VERSION = "retrieval-baseline/v1"
DEFAULT_RECALL_CUTOFFS = (1, 3, 5, 10)


@dataclass(frozen=True)
class RetrievalBenchmarkCase:
    """One visible development query and its frozen, auditable rank observation."""

    id: str
    split: str
    query: str
    expected_outcome: str
    expected_source_ids: tuple[str, ...]
    ranked_source_ids: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalBenchmark:
    """Validated RAG-005 development corpus and retrieval configuration."""

    benchmark_id: str
    retrieval_configuration: dict[str, str]
    cases: tuple[RetrievalBenchmarkCase, ...]


@dataclass(frozen=True)
class RetrievalBaseline:
    """Aggregate exact-source retrieval metrics for one immutable fixture run."""

    benchmark_id: str
    retrieval_configuration: dict[str, str]
    answerable_query_count: int
    no_answer_query_count: int
    recall_at_k: dict[str, float]
    mean_reciprocal_rank: float
    no_answer_false_positive_rate: float

    def as_json(self) -> str:
        """Render the committed, stable baseline artifact."""

        return (
            json.dumps(
                {
                    "schema_version": BASELINE_SCHEMA_VERSION,
                    "benchmark_id": self.benchmark_id,
                    "retrieval_configuration": self.retrieval_configuration,
                    "metrics": {
                        "answerable_query_count": self.answerable_query_count,
                        "no_answer_query_count": self.no_answer_query_count,
                        "recall_at_k": self.recall_at_k,
                        "mean_reciprocal_rank": self.mean_reciprocal_rank,
                        "no_answer_false_positive_rate": self.no_answer_false_positive_rate,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


def load_retrieval_benchmark(path: Path) -> RetrievalBenchmark:
    """Load only the narrow, visible development fixture contract for RAG-005."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Retrieval benchmark must be a mapping")
    if raw.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
        raise ValueError("Unsupported retrieval benchmark schema version")
    benchmark_id = _required_text(raw, "benchmark_id")
    configuration = raw.get("retrieval_configuration")
    if not isinstance(configuration, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value.strip()
        for key, value in configuration.items()
    ):
        raise ValueError("Retrieval configuration must contain non-empty strings")
    cases_raw = raw.get("cases")
    if not isinstance(cases_raw, list) or len(cases_raw) < 15:
        raise ValueError("Retrieval benchmark requires at least 15 cases")

    cases = tuple(_case(value) for value in cases_raw)
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Retrieval benchmark case IDs must be unique")
    if any(case.split != "development" for case in cases):
        raise ValueError("RAG-005 baseline may contain development cases only")
    return RetrievalBenchmark(
        benchmark_id=benchmark_id,
        retrieval_configuration=dict(sorted(configuration.items())),
        cases=cases,
    )


def evaluate_retrieval_benchmark(
    benchmark: RetrievalBenchmark,
    *,
    recall_cutoffs: tuple[int, ...] = DEFAULT_RECALL_CUTOFFS,
) -> RetrievalBaseline:
    """Calculate exact-source metrics without network, models, or tuning state."""

    if not recall_cutoffs or any(cutoff <= 0 for cutoff in recall_cutoffs):
        raise ValueError("Recall cutoffs must be positive")
    answerable = tuple(
        case for case in benchmark.cases if case.expected_outcome == "source"
    )
    no_answer = tuple(
        case for case in benchmark.cases if case.expected_outcome == "no_answer"
    )
    if not answerable or not no_answer:
        raise ValueError("Benchmark requires source and no-answer cases")

    recall_at_k = {
        str(cutoff): sum(_has_expected_source(case, cutoff) for case in answerable)
        / len(answerable)
        for cutoff in recall_cutoffs
    }
    reciprocal_ranks = [_reciprocal_rank(case) for case in answerable]
    false_positive_rate = sum(bool(case.ranked_source_ids) for case in no_answer) / len(
        no_answer
    )
    return RetrievalBaseline(
        benchmark_id=benchmark.benchmark_id,
        retrieval_configuration=benchmark.retrieval_configuration,
        answerable_query_count=len(answerable),
        no_answer_query_count=len(no_answer),
        recall_at_k=recall_at_k,
        mean_reciprocal_rank=sum(reciprocal_ranks) / len(reciprocal_ranks),
        no_answer_false_positive_rate=false_positive_rate,
    )


def _case(raw: object) -> RetrievalBenchmarkCase:
    if not isinstance(raw, dict):
        raise ValueError("Retrieval benchmark case must be a mapping")
    expected_outcome = _required_text(raw, "expected_outcome")
    if expected_outcome not in {"source", "no_answer"}:
        raise ValueError("Retrieval benchmark expected outcome is invalid")
    expected_source_ids = _string_tuple(raw.get("expected_source_ids"))
    ranked_source_ids = _string_tuple(raw.get("ranked_source_ids"))
    if len(set(expected_source_ids)) != len(expected_source_ids):
        raise ValueError("Expected source IDs must not repeat")
    if len(set(ranked_source_ids)) != len(ranked_source_ids):
        raise ValueError("Ranked source IDs must not repeat")
    if expected_outcome == "source" and not expected_source_ids:
        raise ValueError("Source cases require expected source IDs")
    if expected_outcome == "no_answer" and expected_source_ids:
        raise ValueError("No-answer cases must not define expected source IDs")
    return RetrievalBenchmarkCase(
        id=_required_text(raw, "id"),
        split=_required_text(raw, "split"),
        query=_required_text(raw, "query"),
        expected_outcome=expected_outcome,
        expected_source_ids=expected_source_ids,
        ranked_source_ids=ranked_source_ids,
    )


def _required_text(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Retrieval benchmark {key} must be non-empty text")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError("Source ID collections must be lists of non-empty text")
    return tuple(value)


def _has_expected_source(case: RetrievalBenchmarkCase, cutoff: int) -> bool:
    return bool(set(case.expected_source_ids) & set(case.ranked_source_ids[:cutoff]))


def _reciprocal_rank(case: RetrievalBenchmarkCase) -> float:
    expected = set(case.expected_source_ids)
    for rank, source_id in enumerate(case.ranked_source_ids, start=1):
        if source_id in expected:
            return 1 / rank
    return 0.0
