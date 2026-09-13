"""Static safety checks for the evaluation GitHub Actions workflows."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SMOKE_WORKFLOW = ROOT / ".github" / "workflows" / "evaluation-smoke.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "evaluation-release.yml"
CHECKOUT_ACTION = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_PYTHON_ACTION = "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405"
UPLOAD_ARTIFACT_ACTION = (
    "actions/upload-artifact@65c4c4a1ddee5b72f698fdd19549f0f0fb45cf08"
)
SMOKE_CASE_IDS = (
    "EVAL-001",
    "EVAL-013",
    "EVAL-025",
    "EVAL-034",
    "EVAL-043",
    "EVAL-049",
    "EVAL-055",
    "EVAL-058",
)


def workflow_text(path: Path) -> str:
    assert path.is_file(), f"Missing workflow: {path}"
    return path.read_text(encoding="utf-8")


def assert_common_workflow_safety(text: str) -> None:
    assert "on:\n  workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "\n  push:" not in text
    assert "continue-on-error:" not in text
    assert CHECKOUT_ACTION in text
    assert SETUP_PYTHON_ACTION in text
    assert UPLOAD_ARTIFACT_ACTION in text
    assert "if: always()" in text
    assert "uv sync --frozen" in text
    assert "--require-positive-case-budgets" in text


def test_smoke_workflow_is_manual_fixed_scope_and_fail_closed() -> None:
    text = workflow_text(SMOKE_WORKFLOW)

    assert_common_workflow_safety(text)
    assert "name: evaluation-smoke" in text
    assert '[[ "${{ inputs.confirm_live_run }}" == "RUN_SMOKE" ]]' in text
    assert "--mode smoke" in text
    assert "--split development" in text
    assert '--max-expected-cost "$SMOKE_MAX_EXPECTED_COST"' in text
    assert "--max-concurrency 1" in text

    for case_id in SMOKE_CASE_IDS:
        assert text.count(f"--case-id {case_id}") == 2


def test_release_workflow_is_protected_main_only_and_full_corpus() -> None:
    text = workflow_text(RELEASE_WORKFLOW)

    assert_common_workflow_safety(text)
    assert "name: evaluation-release" in text
    assert '[[ "$GITHUB_REF" == "refs/heads/main" ]]' in text
    assert '[[ "$CANDIDATE_COMMIT_SHA" == "$GITHUB_SHA" ]]' in text
    assert '[[ "${{ inputs.confirm_live_run }}" == "RUN_RELEASE" ]]' in text
    assert "--mode release" in text
    assert (
        "--release-review-manifest "
        "evaluation/reviews/release-review-manifest.v1.yaml" in text
    )
    assert "--case-id" not in text
    assert "--split" not in text
    assert '--max-expected-cost "$B0_MAX_EXPECTED_COST"' in text
    assert '--max-expected-cost "$GROUNDED_MAX_EXPECTED_COST"' in text
    assert 'B0_MAX_EXPECTED_COST: "2"' in text
    assert 'GROUNDED_MAX_EXPECTED_COST: "8"' in text
    assert "Run label_completeness_and_adjudication_v1" in text
    assert "scripts/verify_label_completeness_and_adjudication.py" in text
