"""Run the repository's stable engineering-command contract."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(*command: str) -> None:
    """Run one repository command and propagate a nonzero exit status."""

    subprocess.run(command, cwd=ROOT, check=True)


def bootstrap() -> None:
    """Install the pinned development tools into the current interpreter."""

    run(PYTHON, "-m", "pip", "install", "-r", "requirements-dev.txt")


def format_code() -> None:
    """Format Python tooling and refresh the manifest it changes."""

    run(PYTHON, "-m", "ruff", "format", "scripts")
    run(PYTHON, "scripts/generate_manifest.py", "--write")


def lint() -> None:
    """Run the repository Python lint gate."""

    run(PYTHON, "-m", "ruff", "check", "scripts")


def typecheck() -> None:
    """Run static type checking for repository Python tooling."""

    run(PYTHON, "-m", "mypy", "scripts")


def test() -> None:
    """Run isolated validator negative tests."""

    run(PYTHON, "scripts/validate_docs.py", "--self-test")


def docs_check() -> None:
    """Check manifest freshness and validate canonical documentation."""

    run(PYTHON, "scripts/generate_manifest.py", "--check")
    run(PYTHON, "scripts/validate_docs.py")


def docs_self_test() -> None:
    """Run the validator's isolated negative checks directly."""

    test()


def ci() -> None:
    """Run all noninteractive Phase 0 checks."""

    lint()
    typecheck()
    test()
    docs_check()


def dev(port: int) -> None:
    """Serve a static Phase 0 repository preview."""

    run(PYTHON, "-m", "http.server", str(port), "--directory", str(ROOT))


def print_help() -> None:
    """Print the stable target names without relying on Make availability."""

    print("Available targets:")
    print("  bootstrap format lint typecheck test dev docs-check docs-self-test ci")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse one stable target and an optional static-preview port."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        choices=(
            "help",
            "bootstrap",
            "format",
            "lint",
            "typecheck",
            "test",
            "dev",
            "docs-check",
            "docs-self-test",
            "ci",
        ),
        nargs="?",
        default="help",
    )
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Dispatch the requested target."""

    args = parse_args(argv)
    commands: dict[str, Callable[[], None]] = {
        "bootstrap": bootstrap,
        "format": format_code,
        "lint": lint,
        "typecheck": typecheck,
        "test": test,
        "docs-check": docs_check,
        "docs-self-test": docs_self_test,
        "ci": ci,
    }
    if args.target == "help":
        print_help()
    elif args.target == "dev":
        dev(args.port)
    else:
        commands[args.target]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
