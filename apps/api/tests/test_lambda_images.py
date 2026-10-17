"""Contract tests for the Lambda images (INFRA-009, INFRA-012); no Docker needed."""

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
MIGRATE_HANDLER = "ai_qa_copilot_api.lambda_migrate.handler"
SECRET_NAME = re.compile(
    r"(SECRET|PASSWORD|TOKEN|API_KEY|ACCESS_KEY|DATABASE_URL|AWS_|SSLROOTCERT)",
    re.IGNORECASE,
)
RUNTIME_EXPORT = (
    "uv export --locked --no-dev --no-emit-workspace --format requirements-txt"
)
MIGRATE_EXPORT = (
    "uv export --locked --no-dev --group migrate --no-emit-workspace "
    "--format requirements-txt"
)


def dockerfile_instructions() -> list[str]:
    """Return Dockerfile instructions with comments removed and continuations joined."""

    joined = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    return [
        " ".join(line.split())
        for line in joined.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def dockerfile_stages() -> dict[str, tuple[str, list[str]]]:
    """Map each stage name to its FROM source and its instructions."""

    stages: dict[str, tuple[str, list[str]]] = {}
    current: str | None = None
    for line in dockerfile_instructions():
        match = re.fullmatch(r"FROM (\S+) AS (\S+)", line)
        if match:
            current = match.group(2)
            stages[current] = (match.group(1), [])
        elif current is not None:
            stages[current][1].append(line)
    return stages


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
    external = {
        name: source
        for name, (source, _) in dockerfile_stages().items()
        if source != "runtime"
    }
    assert external == {
        "dependencies": "${LAMBDA_PYTHON_BASE}",
        "runtime": "${LAMBDA_PYTHON_BASE}",
        "migrate-dependencies": "${LAMBDA_PYTHON_BASE}",
        "migrate": "${LAMBDA_PYTHON_BASE}",
    }


def test_each_function_target_sets_only_its_handler() -> None:
    targets = {
        name: body
        for name, (source, body) in dockerfile_stages().items()
        if source == "runtime"
    }

    assert targets == {
        function: [f'CMD ["{handler}"]']
        for function, handler in EXPECTED_HANDLERS.items()
    }


def test_the_function_images_are_unchanged_by_the_migrate_target() -> None:
    stages = dockerfile_stages()

    assert [line for line in stages["runtime"][1] if line.startswith("COPY ")] == [
        "COPY --from=dependencies /build/site-packages ${LAMBDA_TASK_ROOT}",
        "COPY apps/api/src/ai_qa_copilot_api ${LAMBDA_TASK_ROOT}/ai_qa_copilot_api",
    ]
    dependencies = " ".join(stages["dependencies"][1])
    assert RUNTIME_EXPORT in dependencies
    assert "--group" not in dependencies
    for name in ("dependencies", "runtime", *EXPECTED_HANDLERS):
        assert not any("alembic" in line for line in stages[name][1]), name


def test_the_migrate_target_adds_alembic_and_the_migrations_only() -> None:
    stages = dockerfile_stages()

    assert MIGRATE_EXPORT in " ".join(stages["migrate-dependencies"][1])
    assert [line for line in stages["migrate"][1] if line.startswith("COPY ")] == [
        "COPY --from=migrate-dependencies /build/site-packages ${LAMBDA_TASK_ROOT}",
        "COPY apps/api/src/ai_qa_copilot_api ${LAMBDA_TASK_ROOT}/ai_qa_copilot_api",
        "COPY apps/api/alembic.ini ${LAMBDA_TASK_ROOT}/migrations/alembic.ini",
        "COPY apps/api/alembic ${LAMBDA_TASK_ROOT}/migrations/alembic",
    ]
    assert stages["migrate"][1][-1] == f'CMD ["{MIGRATE_HANDLER}"]'
    # The scripts must not land in ${LAMBDA_TASK_ROOT}/alembic, where they would
    # shadow the installed alembic package.
    assert not any(
        line.endswith("${LAMBDA_TASK_ROOT}/alembic") for line in stages["migrate"][1]
    )


@pytest.mark.parametrize(
    "handler_path", sorted([*EXPECTED_HANDLERS.values(), MIGRATE_HANDLER])
)
def test_each_handler_path_resolves_to_a_callable(handler_path: str) -> None:
    module_name, attribute = handler_path.rsplit(".", 1)
    module = importlib.import_module(module_name)

    assert callable(getattr(module, attribute))


def test_function_classes_match_the_terraform_image_uris_keys() -> None:
    terraform = COMPUTE_MODULE.read_text(encoding="utf-8")
    script = load_build_script()

    assert (
        'toset(keys(var.image_uris)) == toset(["api", "parser", "general", "executor"])'
        in terraform
    )
    assert set(script.FUNCTIONS) == set(EXPECTED_HANDLERS)
    assert script.TARGETS == (*script.FUNCTIONS, "migrate")


def test_dependencies_are_installed_from_the_lock_without_dev_or_compilation() -> None:
    text = " ".join(dockerfile_instructions())

    assert text.count("uv==0.11.16") == 2
    assert text.count("--require-hashes") == 2
    assert text.count("--only-binary=:all:") == 2
    assert text.count("--no-deps") == 2
    assert text.count("--no-dev") == 2
    assert "uv sync" not in text
    assert "--group dev" not in text and "--all-groups" not in text


def test_only_lock_inputs_application_package_and_migrations_are_copied() -> None:
    copies = [line for line in dockerfile_instructions() if line.startswith("COPY ")]

    assert copies == [
        "COPY pyproject.toml uv.lock ./",
        "COPY apps/api/pyproject.toml apps/api/pyproject.toml",
        "COPY --from=dependencies /build/site-packages ${LAMBDA_TASK_ROOT}",
        "COPY apps/api/src/ai_qa_copilot_api ${LAMBDA_TASK_ROOT}/ai_qa_copilot_api",
        "COPY pyproject.toml uv.lock ./",
        "COPY apps/api/pyproject.toml apps/api/pyproject.toml",
        "COPY --from=migrate-dependencies /build/site-packages ${LAMBDA_TASK_ROOT}",
        "COPY apps/api/src/ai_qa_copilot_api ${LAMBDA_TASK_ROOT}/ai_qa_copilot_api",
        "COPY apps/api/alembic.ini ${LAMBDA_TASK_ROOT}/migrations/alembic.ini",
        "COPY apps/api/alembic ${LAMBDA_TASK_ROOT}/migrations/alembic",
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
        "!apps/api/alembic.ini",
        "!apps/api/alembic/**",
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


def test_migrate_is_built_only_when_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_build_script()
    monkeypatch.setattr(script, "commit_sha", lambda: "c" * 40)

    assert script.main(["--dry-run"]) == 0
    default = capsys.readouterr().out
    assert script.main(["--dry-run", "--function", "migrate"]) == 0
    named = capsys.readouterr().out

    assert "--target migrate" not in default
    assert default.count("--target ") == 4
    assert f"--target migrate --tag ai-qa-copilot-lambda/migrate:{'c' * 40}" in named


def test_build_inputs_cover_every_copied_source() -> None:
    script = load_build_script()

    for path in (
        "pyproject.toml",
        "uv.lock",
        "apps/api/pyproject.toml",
        "apps/api/src",
        "apps/api/alembic.ini",
        "apps/api/alembic",
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
