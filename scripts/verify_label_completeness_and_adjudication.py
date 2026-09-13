"""CLI gate for EG-09 label completeness and independent adjudication."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_qa_copilot_api.evaluation_label_completeness import (
    LabelCompletenessAndAdjudicationRejected,
    verify_label_completeness_and_adjudication,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path("evaluation/reviews/release-review-manifest.v1.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify label_completeness_and_adjudication_v1 evidence."
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repository_root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path

    try:
        result = verify_label_completeness_and_adjudication(
            repository_root=root,
            manifest_path=manifest_path,
        )
    except LabelCompletenessAndAdjudicationRejected as error:
        raise SystemExit(str(error)) from error

    print(
        "label_completeness_and_adjudication_v1 passed: "
        f"suite={result.suite_id}, cases={result.case_count}, "
        f"validation_reviews={result.validation_independent_review_count}, "
        f"holdout_reviews={result.holdout_independent_review_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
