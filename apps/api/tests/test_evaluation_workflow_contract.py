from __future__ import annotations

from pathlib import Path

import pytest

from ai_qa_copilot_api.evaluation_workflow_contract import (
    SMOKE_CASE_IDS,
    EvaluationWorkflowContractRejected,
    verify_release_workflow_preflight,
    verify_smoke_workflow_preflight,
)


ROOT = Path(__file__).resolve().parents[3]
VALID_BASELINE_EXECUTOR = (
    "ai_qa_copilot_api.naive_baseline:create_naive_baseline_executor"
)
VALID_GROUNDED_EXECUTOR = "package.grounded:create_executor"


def test_smoke_preflight_uses_the_fixed_representative_development_subset() -> None:
    preflight = verify_smoke_workflow_preflight(
        ROOT,
        baseline_executor=VALID_BASELINE_EXECUTOR,
        grounded_executor=VALID_GROUNDED_EXECUTOR,
    )

    assert preflight.mode == "smoke"
    assert preflight.selected_case_ids == SMOKE_CASE_IDS
    assert len(preflight.selected_case_ids) == 8
    assert preflight.declared_expected_cost == 0


def test_smoke_preflight_refuses_live_execution_with_zero_case_budgets() -> None:
    with pytest.raises(
        EvaluationWorkflowContractRejected,
        match="positive maximum_expected_cost",
    ):
        verify_smoke_workflow_preflight(
            ROOT,
            baseline_executor=VALID_BASELINE_EXECUTOR,
            grounded_executor=VALID_GROUNDED_EXECUTOR,
            require_positive_case_budgets=True,
        )


def test_release_preflight_requires_a_committed_review_manifest(tmp_path: Path) -> None:
    with pytest.raises(
        EvaluationWorkflowContractRejected,
        match="Release review manifest does not exist",
    ):
        verify_release_workflow_preflight(
            ROOT,
            baseline_executor=VALID_BASELINE_EXECUTOR,
            grounded_executor=VALID_GROUNDED_EXECUTOR,
            release_review_manifest=tmp_path / "missing-release-review-manifest.yaml",
        )


def test_preflight_rejects_an_invalid_executor_specification() -> None:
    with pytest.raises(
        EvaluationWorkflowContractRejected,
        match="baseline executor must use module:attribute form",
    ):
        verify_smoke_workflow_preflight(
            ROOT,
            baseline_executor="not-a-factory",
            grounded_executor=VALID_GROUNDED_EXECUTOR,
        )
