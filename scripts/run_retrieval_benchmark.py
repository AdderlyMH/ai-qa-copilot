"""Render or verify the committed RAG-005 retrieval baseline artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_qa_copilot_api.retrieval_benchmark import (
    evaluate_retrieval_benchmark,
    load_retrieval_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "fixtures/benchmark/retrieval-benchmark.v1.yaml"
DEFAULT_REPORT = ROOT / "fixtures/benchmark/retrieval-baseline.v1.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    report = evaluate_retrieval_benchmark(
        load_retrieval_benchmark(args.fixture)
    ).as_json()
    if args.check:
        if args.report.read_text(encoding="utf-8") != report:
            raise SystemExit("Retrieval baseline report is stale")
        print("Retrieval baseline check passed.")
        return 0

    args.report.write_text(report, encoding="utf-8")
    print(f"Retrieval baseline written: {args.report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
