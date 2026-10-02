"""CLI gate for EG-09 label completeness and independent adjudication."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from ai_qa_copilot_api.evaluation_label_completeness import (
    LabelCompletenessAndAdjudicationRejected,
    verify_label_completeness_and_adjudication,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path("evaluation/reviews/release-review-manifest.v2.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify versioned release review evidence."
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--expected-candidate-commit-sha")
    parser.add_argument("--output", type=Path)
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

    if (
        args.expected_candidate_commit_sha is not None
        and result.candidate_commit_sha != args.expected_candidate_commit_sha
    ):
        raise SystemExit(
            "Release review candidate SHA does not match checked-out commit"
        )

    if args.output is not None:
        payload = {
            "schema_version": "release-review-verification/v1",
            "release_review_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "review": asdict(result),
        }
        try:
            with args.output.open("x", encoding="utf-8", newline="\n") as target:
                target.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        except OSError as error:
            raise SystemExit(
                f"Cannot write release review verification: {error}"
            ) from error

    print(
        "release review verification passed: "
        f"suite={result.suite_id}, cases={result.case_count}, "
        f"mode={result.review_mode}, disclosure={result.disclosure}, "
        f"validation_reviews={result.validation_independent_review_count}, "
        f"holdout_reviews={result.holdout_independent_review_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
