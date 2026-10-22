"""Assemble the guest-demo static site from verified publications (ADR-019).

Usage: ``uv run python scripts/publish_demo_site.py <archive-dir> <site-dir>
--owner-reviewed [--project-name NAME]`` or ``... --rollback-to <hash>``. The
logic lives in ``ai_qa_copilot_api.guest_demo_publish``; it never deploys.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    # Loaded at run time for the same reason as build_demo_snapshot.py: scripts/
    # is type-checked in the docs-validation job with dev dependencies only.
    publish = import_module("ai_qa_copilot_api.guest_demo_publish")
    return int(publish.main(sys.argv[1:] if argv is None else argv, repo_root=ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
