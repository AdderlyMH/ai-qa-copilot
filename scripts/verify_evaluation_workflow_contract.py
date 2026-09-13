"""Validate the non-secret preconditions for an evaluation workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_qa_copilot_api.evaluation_workflow_contract import (
    DEFAULT_RELEASE_REVIEW_MANIFEST_RELATIVE_PATH,
    EvaluationWorkflowContractRejected,
    verify_release_workflow_preflight,
    verify_smoke_workflow_preflight,
)


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "release"), required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--baseline-executor", required=True)
    parser.add_argument("--grounded-executor", required=True)
    parser.add_argument(
        "--release-review-manifest",
        type=Path,
        default=ROOT / DEFAULT_RELEASE_REVIEW_MANIFEST_RELATIVE_PATH,
    )
    parser.add_argument("--require-positive-case-budgets", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.mode == "smoke":
            preflight = verify_smoke_workflow_preflight(
                args.repository_root,
                baseline_executor=args.baseline_executor,
                grounded_executor=args.grounded_executor,
                require_positive_case_budgets=args.require_positive_case_budgets,
            )
        else:
            preflight = verify_release_workflow_preflight(
                args.repository_root,
                baseline_executor=args.baseline_executor,
                grounded_executor=args.grounded_executor,
                release_review_manifest=args.release_review_manifest,
                require_positive_case_budgets=args.require_positive_case_budgets,
            )
    except EvaluationWorkflowContractRejected as error:
        raise SystemExit(str(error)) from error

    print(
        f"{preflight.mode} preflight passed: "
        f"suite={preflight.suite_id}, "
        f"cases={len(preflight.selected_case_ids)}, "
        f"declared_expected_cost={preflight.declared_expected_cost}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
