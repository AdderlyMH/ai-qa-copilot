"""informed-v4 and OpenAI support in the provider-comparison workflow (ADR-016).

Static checks and executed copies of the workflow's Python steps; no workflow,
provider or network call.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_evaluation_provider_comparison_workflow import (  # noqa: E402
    job,
    run_script,
    run_validation,
    step,
    steps,
    workflow_text,
)


ROOT = Path(__file__).resolve().parents[3]
V4_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v4.yaml"
REVIEW_RECORD = ROOT / "fixtures/benchmark/evaluation-v4-review.v1.yaml"
OPENAI_STEP = "Run evaluation (OpenAI)"
CLAUDE_STEP = "Run evaluation"


def v4_cases() -> list[dict[str, object]]:
    corpus = yaml.safe_load(V4_FIXTURE.read_text(encoding="utf-8"))
    return cast(list[dict[str, object]], corpus["cases"])


def v4_case_budget() -> Decimal:
    budgets = {
        Decimal(str(cast(dict[str, object], case["expected"])["maximum_expected_cost"]))
        for case in v4_cases()
    }
    assert len(budgets) == 1
    return budgets.pop()


def validate(tmp_path: Path, **inputs: str) -> tuple[int, str, dict[str, str]]:
    result, outputs = run_validation(tmp_path, BASELINE="informed-v4", **inputs)
    return result.returncode, result.stdout, outputs


# Guard values


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_informed_v4_per_call_limit_is_the_v4_case_budget(
    tmp_path: Path, provider: str
) -> None:
    validation = run_script("Validate inputs and spend limits")

    assert v4_case_budget() == Decimal("0.11")
    assert f'("informed-v4", "{provider}"): Decimal("0.11"),' in validation
    accepted = validate(
        tmp_path,
        MODEL_PROVIDER=provider,
        MAX_CALL_COST_USD="0.11",
        MAX_RUN_COST_USD="0.88",
    )
    rejected = validate(
        tmp_path,
        MODEL_PROVIDER=provider,
        MAX_CALL_COST_USD="0.110001",
        MAX_RUN_COST_USD="0.88",
    )

    assert accepted[0] == 0, accepted[1]
    assert rejected[0] != 0
    assert "informed-v4 per-case budget 0.11 USD" in rejected[1]
    assert rejected[2] == {}


@pytest.mark.parametrize(
    ("provider", "scope", "budget", "cap"),
    [
        ("anthropic", "smoke", "0.88", "0.88"),
        ("anthropic", "development", "3.41", "3.41"),
        ("openai", "smoke", "0.88", "0.88"),
        ("openai", "development", "3.41", "3.41"),
        ("openai", "probe", "0.11", "0.22"),
    ],
)
def test_informed_v4_scope_budgets_and_run_limits(
    tmp_path: Path, provider: str, scope: str, budget: str, cap: str
) -> None:
    common = {"MODEL_PROVIDER": provider, "SCOPE": scope, "MAX_CALL_COST_USD": "0.11"}

    at_budget = validate(tmp_path, MAX_RUN_COST_USD=budget, **common)
    at_cap = validate(tmp_path, MAX_RUN_COST_USD=cap, **common)
    # A smaller per-call limit, so the run limit is tested and not call <= run.
    below = validate(
        tmp_path,
        MAX_RUN_COST_USD=str(Decimal(budget) - Decimal("0.000001")),
        **{**common, "MAX_CALL_COST_USD": "0.05"},
    )
    above = validate(
        tmp_path, MAX_RUN_COST_USD=str(Decimal(cap) + Decimal("0.000001")), **common
    )

    assert at_budget[0] == 0, at_budget[1]
    assert at_budget[2]["scope_budget_usd"] == budget
    assert at_budget[2]["prefix"] == f"informed-v4-{provider}-{scope}"
    assert at_cap[0] == 0, at_cap[1]
    assert below[0] != 0 and "must cover" in below[1]
    assert above[0] != 0 and "informed-v4" in above[1] and "run limit" in above[1]
    selected = {"smoke": 8, "development": 31, "probe": 1}[scope]
    assert Decimal(budget) == v4_case_budget() * selected


def test_informed_v4_still_respects_the_hard_maximum(tmp_path: Path) -> None:
    validation = run_script("Validate inputs and spend limits")
    code, stdout, outputs = validate(
        tmp_path, SCOPE="development", MAX_CALL_COST_USD="0.11", MAX_RUN_COST_USD="6.01"
    )

    assert 'HARD_MAX_RUN_COST_USD = Decimal("6.00")' in validation
    assert code != 0 and "hard maximum" in stdout
    assert outputs == {}


# Provider rules


@pytest.mark.parametrize("scope", ["smoke", "development", "probe"])
@pytest.mark.parametrize("baseline", ["b0", "informed"])
def test_openai_is_refused_for_b0_and_informed(
    tmp_path: Path, baseline: str, scope: str
) -> None:
    result, outputs = run_validation(
        tmp_path,
        BASELINE=baseline,
        MODEL_PROVIDER="openai",
        SCOPE=scope,
        MAX_CALL_COST_USD="0.05",
        MAX_RUN_COST_USD="0.80",
    )

    assert result.returncode != 0
    assert f"not available for the {baseline} baseline" in result.stdout
    assert outputs == {}


@pytest.mark.parametrize(
    ("scope", "max_run", "case_ids"),
    [
        (
            "smoke",
            "0.88",
            "EVAL-105 EVAL-101 EVAL-106 EVAL-111 EVAL-112 EVAL-126 EVAL-120 EVAL-131",
        ),
        ("development", "3.41", ""),
        ("probe", "0.22", "EVAL-111"),
    ],
)
def test_openai_is_accepted_only_for_informed_v4(
    tmp_path: Path, scope: str, max_run: str, case_ids: str
) -> None:
    code, stdout, outputs = validate(
        tmp_path,
        MODEL_PROVIDER="openai",
        SCOPE=scope,
        MAX_CALL_COST_USD="0.11",
        MAX_RUN_COST_USD=max_run,
    )

    assert code == 0, stdout
    assert outputs["prefix"] == f"informed-v4-openai-{scope}"
    assert outputs["case_ids"] == case_ids


@pytest.mark.parametrize(
    ("baseline", "provider", "message"),
    [
        ("informed-v4", "anthropic", "probe is only available"),
        ("b0", "anthropic", "scope must be"),
        ("informed", "anthropic", "scope must be"),
    ],
)
def test_probe_is_only_for_informed_v4_with_openai(
    tmp_path: Path, baseline: str, provider: str, message: str
) -> None:
    result, outputs = run_validation(
        tmp_path,
        BASELINE=baseline,
        MODEL_PROVIDER=provider,
        SCOPE="probe",
        MAX_CALL_COST_USD="0.05",
        MAX_RUN_COST_USD="0.22",
    )

    assert result.returncode != 0
    assert message in result.stdout
    assert outputs == {}


def test_b0_and_informed_outputs_have_no_case_list(tmp_path: Path) -> None:
    result, outputs = run_validation(
        tmp_path, BASELINE="informed", MAX_CALL_COST_USD="0.10", MAX_RUN_COST_USD="0.80"
    )

    assert result.returncode == 0, result.stdout
    assert outputs == {"prefix": "informed-anthropic-smoke", "scope_budget_usd": "0.80"}


# Case selection


def _case_list(scope: str) -> list[str]:
    validation = run_script("Validate inputs and spend limits")
    block = validation.split(f'"{scope}": (', 1)[1].split(")", 1)[0]
    return re.findall(r'"(EVAL-\d{3})"', block)


def test_smoke_list_equals_the_review_record() -> None:
    review = yaml.safe_load(REVIEW_RECORD.read_text(encoding="utf-8"))
    recorded = [entry["id"] for entry in review["smoke_cases"]]

    assert _case_list("smoke") == recorded
    assert len(recorded) == 8
    assert set(recorded) <= {cast(str, case["id"]) for case in v4_cases()}


def test_probe_is_the_largest_v4_case_and_development_is_the_whole_fixture() -> None:
    assert _case_list("probe") == ["EVAL-111"]
    assert '"development": (),' in run_script("Validate inputs and spend limits")
    assert len(v4_cases()) == 31
    assert {case["split"] for case in v4_cases()} == {"development"}


def test_report_negative_controls_equal_the_fixture_controls() -> None:
    report = run_script("Report score result without gating")
    controls = {
        cast(str, case["id"])
        for case in v4_cases()
        if "negative_control" in cast(list[str], case["tags"])
    }

    assert controls == {"EVAL-128", "EVAL-129", "EVAL-130", "EVAL-131"}
    assert (
        'INFORMED_V4_NEGATIVE_CONTROLS = {"EVAL-128", "EVAL-129", "EVAL-130", "EVAL-131"}'
        in report
    )


@pytest.mark.parametrize("name", [CLAUDE_STEP, OPENAI_STEP])
def test_informed_v4_selection_comes_only_from_the_validated_plan(name: str) -> None:
    script = run_script(name)
    environment = cast(dict[str, str], step(name)["env"])

    assert environment["CASE_IDS"] == "${{ steps.plan.outputs.case_ids }}"
    assert "for case_id in $CASE_IDS; do" in script
    assert 'selection+=(--case-id "$case_id")' in script
    for case_id in ("EVAL-105", "EVAL-111", "EVAL-131"):
        assert f"--case-id {case_id}" not in script


# Secrets and environments


def test_environment_is_chosen_by_provider() -> None:
    environment = cast(dict[str, str], job()["environment"])["name"]

    assert "inputs.model_provider == 'openai'" in environment
    assert "'openai-evaluation'" in environment
    assert "'c1-evaluation'" in environment
    assert "secrets." not in environment


def test_each_key_is_scoped_to_its_own_provider_run_step() -> None:
    claude = step(CLAUDE_STEP)
    openai = step(OPENAI_STEP)
    claude_env = json.dumps(claude["env"])
    openai_env = json.dumps(openai["env"])

    assert claude["if"] == "inputs.model_provider == 'anthropic'"
    assert openai["if"] == "inputs.model_provider == 'openai'"
    assert "ANTHROPIC_API_KEY" in claude_env and "OPENAI_API_KEY" not in claude_env
    assert "OPENAI_API_KEY" in openai_env and "ANTHROPIC_API_KEY" not in openai_env
    assert "OPENAI_API_KEY" not in cast(str, claude["run"])
    assert "ANTHROPIC_API_KEY" not in cast(str, openai["run"])
    for item in steps():
        if item.get("name") not in (CLAUDE_STEP, OPENAI_STEP):
            assert "API_KEY" not in json.dumps(item)
    assert workflow_text().count("secrets.OPENAI_API_KEY") == 1
    assert workflow_text().count("secrets.ANTHROPIC_API_KEY") == 1


def test_the_openai_key_is_never_echoed() -> None:
    script = run_script(OPENAI_STEP)

    assert "set -euo pipefail" in script
    for line in script.splitlines():
        if "OPENAI_API_KEY" in line:
            assert '[[ -n "${OPENAI_API_KEY:-}" ]]' in line or "::error::" in line
            assert "$OPENAI_API_KEY" not in line.replace('"${OPENAI_API_KEY:-}"', "")


# OpenAI run, scoring, provenance and report


def test_openai_step_runs_v4_through_the_openai_factory() -> None:
    script = run_script(OPENAI_STEP)
    environment = cast(dict[str, str], step(OPENAI_STEP)["env"])
    informed = {
        k: v for k, v in environment.items() if k.startswith("AI_QA_COPILOT_INFORMED_")
    }

    assert informed == {
        "AI_QA_COPILOT_INFORMED_MODEL_FACTORY": (
            "ai_qa_copilot_api.informed_openai_evaluation_model:"
            "create_informed_openai_model"
        ),
        "AI_QA_COPILOT_INFORMED_PRICING_PATH": (
            "fixtures/benchmark/pricing/openai-gpt-6-1-sol.v1.yaml"
        ),
        "AI_QA_COPILOT_INFORMED_MAX_CALL_COST_USD": "${{ inputs.max_call_cost_usd }}",
        "AI_QA_COPILOT_INFORMED_MAX_RUN_COST_USD": "${{ inputs.max_run_cost_usd }}",
        "AI_QA_COPILOT_INFORMED_CALL_LEDGER_PATH": (
            "artifacts/${{ steps.plan.outputs.prefix }}-ledger.jsonl"
        ),
        "AI_QA_COPILOT_INFORMED_CONFIG_PATH": (
            "fixtures/benchmark/baselines/informed-single-prompt.v1.yaml"
        ),
        "AI_QA_COPILOT_INFORMED_REPOSITORY_ROOT": ".",
    }
    assert "--fixture fixtures/benchmark/evaluation-cases.v4.yaml" in script
    assert (
        "--executor ai_qa_copilot_api.informed_baseline:create_informed_baseline_executor"
        in script
    )
    assert script.count("--max-concurrency 1") == 1
    assert 'if [[ "$BASELINE" != "informed-v4" ]]; then' in script
    assert "evaluation-cases.v2.yaml" not in script
    assert "evaluation-cases.v3.yaml" not in script


def test_claude_step_runs_informed_v4_on_the_v4_fixture() -> None:
    script = run_script(CLAUDE_STEP)
    branch = script.split("informed-v4)", 1)[1].split(";;", 1)[0]

    assert "--fixture fixtures/benchmark/evaluation-cases.v4.yaml" in branch
    assert "create_informed_baseline_executor" in branch


def test_scoring_uses_v4_and_never_scores_a_probe() -> None:
    script = run_script("Score run report")

    assert (
        "informed-v4) fixture=fixtures/benchmark/evaluation-cases.v4.yaml ;;" in script
    )
    probe = script.index('if [[ "$SCOPE" == "probe" ]]; then')
    assert probe < script.index("scripts/score_evaluation_run.py")
    assert cast(dict[str, str], step("Score run report")["env"])["SCOPE"] == (
        "${{ inputs.scope }}"
    )


def test_provenance_is_recorded_with_the_matching_provider() -> None:
    script = run_script("Record run provenance")
    branch = script.split("informed-v4)", 1)[1].rsplit("*)", 1)[0]

    assert (
        "anthropic) pricing=fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml ;;"
        in branch
    )
    assert (
        "openai) pricing=fixtures/benchmark/pricing/openai-gpt-6-1-sol.v1.yaml ;;"
        in branch
    )
    assert '--provider "$MODEL_PROVIDER"' in branch
    assert "--fixture fixtures/benchmark/evaluation-cases.v4.yaml" in branch
    assert "scripts/record_informed_evaluation_provenance.py" in branch
    assert cast(dict[str, str], step("Record run provenance")["env"])[
        "MODEL_PROVIDER"
    ] == ("${{ inputs.model_provider }}")


def test_every_step_receives_the_baseline_through_env() -> None:
    for name in (OPENAI_STEP, "Report score result without gating"):
        environment = cast(dict[str, str], step(name)["env"])
        assert environment["BASELINE"] == "${{ inputs.baseline }}"


def test_artifact_prefixes_include_baseline_and_provider() -> None:
    validation = run_script("Validate inputs and spend limits")

    assert '"anthropic": "informed-v4-anthropic"' in validation
    assert '"openai": "informed-v4-openai"' in validation
    assert 'prefix = f"{INFORMED_V4_ARTIFACT_PREFIX[provider]}-{scope}"' in validation


def run_report(
    tmp_path: Path, scope: str, scores: list[dict[str, object]] | None
) -> str:
    script = run_script("Report score result without gating")
    match = re.search(r"python - <<'PY'\n(.*)\nPY", script, re.DOTALL)
    assert match is not None
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    if scores is not None:
        (artifacts / "x-score.json").write_text(
            json.dumps({"passed": False, "scores": scores}), encoding="utf-8"
        )
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "GITHUB_STEP_SUMMARY": str(summary),
        "BASELINE": "informed-v4",
        "SCOPE": scope,
        "PREFIX": "x",
    }
    result = subprocess.run(
        [sys.executable, "-c", match.group(1)],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return summary.read_text(encoding="utf-8")


def _score(case_id: str, **passed: bool) -> dict[str, object]:
    codes = (
        "required_ground_truth_ids",
        "unexpected_ground_truth_ids",
        "expected_source_references",
        "policy_boundary",
        "side_effects",
    )
    return {
        "case_id": case_id,
        "passed": all(passed.get(code, True) for code in codes),
        "checks": [{"code": code, "passed": passed.get(code, True)} for code in codes],
    }


def test_informed_v4_report_shows_only_the_four_checks_with_denominators(
    tmp_path: Path,
) -> None:
    summary = run_report(
        tmp_path,
        "smoke",
        [
            _score("EVAL-101", expected_source_references=False),
            _score("EVAL-120", side_effects=False),
            _score("EVAL-131", unexpected_ground_truth_ids=False),
        ],
    )

    assert "Required IDs: 2 of 2" in summary
    assert "No unexpected IDs: 2 of 3" in summary
    assert "Source references: 1 of 2" in summary
    assert "Boundary: 3 of 3" in summary
    assert "results_not_independently_validated" in summary
    assert "not B1, B2 or gate evidence" in summary
    assert "Score report passed" not in summary
    assert "cases passed" not in summary.lower()
    assert "side_effects" not in summary


def test_probe_report_makes_no_score_claim(tmp_path: Path) -> None:
    summary = run_report(tmp_path, "probe", [_score("EVAL-111")])

    assert "no score is reported" in summary
    assert " of " not in summary
    assert "passed" not in summary.lower()


def test_no_step_prints_a_cases_passed_headline() -> None:
    assert "cases passed" not in workflow_text().lower()
