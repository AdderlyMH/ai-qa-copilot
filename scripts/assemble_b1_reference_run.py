"""Assemble one immutable B1 reference artifact from recorded evidence only."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from ai_qa_copilot_api.b1_reference_artifact import (
    B1ReferenceArtifactRejected,
    assemble_b1_reference_artifact,
    write_b1_reference_artifact,
)
from ai_qa_copilot_api.b1_reference_assembly_inputs import (
    B1ReferenceAssemblyInputRejected,
    load_b1_measurements,
    load_b1_reference_assembly_input,
    load_evaluation_score_report,
)
from ai_qa_copilot_api.b1_reference_evidence import (
    B1ReferenceEvidenceRejected,
    build_b1_reference_run,
)
from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_release_benchmark import (
    EVALUATION_CORPUS_SUITE_ID,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationRunRejected,
    evaluation_run_from_json,
    EvaluationRun,
)
from ai_qa_copilot_api.evaluation_scoring import EvaluationScoreReport


ROOT = Path(__file__).resolve().parents[1]
CASE_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
GROUND_TRUTH_FIXTURE = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembly-input", type=Path, required=True)
    parser.add_argument("--evaluation-run", type=Path, required=True)
    parser.add_argument("--score-report", type=Path, required=True)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--review-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    try:
        assembly_input = load_b1_reference_assembly_input(args.assembly_input)
        evaluation_run = evaluation_run_from_json(
            _read_required(args.evaluation_run, "Evaluation run")
        )
        score_report = load_evaluation_score_report(args.score_report)
        measurements = load_b1_measurements(args.measurements)

        _validate_complete_corpus(
            repository_root=args.repository_root,
            evaluation_run=evaluation_run,
            score_report=score_report,
        )

        reference_run = build_b1_reference_run(
            reference_run_id=assembly_input.reference_run_id,
            workflow_trace_id=assembly_input.workflow_trace_id,
            recorded_at=assembly_input.recorded_at,
            configuration=assembly_input.configuration,
            evaluation_run=evaluation_run,
            score_report=score_report,
            measurements=measurements,
        )
        artifact = assemble_b1_reference_artifact(
            repository_root=args.repository_root,
            release_review_manifest_path=args.review_manifest,
            reference_run=reference_run,
        )
        write_b1_reference_artifact(artifact, output_path=args.output)
    except (
        B1ReferenceAssemblyInputRejected,
        B1ReferenceEvidenceRejected,
        B1ReferenceArtifactRejected,
        EvaluationRunRejected,
    ) as error:
        raise SystemExit(str(error)) from error

    print(f"B1 reference artifact written: {_display_path(args.output)}")
    return 0


def _validate_complete_corpus(
    *,
    repository_root: Path,
    evaluation_run: EvaluationRun,
    score_report: EvaluationScoreReport,
) -> None:
    case_fixture = repository_root / "fixtures/benchmark/evaluation-cases.v1.yaml"
    ground_truth = repository_root / "fixtures/benchmark/ground-truth.v1.yaml"
    if not case_fixture.is_file() or not ground_truth.is_file():
        raise B1ReferenceArtifactRejected(
            "Current B1 benchmark or ground-truth fixture does not exist"
        )

    suite = load_evaluation_case_suite(case_fixture)
    if suite.suite_id != EVALUATION_CORPUS_SUITE_ID:
        raise B1ReferenceArtifactRejected("Current evaluation suite is not the corpus")

    expected_case_ids = tuple(case.id for case in suite.cases)
    expected_case_sha256 = _sha256_file(case_fixture)
    expected_ground_truth_sha256 = _sha256_file(ground_truth)

    if (
        evaluation_run.suite_id != suite.suite_id
        or evaluation_run.fixture_sha256 != expected_case_sha256
        or evaluation_run.selected_case_ids != expected_case_ids
    ):
        raise B1ReferenceArtifactRejected(
            "Evaluation run does not match the complete current B1 corpus"
        )
    if score_report.ground_truth_sha256 != expected_ground_truth_sha256:
        raise B1ReferenceArtifactRejected(
            "Score report does not match current B1 ground-truth provenance"
        )


def _read_required(path: Path, label: str) -> str:
    if not path.is_file():
        raise B1ReferenceArtifactRejected(f"{label} does not exist: {path}")
    return path.read_text(encoding="utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path) -> Path:
    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return path.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
