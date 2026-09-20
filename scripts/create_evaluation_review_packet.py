"""Create one immutable reviewer packet from a selected evaluation case."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCasesRejected,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_review_capture import (
    EvaluationReviewCaptureRejected,
    EvaluationReviewPacketRole,
    build_evaluation_review_capture_packet,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
DEFAULT_RUBRIC_VERSION = "evaluation-review-rubric/v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--case-id", required=True)
    parser.add_argument(
        "--role",
        required=True,
        choices=[role.value for role in EvaluationReviewPacketRole],
    )
    parser.add_argument(
        "--subject-kind",
        required=True,
        choices=["finding", "test_case", "failure_analysis"],
    )
    parser.add_argument("--subject-id", required=True)
    parser.add_argument(
        "--rubric-version",
        default=DEFAULT_RUBRIC_VERSION,
    )
    parser.add_argument("--candidate-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.fixture.is_file():
        raise SystemExit(f"Evaluation fixture does not exist: {args.fixture}")
    if not args.repository_root.is_dir():
        raise SystemExit(f"Repository root does not exist: {args.repository_root}")
    if args.output.exists():
        raise SystemExit(f"Output already exists: {args.output}")

    repository_root = args.repository_root.resolve()
    output_path = args.output.resolve()
    try:
        output_path.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise SystemExit("Review-packet output must be outside the repository root")

    role = EvaluationReviewPacketRole(args.role)
    if role is EvaluationReviewPacketRole.PRIMARY:
        if args.candidate_output is None:
            raise SystemExit("Primary review packets require --candidate-output")
        if not args.candidate_output.is_file():
            raise SystemExit(
                f"Candidate output does not exist: {args.candidate_output}"
            )
        try:
            candidate_output_text = args.candidate_output.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            raise SystemExit("Candidate output must be UTF-8 text") from error
    else:
        if args.candidate_output is not None:
            raise SystemExit("Independent review packets cannot use --candidate-output")
        candidate_output_text = None

    try:
        suite = load_evaluation_case_suite(args.fixture)
        case = next(
            (item for item in suite.cases if item.id == args.case_id),
            None,
        )
        if case is None:
            raise EvaluationReviewCaptureRejected(
                f"Evaluation case was not found: {args.case_id}"
            )

        packet = build_evaluation_review_capture_packet(
            case,
            suite_id=suite.suite_id,
            case_fixture_sha256=hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
            dataset_version=suite.schema_version,
            rubric_version=args.rubric_version,
            subject_kind=args.subject_kind,
            subject_id=args.subject_id,
            role=role,
            repository_root=repository_root,
            candidate_output_text=candidate_output_text,
        )
    except (
        EvaluationCasesRejected,
        EvaluationReviewCaptureRejected,
    ) as error:
        raise SystemExit(str(error)) from error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(packet.as_json().encode("utf-8"))

    print(f"Review packet written: {output_path}")
    print(f"Review packet SHA-256: {packet.sha256}")
    if packet.candidate_output_sha256 is not None:
        print(f"Candidate-output SHA-256: {packet.candidate_output_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
