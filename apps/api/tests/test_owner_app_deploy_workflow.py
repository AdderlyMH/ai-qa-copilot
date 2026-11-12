"""Static and behavioral safety checks for the owner-app deploy workflow (ADR-022)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import cast

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
DEPLOY_WORKFLOW = WORKFLOWS / "deploy-owner-app.yml"
APPLICATION_CI = WORKFLOWS / "application-ci.yml"
NEXT_CONFIG = ROOT / "apps/web/next.config.ts"
INFRASTRUCTURE = ROOT / "docs/INFRASTRUCTURE.md"
ADR_022 = ROOT / "docs/adr/ADR-022-owner-app-frontend-host.md"
PRODUCTION_ROOT = ROOT / "infra/environments/production/main.tf"

WRANGLER_ACTION = "cloudflare/wrangler-action@953926a2e2182532811c01a25e53647d93bf07c0"
SECRET_NAMES = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")
DEPLOY_STEP = "Deploy to Cloudflare Pages"
VALIDATION_STEP = "Validate build variables"
BUILD_STEP = "Build the static export"
OUTPUT_STEP = "Check the build output"
RUNBOOK_HEADING = "## Owner-app deployment runbook (INFRA-010 stage 6b, owner-run)"

# SHA-256 of the committed (LF) bytes, as in
# test_evaluation_provider_comparison_workflow.py: line endings are normalized
# for Windows checkouts, and any content change fails this pin.
UNCHANGED_WORKFLOW_SHA256 = {
    "evaluation-smoke.yml": (
        "67ad1497c1f77a3fa4c164505b417ad6c1fea126ffdce94eb3180a367289f90a"
    ),
    "evaluation-release.yml": (
        "684b13cd308a0b3a52c0e3435f8781a4f1acb50b113570f06f8227896e0ed2ce"
    ),
    "evaluation-provider-comparison.yml": (
        "5a50a0319fb3057d7ea4a76ea32a24f1ba502862a51e257f9608f158b9ddca89"
    ),
    "docs-validation.yml": (
        "b50713172cd9b7e8f01db9824e862ef6e4847f06305a9997e0a8bdf90645cd12"  # updated 2026-11-12 for the actions/setup-python 7.1.0 pin bump (Dependabot #231)
    ),
}

VALID_VARIABLES = {
    "NEXT_PUBLIC_API_BASE_URL": "https://api.example.invalid",
    "NEXT_PUBLIC_COGNITO_DOMAIN": "https://auth.example.invalid",
    "NEXT_PUBLIC_COGNITO_CLIENT_ID": "client-id.example.invalid",
    "NEXT_PUBLIC_AUTH_REDIRECT_URI": "https://app.example.invalid/",
    "NEXT_PUBLIC_AUTH_LOGOUT_URI": "https://app.example.invalid/",
    "CLOUDFLARE_PAGES_PROJECT": "owner-app-placeholder",
}

# Anything that could be a real host, account or client: a URL with a host other
# than the documented placeholder, a hostname on a common public suffix, or a
# 32-character hex account ID.
URL_WITH_HOST = re.compile(r"https?://(?!app\.<owner-domain>)[a-z0-9]", re.IGNORECASE)
PUBLIC_HOSTNAME = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|app|ai|co|cloud)\b",
    re.IGNORECASE,
)
ACCOUNT_ID = re.compile(r"\b[0-9a-f]{32}\b")


def workflow_text() -> str:
    return DEPLOY_WORKFLOW.read_text(encoding="utf-8")


def workflow() -> dict[object, object]:
    return cast(dict[object, object], yaml.safe_load(workflow_text()))


def jobs() -> dict[str, dict[str, object]]:
    return cast(dict[str, dict[str, object]], workflow()["jobs"])


def steps() -> list[dict[str, object]]:
    return cast(list[dict[str, object]], jobs()["deploy"]["steps"])


def step(name: str) -> dict[str, object]:
    matches = [item for item in steps() if item.get("name") == name]
    assert len(matches) == 1, f"Expected exactly one step named {name}"
    return matches[0]


def run_script(name: str) -> str:
    return cast(str, step(name)["run"])


def next_config_variables() -> set[str]:
    return set(
        re.findall(
            r"process\.env\.(NEXT_PUBLIC_[A-Z_]+)",
            NEXT_CONFIG.read_text(encoding="utf-8"),
        )
    )


def runbook() -> str:
    text = INFRASTRUCTURE.read_text(encoding="utf-8")
    section = text[text.index(RUNBOOK_HEADING) :]
    next_heading = section.index("\n## ", len(RUNBOOK_HEADING))
    return section[:next_heading]


# Triggers, permissions and job settings


def test_triggers_are_exactly_workflow_dispatch() -> None:
    # PyYAML reads the bare ``on`` key as boolean True.
    triggers = cast(dict[str, object], workflow()[True])

    assert list(triggers) == ["workflow_dispatch"]
    assert triggers["workflow_dispatch"] is None
    for forbidden in (
        "push:",
        "pull_request",
        "schedule:",
        "workflow_run",
        "workflow_call",
        "repository_dispatch",
    ):
        assert forbidden not in workflow_text()


def test_permissions_are_exactly_contents_read() -> None:
    assert workflow()["permissions"] == {"contents": "read"}
    for job in jobs().values():
        assert "permissions" not in job


def test_two_deploys_cannot_overlap() -> None:
    assert workflow()["concurrency"] == {
        "group": "deploy-owner-app",
        "cancel-in-progress": False,
    }


def test_deploy_runs_only_from_main_and_other_refs_say_why() -> None:
    assert set(jobs()) == {"deploy", "refuse-non-main"}
    assert jobs()["deploy"]["if"] == "github.ref == 'refs/heads/main'"

    refuse = jobs()["refuse-non-main"]
    assert refuse["if"] == "github.ref != 'refs/heads/main'"
    assert "environment" not in refuse
    refuse_steps = cast(list[dict[str, object]], refuse["steps"])
    assert len(refuse_steps) == 1
    assert "uses" not in refuse_steps[0]
    assert "::notice::Nothing was deployed" in cast(str, refuse_steps[0]["run"])
    assert "${{" not in json.dumps(refuse_steps)


def test_environment_is_owner_app_deploy() -> None:
    assert jobs()["deploy"]["environment"] == {"name": "owner-app-deploy"}


def test_runners_are_pinned_like_application_ci() -> None:
    assert "ubuntu-latest" not in workflow_text()
    ci = yaml.safe_load(APPLICATION_CI.read_text(encoding="utf-8"))
    for job in jobs().values():
        assert job["runs-on"] == ci["jobs"]["quality"]["runs-on"]
        timeout = job["timeout-minutes"]
        assert isinstance(timeout, int)
        assert 0 < timeout <= 30


# Actions


def test_every_action_is_pinned_to_a_full_sha_with_a_version_comment() -> None:
    lines = [line for line in workflow_text().splitlines() if "uses:" in line]

    assert len(lines) == 3
    for line in lines:
        assert re.fullmatch(
            r"\s+(?:- )?uses: [\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", line
        ), line


def test_checkout_and_setup_node_use_the_application_ci_pins() -> None:
    ci = APPLICATION_CI.read_text(encoding="utf-8")
    uses = [cast(str, item["uses"]) for item in steps() if "uses" in item]

    assert len(uses) == 3
    for action in uses[:2]:
        assert re.search(rf"uses: {re.escape(action)} # v", ci), action
    assert uses[2] == WRANGLER_ACTION
    assert f"{WRANGLER_ACTION} # v4.1.3" in workflow_text()


def test_checkout_drops_credentials_and_node_uses_the_repository_version() -> None:
    checkout = cast(dict[str, object], step("Check out the selected commit")["with"])
    setup = cast(dict[str, object], step("Set up Node")["with"])

    assert checkout == {"persist-credentials": False}
    assert setup["node-version-file"] == ".node-version"
    assert "cache" not in setup


def test_wrangler_version_is_exact() -> None:
    parameters = cast(dict[str, object], step(DEPLOY_STEP)["with"])

    assert parameters["wranglerVersion"] == "4.158.0"


def test_deploy_command_is_a_pages_deploy_of_the_export_on_main() -> None:
    parameters = cast(dict[str, str], step(DEPLOY_STEP)["with"])

    assert parameters["command"] == (
        "pages deploy apps/web/out "
        "--project-name=${{ vars.CLOUDFLARE_PAGES_PROJECT }} --branch=main"
    )


def test_step_order_is_install_validate_build_check_deploy() -> None:
    assert [item["name"] for item in steps()] == [
        "Check out the selected commit",
        "Set up Node",
        "Install locked dependencies",
        VALIDATION_STEP,
        BUILD_STEP,
        OUTPUT_STEP,
        DEPLOY_STEP,
    ]
    assert run_script("Install locked dependencies") == "npm ci"


# Secrets and variables


def test_secrets_appear_only_as_deploy_step_inputs() -> None:
    document = workflow()
    for key, value in document.items():
        if key != "jobs":
            assert "secrets." not in json.dumps(value, default=str)
    for job_name, job in jobs().items():
        for key, value in job.items():
            if key == "steps" and job_name == "deploy":
                continue
            assert "secrets." not in json.dumps(value, default=str)
    for item in steps():
        if item.get("name") != DEPLOY_STEP:
            text = json.dumps(item)
            assert "secrets." not in text
            for name in SECRET_NAMES:
                assert name not in text

    deploy = step(DEPLOY_STEP)
    assert "run" not in deploy
    assert "env" not in deploy
    parameters = cast(dict[str, str], deploy["with"])
    assert parameters["apiToken"] == "${{ secrets.CLOUDFLARE_API_TOKEN }}"
    assert parameters["accountId"] == "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
    assert workflow_text().count("secrets.") == 2
    for name in SECRET_NAMES:
        assert workflow_text().count(name) == 1


def test_no_step_exposes_or_traces_anything() -> None:
    text = workflow_text()

    assert "set -x" not in text
    assert "outputs:" not in text
    assert "GITHUB_OUTPUT" not in text
    assert "GITHUB_ENV" not in text
    assert "continue-on-error" not in text
    assert "upload-artifact" not in text
    assert "always()" not in text


def test_expressions_are_never_interpolated_into_shell_commands() -> None:
    for item in steps():
        if "run" in item:
            assert "${{" not in cast(str, item["run"]), item.get("name")


def test_build_variables_are_vars_matching_what_next_config_validates() -> None:
    names = next_config_variables()

    assert len(names) == 5
    for name, extra in (
        (VALIDATION_STEP, {"CLOUDFLARE_PAGES_PROJECT"}),
        (BUILD_STEP, set()),
    ):
        environment = cast(dict[str, str], step(name)["env"])
        assert set(environment) == names | extra
        for variable, value in environment.items():
            assert value == f"${{{{ vars.{variable} }}}}"


# Build


def test_build_uses_the_npm_script_and_never_a_bare_next_build() -> None:
    assert run_script(BUILD_STEP) == "npm run build --workspace @ai-qa-copilot/web"
    assert "next build" not in workflow_text()
    assert "npx " not in workflow_text()


def test_workflow_never_selects_the_demo_build() -> None:
    assert "PUBLIC_DEMO_MODE" not in workflow_text()
    assert "guest_demo" not in workflow_text()


def test_build_output_check_requires_the_files_and_rejects_unsafe_inline() -> None:
    script = run_script(OUTPUT_STEP)

    assert "set -euo pipefail" in script
    assert "apps/web/out/index.html" in script
    assert "apps/web/out/_headers" in script
    assert 'grep -qF "unsafe-inline" apps/web/out/_headers' in script
    assert script.count("exit 1") == 2


def run_output_check(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available")
    return subprocess.run(
        [bash, "-c", run_script(OUTPUT_STEP)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_build_output_check_behavior(tmp_path: Path) -> None:
    out = tmp_path / "apps/web/out"
    out.mkdir(parents=True)

    assert run_output_check(tmp_path).returncode != 0
    (out / "index.html").write_text("<html></html>", encoding="utf-8")
    missing = run_output_check(tmp_path)
    assert missing.returncode != 0
    assert "_headers was not produced" in missing.stdout

    (out / "_headers").write_text(
        "/*\n  Content-Security-Policy: script-src 'self'\n", encoding="utf-8"
    )
    assert run_output_check(tmp_path).returncode == 0

    (out / "_headers").write_text(
        "/*\n  Content-Security-Policy: script-src 'unsafe-inline'\n", encoding="utf-8"
    )
    rejected = run_output_check(tmp_path)
    assert rejected.returncode != 0
    assert "must not allow unsafe-inline" in rejected.stdout


# Validation script behavior (extracted from the workflow and executed)


def run_validation(**overrides: str | None) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    match = re.search(
        r"node - <<'JS'\n(.*)\nJS", run_script(VALIDATION_STEP), re.DOTALL
    )
    assert match is not None
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        **VALID_VARIABLES,
    }
    for name, value in overrides.items():
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    return subprocess.run(
        [node, "-"],
        input=match.group(1),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_validation_accepts_valid_placeholders() -> None:
    result = run_validation()

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("name", sorted(VALID_VARIABLES))
@pytest.mark.parametrize("value", [None, ""])
def test_validation_rejects_a_missing_variable(name: str, value: str | None) -> None:
    result = run_validation(**{name: value})

    assert result.returncode != 0
    assert f"::error::{name} must be" in result.stdout


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NEXT_PUBLIC_API_BASE_URL", "http://api.example.invalid"),
        ("NEXT_PUBLIC_API_BASE_URL", "https://api.example.invalid/"),
        ("NEXT_PUBLIC_API_BASE_URL", "not a url"),
        ("NEXT_PUBLIC_COGNITO_DOMAIN", "http://auth.example.invalid"),
        ("NEXT_PUBLIC_COGNITO_DOMAIN", "https://auth.example.invalid/"),
        ("NEXT_PUBLIC_COGNITO_DOMAIN", "https://auth.example.invalid/path"),
        ("NEXT_PUBLIC_COGNITO_CLIENT_ID", "   "),
        ("NEXT_PUBLIC_AUTH_REDIRECT_URI", "http://app.example.invalid/"),
        ("NEXT_PUBLIC_AUTH_REDIRECT_URI", "https://app.example.invalid"),
        ("NEXT_PUBLIC_AUTH_REDIRECT_URI", "https://app.example.invalid/callback"),
        ("NEXT_PUBLIC_AUTH_LOGOUT_URI", "http://app.example.invalid/"),
        ("NEXT_PUBLIC_AUTH_LOGOUT_URI", "https://app.example.invalid"),
        ("NEXT_PUBLIC_AUTH_LOGOUT_URI", "https://app.example.invalid/?x=1"),
        ("CLOUDFLARE_PAGES_PROJECT", "Owner_App"),
        ("CLOUDFLARE_PAGES_PROJECT", "owner-app --branch=other"),
        ("CLOUDFLARE_PAGES_PROJECT", "-owner-app"),
    ],
)
def test_validation_rejects_malformed_values_without_printing_them(
    name: str, value: str
) -> None:
    result = run_validation(**{name: value})

    assert result.returncode != 0
    assert f"::error::{name} must be" in result.stdout
    assert value.strip() == "" or value not in result.stdout + result.stderr


# Nothing real in the repository


def test_workflow_has_no_real_domain_account_or_url() -> None:
    text = workflow_text()

    assert not URL_WITH_HOST.search(text)
    assert not PUBLIC_HOSTNAME.search(text)
    assert not ACCOUNT_ID.search(text)


def test_runbook_has_no_real_domain_account_or_url() -> None:
    text = runbook()

    assert not URL_WITH_HOST.search(text)
    assert not ACCOUNT_ID.search(text)
    hostnames = {match.group(0) for match in PUBLIC_HOSTNAME.finditer(text)}
    # The platform's default address, with a placeholder for the project.
    assert hostnames <= {"pages.dev"}


# Runbook and ADR


def test_runbook_has_ten_owner_run_steps() -> None:
    text = runbook()
    labels = re.findall(r"^\*\*Step (\d+)\. OWNER RUNS THIS", text, re.MULTILINE)

    assert labels == [str(number) for number in range(1, 11)]
    assert "app.<owner-domain>" in text
    assert "owner-app-deploy" in text
    assert "No step here has been executed" in text


def test_runbook_names_every_secret_variable_and_tfvar() -> None:
    text = runbook()

    for name in (
        *SECRET_NAMES,
        *sorted(next_config_variables()),
        "CLOUDFLARE_PAGES_PROJECT",
        "web_origins",
        "cognito_domain_prefix",
        "cognito_callback_urls",
        "cognito_logout_urls",
    ):
        assert name in text


def test_runbook_outputs_exist_in_the_production_root() -> None:
    root = PRODUCTION_ROOT.read_text(encoding="utf-8")

    for name in re.findall(r"terraform output -raw (\w+)", runbook()):
        assert f'output "{name}"' in root
    assert "terraform output -raw cognito_client_id" in runbook()
    assert "terraform output -raw cognito_domain_base_url" in runbook()


def test_runbook_plan_is_targeted_and_stops_before_apply() -> None:
    text = runbook()

    assert (
        'terraform plan "-var-file=production.tfvars" '
        "'-target=module.compute_api' \"-out=tfplan\"" in text
    )
    assert text.index("-target=module.compute_api") < text.index(
        "terraform apply tfplan"
    )
    assert "Stop and paste the plan to the reviewer before apply" in text


def test_runbook_states_what_stage_6a_did_not_verify() -> None:
    text = runbook()

    for item in (
        "The Wrangler action on Pages",
        "CORS live",
        "default style",
        "5 requests per second throttle",
        "prefix-domain charge",
    ):
        assert item in text
    assert "`_headers`" in text
    assert "unverified until step 9" in text


def test_adr_records_the_decisions_and_the_partly_resolved_token_item() -> None:
    adr = ADR_022.read_text(encoding="utf-8")

    assert "Owner decisions of 2026-11-05" in adr
    assert "app.<owner-domain>" in adr
    token_row = next(
        line
        for line in adr.splitlines()
        if line.startswith("| Whether a Cloudflare API token can be limited")
    )
    assert "PARTIALLY RESOLVED" in token_row
    assert "secondary source" in token_row


# Existing workflows


@pytest.mark.parametrize("name", sorted(UNCHANGED_WORKFLOW_SHA256))
def test_existing_workflows_are_unchanged(name: str) -> None:
    content = (WORKFLOWS / name).read_bytes().replace(b"\r\n", b"\n")

    assert hashlib.sha256(content).hexdigest() == UNCHANGED_WORKFLOW_SHA256[name]
