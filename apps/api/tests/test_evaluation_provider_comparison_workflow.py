"""Static and behavioral safety checks for the provider-comparison workflow."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
COMPARISON_WORKFLOW = WORKFLOWS / "evaluation-provider-comparison.yml"
CHECKOUT_ACTION = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_PYTHON_ACTION = "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405"
UPLOAD_ARTIFACT_ACTION = (
    "actions/upload-artifact@65c4c4a1ddee5b72f698fdd19549f0f0fb45cf08"
)

# SHA-256 of the committed (LF) bytes. Windows checkouts may use CRLF, so line
# endings are normalized before hashing; any content change fails this pin.
UNCHANGED_WORKFLOW_SHA256 = {
    "evaluation-smoke.yml": (
        "67ad1497c1f77a3fa4c164505b417ad6c1fea126ffdce94eb3180a367289f90a"
    ),
    "evaluation-release.yml": (
        "684b13cd308a0b3a52c0e3435f8781a4f1acb50b113570f06f8227896e0ed2ce"
    ),
}


def workflow_text() -> str:
    return COMPARISON_WORKFLOW.read_text(encoding="utf-8")


def workflow() -> dict[object, object]:
    return cast(dict[object, object], yaml.safe_load(workflow_text()))


def job() -> dict[str, object]:
    jobs = cast(dict[str, dict[str, object]], workflow()["jobs"])
    assert list(jobs) == ["evaluate"]
    return jobs["evaluate"]


def steps() -> list[dict[str, object]]:
    return cast(list[dict[str, object]], job()["steps"])


def step(name: str) -> dict[str, object]:
    matches = [item for item in steps() if item.get("name") == name]
    assert len(matches) == 1, f"Expected exactly one step named {name}"
    return matches[0]


def run_script(name: str) -> str:
    return cast(str, step(name)["run"])


# Triggers, permissions, and job settings


def test_triggers_are_exactly_workflow_dispatch() -> None:
    # PyYAML reads the bare ``on`` key as boolean True.
    triggers = cast(dict[str, object], workflow()[True])

    assert list(triggers) == ["workflow_dispatch"]
    for forbidden in ("push:", "pull_request", "schedule:", "workflow_call"):
        assert forbidden not in workflow_text()


def test_inputs_are_bounded_to_the_approved_choices_and_defaults() -> None:
    triggers = cast(dict[str, dict[str, dict[str, object]]], workflow()[True])
    inputs = cast(dict[str, dict[str, object]], triggers["workflow_dispatch"]["inputs"])

    assert set(inputs) == {
        "model_provider",
        "scope",
        "max_call_cost_usd",
        "max_run_cost_usd",
        "openai_b0_model_factory",
    }
    assert inputs["model_provider"]["options"] == ["anthropic", "openai"]
    assert inputs["model_provider"]["default"] == "anthropic"
    assert inputs["scope"]["options"] == ["smoke", "development"]
    assert inputs["scope"]["default"] == "smoke"
    assert inputs["max_call_cost_usd"]["required"] is True
    assert inputs["max_call_cost_usd"]["default"] == "0.09"
    assert inputs["max_run_cost_usd"]["required"] is True
    assert inputs["max_run_cost_usd"]["default"] == "0.72"
    for split in ("validation", "holdout"):
        assert f"--split {split}" not in workflow_text()


def test_permissions_are_read_only_with_environment_and_timeout() -> None:
    assert workflow()["permissions"] == {"contents": "read"}
    evaluate = job()
    assert "permissions" not in evaluate
    assert evaluate["environment"] == {"name": "c1-evaluation"}
    timeout = evaluate["timeout-minutes"]
    assert isinstance(timeout, int)
    assert 0 < timeout <= 120


def test_actions_are_pinned_like_the_existing_evaluation_workflows() -> None:
    uses = [cast(str, item["uses"]) for item in steps() if "uses" in item]

    assert uses == [CHECKOUT_ACTION, SETUP_PYTHON_ACTION, UPLOAD_ARTIFACT_ACTION]
    for action in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action)


# Credentials


def test_provider_key_is_exposed_only_to_the_run_step() -> None:
    document = workflow()
    for key, value in document.items():
        if key != "jobs":
            assert "secrets." not in json.dumps(value, default=str)
    for key, value in job().items():
        if key != "steps":
            assert "secrets." not in json.dumps(value, default=str)

    run_step = step("Run evaluation")
    for item in steps():
        if item.get("name") != "Run evaluation":
            assert "secrets." not in json.dumps(item)
    assert "secrets." not in cast(str, run_step["run"])

    environment = cast(dict[str, str], run_step["env"])
    secret_variables = {
        name for name, value in environment.items() if "secrets." in str(value)
    }
    assert secret_variables == {"ANTHROPIC_API_KEY"}
    assert environment["ANTHROPIC_API_KEY"] == (
        "${{ inputs.model_provider == 'anthropic' && secrets.ANTHROPIC_API_KEY || '' }}"
    )
    assert workflow_text().count("secrets.") == 1
    assert "OPENAI_API_KEY" not in workflow_text()


def test_the_key_is_never_echoed_or_traced() -> None:
    script = run_script("Run evaluation")

    assert "set -x" not in workflow_text()
    assert "set -euo pipefail" in script
    for line in script.splitlines():
        if "ANTHROPIC_API_KEY" in line:
            assert '[[ -n "${ANTHROPIC_API_KEY:-}" ]]' in line or "::error::" in line
            assert "$ANTHROPIC_API_KEY" not in line.replace(
                '"${ANTHROPIC_API_KEY:-}"', ""
            )


# Run, scoring, provenance, and artifacts


def test_run_step_uses_v2_b0_c1_factory_and_concurrency_one() -> None:
    script = run_script("Run evaluation")
    environment = cast(dict[str, str], step("Run evaluation")["env"])

    assert "--max-concurrency 1" in script
    assert script.count("--max-concurrency") == 1
    assert "--fixture fixtures/benchmark/evaluation-cases.v2.yaml" in script
    assert (
        "--executor ai_qa_copilot_api.naive_baseline:create_naive_baseline_executor"
        in script
    )
    assert '--max-expected-cost "$SCOPE_BUDGET_USD"' in script
    assert environment["AI_QA_COPILOT_B0_MODEL_FACTORY"] == (
        "ai_qa_copilot_api.c1_evaluation_model:create_c1_b0_model"
    )
    assert environment["AI_QA_COPILOT_C1_PRICING_PATH"] == (
        "fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml"
    )


def test_provenance_is_recorded_with_every_ledger() -> None:
    script = run_script("Record run provenance")

    assert "scripts/record_evaluation_provenance.py" in script
    assert 'for ledger in artifacts/"${PREFIX}"-ledger*.jsonl' in script
    assert '"${ledger_arguments[@]}"' in script
    assert '--git-commit "$GITHUB_SHA"' in script


def test_score_is_reported_but_never_gates() -> None:
    summary = step("Report score result without gating")

    assert summary["if"] == "always()"
    assert "GITHUB_STEP_SUMMARY" in cast(str, summary["run"])
    assert "is not True" not in workflow_text()
    assert "continue-on-error" not in workflow_text()


def test_artifacts_are_provider_prefixed_and_never_under_reviews() -> None:
    upload = step("Upload evaluation artifacts")
    parameters = cast(dict[str, str], upload["with"])

    assert upload["if"] == "always()"
    assert parameters["name"].startswith("${{ steps.plan.outputs.prefix")
    paths = [line.strip() for line in parameters["path"].splitlines() if line.strip()]
    assert paths == [
        "artifacts/${{ steps.plan.outputs.prefix }}-run.json",
        "artifacts/${{ steps.plan.outputs.prefix }}-score.json",
        "artifacts/${{ steps.plan.outputs.prefix }}-provenance.json",
        "artifacts/${{ steps.plan.outputs.prefix }}-ledger*.jsonl",
    ]
    validation = run_script("Validate inputs and spend limits")
    assert 'ARTIFACT_PREFIX = {"anthropic": "c1", "openai": "b0-openai"}' in validation
    assert "evaluation/reviews" not in workflow_text()


# Existing workflows


@pytest.mark.parametrize("name", sorted(UNCHANGED_WORKFLOW_SHA256))
def test_existing_evaluation_workflows_are_unchanged(name: str) -> None:
    content = (WORKFLOWS / name).read_bytes().replace(b"\r\n", b"\n")

    assert hashlib.sha256(content).hexdigest() == UNCHANGED_WORKFLOW_SHA256[name]


# Validation script behavior (extracted from the workflow and executed)


def run_validation(
    tmp_path: Path, **inputs: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    script = run_script("Validate inputs and spend limits")
    match = re.search(r"python - <<'PY'\n(.*)\nPY", script, re.DOTALL)
    assert match is not None
    output_file = tmp_path / "github-output"
    output_file.write_text("", encoding="utf-8")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "GITHUB_OUTPUT": str(output_file),
        "MODEL_PROVIDER": "anthropic",
        "SCOPE": "smoke",
        "MAX_CALL_COST_USD": "0.09",
        "MAX_RUN_COST_USD": "0.72",
        "OPENAI_B0_MODEL_FACTORY": "",
    }
    environment.update(inputs)
    result = subprocess.run(
        [sys.executable, "-c", match.group(1)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    outputs = dict(
        line.split("=", 1)
        for line in output_file.read_text(encoding="utf-8").splitlines()
    )
    return result, outputs


def test_hard_maximum_on_the_run_limit_exists() -> None:
    validation = run_script("Validate inputs and spend limits")

    assert 'HARD_MAX_RUN_COST_USD = Decimal("6.00")' in validation
    assert 'if limits["MAX_RUN_COST_USD"] > HARD_MAX_RUN_COST_USD:' in validation


@pytest.mark.parametrize(
    ("scope", "max_run", "prefix", "budget"),
    [
        ("smoke", "0.72", "c1-smoke", "0.72"),
        ("development", "5.40", "c1-development", "5.40"),
        ("development", "6.00", "c1-development", "5.40"),
    ],
)
def test_validation_accepts_approved_limits(
    tmp_path: Path, scope: str, max_run: str, prefix: str, budget: str
) -> None:
    result, outputs = run_validation(tmp_path, SCOPE=scope, MAX_RUN_COST_USD=max_run)

    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs == {"prefix": prefix, "scope_budget_usd": budget}


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ({"MAX_RUN_COST_USD": "6.01"}, "hard maximum"),
        ({"MAX_RUN_COST_USD": "60"}, "hard maximum"),
        ({"MAX_RUN_COST_USD": "1e3"}, "positive USD amount"),
        ({"MAX_RUN_COST_USD": "0"}, "positive USD amount"),
        ({"MAX_CALL_COST_USD": "-0.09"}, "positive USD amount"),
        ({"MAX_CALL_COST_USD": "1.00"}, "cannot exceed"),
        ({"SCOPE": "development", "MAX_RUN_COST_USD": "0.72"}, "must cover"),
        ({"SCOPE": "holdout"}, "scope must be"),
        ({"MODEL_PROVIDER": "openai"}, "not yet identified"),
        (
            {
                "MODEL_PROVIDER": "openai",
                "OPENAI_B0_MODEL_FACTORY": "external_module:create_model",
            },
            "not yet supported",
        ),
    ],
)
def test_validation_rejects_unsafe_inputs(
    tmp_path: Path, inputs: dict[str, str], message: str
) -> None:
    result, outputs = run_validation(tmp_path, **inputs)

    assert result.returncode != 0
    assert message in result.stdout
    assert outputs == {}
