"""Render a deterministic evaluation corpus (v1, budgeted v2, informed v3, or objective v4)."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ai_qa_copilot_api.evaluation_budgeted_benchmark import (
    render_budgeted_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_informed_benchmark import (
    render_informed_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_objective_benchmark import (
    render_objective_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_release_benchmark import (
    render_complete_evaluation_cases,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS_RENDERERS: dict[str, tuple[Callable[[Path], str], Path]] = {
    "v1": (
        render_complete_evaluation_cases,
        ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml",
    ),
    "v2": (
        render_budgeted_evaluation_cases,
        ROOT / "fixtures/benchmark/evaluation-cases.v2.yaml",
    ),
    "v3": (
        render_informed_evaluation_cases,
        ROOT / "fixtures/benchmark/evaluation-cases.v3.yaml",
    ),
    "v4": (
        render_objective_evaluation_cases,
        ROOT / "fixtures/benchmark/evaluation-cases.v4.yaml",
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=sorted(CORPUS_RENDERERS), default="v1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    renderer, default_output = CORPUS_RENDERERS[args.corpus]
    rendered = renderer(ROOT)
    if not args.write:
        print(rendered, end="")
        return 0

    output: Path = args.output or default_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Evaluation corpus written: {_display_path(output)}")
    return 0


def _display_path(path: Path) -> Path:
    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return path.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
