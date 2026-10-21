"""Build the guest-demo snapshot locally into an output directory (ADR-019).

Offline and deterministic: no provider, no network, no database. Writes only
``snapshot.json`` and ``manifest.json`` into the given directory, which must be
outside the repository and must not already contain them. Prints the content
hash and the files written. Run through ``scripts/build_demo_snapshot.py``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_qa_copilot_api.guest_demo_build import DemoBuildRejected, build_demo
from ai_qa_copilot_api.guest_demo_snapshot import (
    SnapshotRejected,
    render_snapshot,
    write_snapshot,
)


def main(argv: list[str] | None, *, repo_root: Path) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args(argv)

    root = repo_root.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir == root or root in output_dir.parents:
        raise SystemExit("The output directory must be outside the repository")

    try:
        output = render_snapshot(build_demo(root / "demo" / "fixture"))
        written = write_snapshot(output, output_dir)
    except (DemoBuildRejected, SnapshotRejected) as error:
        raise SystemExit(f"Build refused: {error}") from None
    print(f"content_hash {output.content_hash}")
    for path in written:
        print(f"wrote {path.name}")
    return 0
