"""Write immutable JSON and Markdown evidence comparing B0 and grounded scores."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_qa_copilot_api.evaluation_baseline_comparison import (
    EvaluationBaselineComparisonRejected,
    compare_evaluation_score_reports,
    load_evaluation_score_report,
)


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-score-report", type=Path, required=True)
    parser.add_argument("--grounded-score-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument(
        "--baseline-label",
        default="B0 naive single prompt",
    )
    parser.add_argument(
        "--grounded-label",
        default="Grounded workflow",
    )
    args = parser.parse_args(argv)

    for source_path, label in (
        (args.baseline_score_report, "Baseline score report"),
        (args.grounded_score_report, "Grounded score report"),
    ):
        if not source_path.is_file():
            raise SystemExit(f"{label} does not exist: {source_path}")

    for output_path, label in (
        (args.output, "JSON output"),
        (args.markdown_output, "Markdown output"),
    ):
        if output_path.exists():
            raise SystemExit(
                f"{label} already exists: {output_path}. "
                "Choose a new path rather than replacing evidence."
            )

    try:
        comparison = compare_evaluation_score_reports(
            baseline_report=load_evaluation_score_report(args.baseline_score_report),
            grounded_report=load_evaluation_score_report(args.grounded_score_report),
            baseline_label=args.baseline_label,
            grounded_label=args.grounded_label,
        )
    except EvaluationBaselineComparisonRejected as error:
        raise SystemExit(str(error)) from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(comparison.as_json(), encoding="utf-8")
    args.markdown_output.write_text(comparison.as_markdown(), encoding="utf-8")

    print(f"Baseline comparison JSON written: {_display_path(args.output)}")
    print(
        f"Baseline comparison Markdown written: {_display_path(args.markdown_output)}"
    )
    return 0


def _display_path(path: Path) -> Path:
    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return path.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
