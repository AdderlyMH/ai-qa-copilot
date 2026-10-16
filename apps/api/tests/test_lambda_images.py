"""Contract tests for the INFRA-009 Lambda images; Docker is not required."""

from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "apps/api/Dockerfile.lambda"
DOCKERIGNORE = ROOT / "apps/api/Dockerfile.lambda.dockerignore"
BUILD_SCRIPT = ROOT / "scripts/build_lambda_images.py"
COMPUTE_MODULE = ROOT / "infra/modules/compute_api/main.tf"

EXPECTED_HANDLERS = {
    "api": "ai_qa_copilot_api.lambda_api.handler",
    "parser": "ai_qa_copilot_api.lambda_workers.parser_handler",
    "general": "ai_qa_copilot_api.lambda_workers.general_handler",
    "executor": "ai_qa_copilot_api.lambda_workers.executor_handler",
}
SECRET_NAME = re.compile(
    r"(SECRET|PASSWORD|TOKEN|API_KEY|ACCESS_KEY|DATABASE_URL|AWS_|SSLROOTCERT)",
    re.IGNORECASE,
)


def dockerfile_instructions() -> list[str]:
    """Return Dockerfile instructions with comments removed and continuations joined."""

    joined = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def load_build_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_lambda_images", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_base_image_is_the_arm64_lambda_python_313_image_pinned_by_digest() -> None:
    instructions = dockerfile_instructions()
    base_args = [
        line for line in instructions if line.startswith("ARG LAMBDA_PYTHON_BASE=")
    ]

    assert len(base_args) == 1
    assert re.fullmatch(
        r"ARG LAMBDA_PYTHON_BASE=public\.ecr\.aws/lambda/python:3\.13-arm64@sha256:[0-9a-f]{64}",
        base_args[0],
    )
    external_froms = [
        line
        for line in instructions
        if line.startswith("FROM ") and not line.startswith("FROM runtime ")
    ]
    assert external_froms == [
        "FROM ${LAMBDA_PYTHON_BASE} AS dependencies",
        "FROM ${LAMBDA_PYTHON_BASE} AS runtime",
    ]


def test_each_function_target_sets_only_its_handler() -> None:
    instructions = dockerfile_instructions()
    targets: dict[str, list[str]] = {}
    current: str | None = None
    for line in instructions:
        match = re.fullmatch(r"FROM runtime AS (\w+)", line)
        if match:
            current = match.group(1)
            targets[current] = []
        elif line.startswith("FROM "):
            current = None
        elif current is not None:
            targets[current].append(line)

    assert targets == {
        function: [f'CMD ["{handler}"]']
        for function, handler in EXPECTED_HANDLERS.items()
    }


@pytest.mark.parametrize("handler_path", sorted(EXPECTED_HANDLERS.values()))
def test_each_handler_path_resolves_to_a_callable(handler_path: str) -> None:
    module_name, attribute = handler_path.rsplit(".", 1)
    module = importlib.import_module(module_name)

    assert callable(getattr(module, attribute))


def test_function_classes_match_the_terraform_image_uris_keys() -> None:
    terraform = COMPUTE_MODULE.read_text(encoding="utf-8")

    assert (
        'toset(keys(var.image_uris)) == toset(["api", "parser", "general", "executor"])'
        in terraform
    )
    assert set(load_build_script().FUNCTIONS) == set(EXPECTED_HANDLERS)


def test_dependencies_are_installed_from_the_lock_without_dev_or_compilation() -> None:
    text = " ".join(dockerfile_instructions())

    assert "uv==0.11.16" in text
    assert "uv export --locked --no-dev --no-emit-workspace" in text
    assert "--require-hashes" in text
    assert "--only-binary=:all:" in text
    assert "--no-deps" in text
    assert "uv sync" not in text
    assert "--group dev" not in text and "--all-groups" not in text


