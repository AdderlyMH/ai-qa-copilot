"""Generate the checked-in 60-case EVAL-005 development benchmark."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_qa_copilot_api.evaluation_development_benchmark import (
    render_development_evaluation_cases,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    rendered = render_development_evaluation_cases(ROOT)
    if not args.write:
        print(rendered, end="")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Development benchmark written: {_display_path(args.output)}")
    return 0


def _display_path(path: Path) -> Path:
    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return path.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
