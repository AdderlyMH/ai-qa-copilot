"""Score a completed evaluation run against the approved ground-truth catalog."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_runner import evaluation_run_from_json
from ai_qa_copilot_api.evaluation_scoring import (
    EvaluationScoringRejected,
    load_ground_truth_catalog,
    score_evaluation_run,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
DEFAULT_GROUND_TRUTH = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_CASE_FIXTURE)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH)
    parser.add_argument("--run-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    for label, path in (
        ("Evaluation fixture", args.fixture),
        ("Ground-truth catalog", args.ground_truth),
        ("Evaluation run report", args.run_report),
    ):
        if not path.is_file():
            raise SystemExit(f"{label} does not exist: {path}")

    if args.output.exists():
        raise SystemExit(f"Output already exists: {args.output}")

    try:
        report = score_evaluation_run(
            load_evaluation_case_suite(args.fixture),
            evaluation_run_from_json(args.run_report.read_text(encoding="utf-8")),
            load_ground_truth_catalog(args.ground_truth),
            case_fixture_path=args.fixture,
            ground_truth_path=args.ground_truth,
        )
    except (EvaluationScoringRejected, ValueError) as error:
        raise SystemExit(str(error)) from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.as_json(), encoding="utf-8")
    print(f"Evaluation score report written: {_display_path(args.output)}")
    return 0


def _display_path(path: Path) -> Path:
    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return path.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