def test_only_lock_inputs_and_the_application_package_are_copied() -> None:
    copies = [line for line in dockerfile_instructions() if line.startswith("COPY ")]

    assert copies == [
        "COPY pyproject.toml uv.lock ./",
        "COPY apps/api/pyproject.toml apps/api/pyproject.toml",
        "COPY --from=dependencies /build/site-packages ${LAMBDA_TASK_ROOT}",
        "COPY apps/api/src/ai_qa_copilot_api ${LAMBDA_TASK_ROOT}/ai_qa_copilot_api",
    ]
    assert not any(line.startswith("ADD ") for line in dockerfile_instructions())


def test_no_secret_credential_or_database_setting_is_baked_in() -> None:
    instructions = dockerfile_instructions()
    settings = [
        line for line in instructions if line.startswith(("ENV ", "ARG ", "LABEL "))
    ]

    for line in settings:
        assert not SECRET_NAME.search(line.split("=", 1)[0]), line
    assert not any(".env" in line for line in instructions if line.startswith("COPY "))
    assert not any(
        token in " ".join(instructions)
        for token in ("/.aws", "credentials", "rds-ca", "global-bundle", ".pem")
    )


def test_no_user_instruction_switches_to_root() -> None:
    users = [line for line in dockerfile_instructions() if line.startswith("USER ")]

    assert not any(line.split()[1].split(":")[0] in {"0", "root"} for line in users)


def test_dockerignore_is_an_allowlist_that_excludes_local_and_repository_noise() -> (
    None
):
    lines = [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert lines[0] == "*"
    assert [line for line in lines if line.startswith("!")] == [
        "!pyproject.toml",
        "!uv.lock",
        "!apps/api/pyproject.toml",
        "!apps/api/src/ai_qa_copilot_api/**",
    ]
    for excluded in (
        "**/.env",
        "**/.env.*",
        ".git",
        "apps/api/tests",
        "docs",
        "infra",
        "node_modules",
        "HANDOFF*.md",
        "**/__pycache__",
    ):
        assert excluded in lines


def test_build_command_targets_arm64_without_provenance_and_never_pushes() -> None:
    script = load_build_script()
    command = script.build_command("docker", "parser", "a" * 40)

    assert command[:3] == ["docker", "buildx", "build"]
    assert command[command.index("--platform") + 1] == "linux/arm64"
    assert "--provenance=false" in command
    assert command[command.index("--file") + 1] == "apps/api/Dockerfile.lambda"
    assert command[command.index("--target") + 1] == "parser"
    assert (
        command[command.index("--tag") + 1] == f"ai-qa-copilot-lambda/parser:{'a' * 40}"
    )
    assert "--load" in command
    assert "--push" not in command
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "get-login-password" not in source
    assert '"push"' not in source
    assert "os.environ" not in source and "getenv" not in source


def test_build_inputs_cover_every_copied_source() -> None:
    script = load_build_script()

    for path in (
        "pyproject.toml",
        "uv.lock",
        "apps/api/pyproject.toml",
        "apps/api/src",
        "apps/api/Dockerfile.lambda",
        "apps/api/Dockerfile.lambda.dockerignore",
    ):
        assert path in script.BUILD_INPUTS


def test_build_refuses_uncommitted_build_inputs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_build_script()
    monkeypatch.setattr(script, "commit_sha", lambda: "b" * 40)
    monkeypatch.setattr(script, "uncommitted_build_inputs", lambda: [" M uv.lock"])

    def unexpected_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("docker must not run")

    monkeypatch.setattr(script.subprocess, "run", unexpected_run)

    assert script.main(["--function", "parser"]) == 1
    assert "uv.lock" in capsys.readouterr().err


def test_parser_worker_compose_dockerfile_is_unchanged_by_the_lambda_images() -> None:
    parser_dockerfile = (ROOT / "apps/api/Dockerfile.parser-worker").read_text(
        encoding="utf-8"
    )

    assert parser_dockerfile.startswith("FROM python:3.13.11-slim-bookworm\n")
    assert "lambda" not in parser_dockerfile.lower()
    assert not (ROOT / ".dockerignore").exists()
