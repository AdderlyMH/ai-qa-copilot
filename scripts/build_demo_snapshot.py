"""Build the guest-demo snapshot locally into an output directory (ADR-019).

Usage: ``uv run python scripts/build_demo_snapshot.py <output-dir>``. The build
lives in ``ai_qa_copilot_api.guest_demo_cli``; see that module for behavior.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    # Loaded at run time: the build needs the API's runtime dependencies
    # (FastAPI for the in-process mock), while scripts/ is type-checked in the
    # docs-validation job with dev dependencies only. The CLI module itself is
    # type-checked by the full mypy run in application CI.
    cli = import_module("ai_qa_copilot_api.guest_demo_cli")
    return int(cli.main(sys.argv[1:] if argv is None else argv, repo_root=ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
