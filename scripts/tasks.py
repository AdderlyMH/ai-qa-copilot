"""Run the repository's stable engineering-command contract."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NODE_MAJOR = 24
EXECUTABLE_OVERRIDE_PREFIX = "AI_QA_COPILOT"


def run(*command: str, env: dict[str, str] | None = None) -> None:
    """Run one repository command and propagate a nonzero exit status."""

    subprocess.run(command, cwd=ROOT, check=True, env=env)


def require_executable(command: str, override_name: str) -> str:
    """Resolve one required executable or fail with an actionable message."""

    configured = os.environ.get(override_name)
    if configured is not None:
        configured_path = Path(configured).resolve()
        if not configured_path.is_file():
            raise RuntimeError(
                f"Configured executable does not exist: {override_name}={configured}"
            )
        return str(configured_path)
    executable = shutil.which(command)
    if executable is None:
        raise RuntimeError(f"Required executable is not on PATH: {command}")
    return executable


def uv() -> str:
    """Return the required uv executable."""

    return require_executable("uv", f"{EXECUTABLE_OVERRIDE_PREFIX}_UV")


def npm() -> str:
    """Return npm's executable, accounting for its Windows command shim."""

    return require_executable(
        "npm.cmd" if os.name == "nt" else "npm",
        f"{EXECUTABLE_OVERRIDE_PREFIX}_NPM",
    )


def node() -> str:
    """Return the Node.js executable."""

    return require_executable("node", f"{EXECUTABLE_OVERRIDE_PREFIX}_NODE")


def verify_node_major() -> None:
    """Fail when commands are not running on the supported Node.js major."""

    completed = subprocess.run(
        (node(), "--version"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    version = completed.stdout.strip().removeprefix("v")
    major_text, _, _ = version.partition(".")
    if not major_text.isdigit() or int(major_text) != EXPECTED_NODE_MAJOR:
        raise RuntimeError(
            f"Node.js {EXPECTED_NODE_MAJOR}.x is required; found {version or 'unknown'}"
        )


def node_environment() -> dict[str, str]:
    """Put the selected Node.js executable first for npm child scripts."""

    environment = os.environ.copy()
    node_directory = str(Path(node()).resolve().parent)
    current_path = environment.get("PATH")
    environment["PATH"] = (
        os.pathsep.join((node_directory, current_path))
        if current_path
        else node_directory
    )
    return environment


def uv_run(*command: str) -> None:
    """Run a command in the locked Python project environment."""

    run(uv(), "run", "--locked", *command)


def npm_run(script: str) -> None:
    """Run one pinned root npm script with the supported Node.js major."""

    verify_node_major()
    run(npm(), "run", script, env=node_environment())


def bootstrap() -> None:
    """Synchronize the locked Python and JavaScript dependencies."""

    verify_node_major()
    run(uv(), "sync", "--locked", "--python", "3.13")
    run(npm(), "ci", env=node_environment())


def format_code() -> None:
    """Format Python code and refresh the repository manifest."""

    uv_run("ruff", "format", "scripts", "apps/api")
    uv_run("python", "scripts/generate_manifest.py", "--write")


def lint() -> None:
    """Run the repository Python and frontend lint gates."""

    uv_run("ruff", "check", "scripts", "apps/api")
    npm_run("lint:web")


def typecheck() -> None:
    """Run strict Python and TypeScript type checking."""

    uv_run("mypy")
    npm_run("typecheck:web")


def test() -> None:
    """Run documentation self-tests and backend tests."""

    docs_self_test()
    uv_run("pytest", "apps/api/tests")


def docs_check() -> None:
    """Check manifest freshness and validate canonical documentation."""

    uv_run("python", "scripts/generate_manifest.py", "--check")
    uv_run("python", "scripts/validate_docs.py")


def docs_self_test() -> None:
    """Run the validator's isolated negative checks directly."""

    uv_run("python", "scripts/validate_docs.py", "--self-test")


def ci() -> None:
    """Run all noninteractive repository checks."""

    lint()
    typecheck()
    test()
    docs_check()


def stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    """Stop child development processes and wait for their exit."""

    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def dev(api_port: int, web_port: int) -> None:
    """Start the FastAPI and Next.js development servers together."""

    verify_node_major()
    commands = (
        (
            uv(),
            "run",
            "--locked",
            "uvicorn",
            "ai_qa_copilot_api.main:app",
            "--app-dir",
            "apps/api/src",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
            "--reload",
        ),
        (
            npm(),
            "run",
            "dev",
            "--workspace",
            "@ai-qa-copilot/web",
            "--",
            "--hostname",
            "localhost",
            "--port",
            str(web_port),
        ),
    )
    environments = (None, node_environment())
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for command, environment in zip(commands, environments, strict=True):
            processes.append(subprocess.Popen(command, cwd=ROOT, env=environment))
        print(
            f"API: http://127.0.0.1:{api_port} | "
            f"Web: http://localhost:{web_port} | press Ctrl+C to stop",
            flush=True,
        )
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    raise RuntimeError(
                        f"Development server exited unexpectedly with {return_code}"
                    )
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("Stopping development servers...", flush=True)
    finally:
        stop_processes(processes)


def print_help() -> None:
    """Print the stable target names without relying on Make availability."""

    print("Available targets:")
    print("  bootstrap format lint typecheck test dev docs-check docs-self-test ci")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse one stable target and optional development-server ports."""

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
    parser.add_argument("--port", type=int, default=8000, help="FastAPI port")
    parser.add_argument("--web-port", type=int, default=3000, help="Next.js port")
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
        dev(args.port, args.web_port)
    else:
        commands[args.target]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
