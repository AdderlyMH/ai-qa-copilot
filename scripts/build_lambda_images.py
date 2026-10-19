"""Build the Lambda container images for linux/arm64 (INFRA-009, INFRA-012).

The images are built from ``apps/api/Dockerfile.lambda`` (one target per
function class), tagged locally with the current Git commit SHA and loaded into
the local Docker image store. Nothing is pushed: pushing to ECR is a separate
owner step with local credentials (docs/INFRASTRUCTURE.md). This script makes
no AWS call, reads no credentials and prints no environment values.

By default it builds the four application functions. The one-shot migration
runner (target ``migrate``, INFRA-012) is built only when named.

Usage (PowerShell or any shell):

    py scripts/build_lambda_images.py
    py scripts/build_lambda_images.py --function parser
    py scripts/build_lambda_images.py --function migrate
    py scripts/build_lambda_images.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = "apps/api/Dockerfile.lambda"
PLATFORM = "linux/arm64"
FUNCTIONS = ("api", "parser", "general", "executor")
MIGRATION_TARGET = "migrate"
TARGETS = (*FUNCTIONS, MIGRATION_TARGET)
LOCAL_REPOSITORY_PREFIX = "ai-qa-copilot-lambda"
# Paths that reach the build context (see Dockerfile.lambda.dockerignore). The
# tag names a commit, so these must match that commit exactly.
BUILD_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "apps/api/pyproject.toml",
    "apps/api/src",
    "apps/api/alembic.ini",
    "apps/api/alembic",
    "apps/api/certs/rds-global-bundle.pem",
    DOCKERFILE,
    f"{DOCKERFILE}.dockerignore",
)


class BuildError(RuntimeError):
    """A precondition for a reproducible image build is not met."""


def git_output(*arguments: str) -> str:
    """Return the stripped standard output of one Git command."""

    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def commit_sha() -> str:
    """Return the full SHA of HEAD."""

    return git_output("rev-parse", "--verify", "HEAD")


def uncommitted_build_inputs() -> list[str]:
    """Return changed or untracked paths among the build inputs."""

    status = git_output(
        "status", "--porcelain", "--untracked-files=all", "--", *BUILD_INPUTS
    )
    return [line for line in status.splitlines() if line.strip()]


def image_reference(function: str, sha: str) -> str:
    """Return the local image name and commit tag for one function class."""

    return f"{LOCAL_REPOSITORY_PREFIX}/{function}:{sha}"


def build_command(docker: str, function: str, sha: str) -> list[str]:
    """Return the buildx command for one single-architecture arm64 image."""

    return [
        docker,
        "buildx",
        "build",
        "--platform",
        PLATFORM,
        "--provenance=false",
        "--sbom=false",
        "--file",
        DOCKERFILE,
        "--target",
        function,
        "--tag",
        image_reference(function, sha),
        "--load",
        ".",
    ]


def inspect_command(docker: str, function: str, sha: str) -> list[str]:
    """Return the command that prints the local image ID, size and platform."""

    return [
        docker,
        "image",
        "inspect",
        "--format",
        "{{.Id}} {{.Size}} {{.Os}}/{{.Architecture}}",
        image_reference(function, sha),
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the selected function classes and the dry-run flag."""

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--function",
        action="append",
        choices=TARGETS,
        help=(
            "Build only this target (repeatable); default: the four function "
            "classes. 'migrate' is built only when named."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the build commands without running Docker.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build the selected images and print their local IDs and sizes."""

    args = parse_args(argv)
    functions = tuple(args.function or FUNCTIONS)
    sha = commit_sha()
    docker = shutil.which("docker") or "docker"

    if args.dry_run:
        for function in functions:
            print(" ".join(build_command(docker, function, sha)))
        return 0

    pending = uncommitted_build_inputs()
    if pending:
        print(
            "Build inputs differ from the commit the tag would name; commit or "
            "stash these first:",
            file=sys.stderr,
        )
        for line in pending:
            print(f"  {line}", file=sys.stderr)
        return 1

    for function in functions:
        print(f"Building {image_reference(function, sha)} for {PLATFORM}")
        subprocess.run(build_command(docker, function, sha), cwd=ROOT, check=True)

    print("Local images (ID, size in bytes, platform):")
    for function in functions:
        details = subprocess.run(
            inspect_command(docker, function, sha),
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        print(f"  {function}: {image_reference(function, sha)} {details}")
    print(
        "The ECR digest for Terraform is the one the registry reports after the "
        "push step; nothing was pushed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
