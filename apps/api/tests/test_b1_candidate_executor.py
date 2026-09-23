from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path

import pytest

from ai_qa_copilot_api.b1_candidate_executor import (
    B1_CANDIDATE_EXECUTOR_SCHEMA_VERSION,
    CANDIDATE_OUTPUT_SCHEMA_VERSION,
    B1CandidateExecutionResult,
    B1CandidateExecutor,
    B1CandidateExecutorConfig,
    B1CandidateExecutorRejected,
    B1CandidateSubject,
    create_b1_candidate_executor,
)
from ai_qa_copilot_api.evaluation_cases import (
    SIDE_EFFECT_FIELD_NAMES,
    EvaluationArtifact,
    EvaluationCase,
    EvaluationCaseSuite,
    EvaluationExpected,
    EvaluationInputs,
)
from ai_qa_copilot_api.evaluation_reviews import EvaluationReviewSubjectKind
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationObservation,
    run_evaluation_cases,
)


def zero_side_effects() -> dict[str, int]:
    return {field_name: 0 for field_name in sorted(SIDE_EFFECT_FIELD_NAMES)}


def zero_side_effect_items() -> tuple[tuple[str, int], ...]:
    return tuple(zero_side_effects().items())


def case_for(repository_root: Path) -> tuple[EvaluationCase, Path]:
    source_path = repository_root / "fixtures" / "source.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("Synthetic source fixture.", encoding="utf-8")

    case = EvaluationCase(
        id="EVAL-001",
        version=1,
        split="development",
        category="requirement_quality",
        tags=("requirements", "control"),
        criticality="high",
        run_mode="analysis",
        side_effect_schema="side-effects/v1",
        inputs=EvaluationInputs(
            artifacts=(
                EvaluationArtifact(
                    artifact_id="REQ-001",
                    path="fixtures/source.md",
                    sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                ),
            ),
            overlays=(),
            user_request="Identify contradictions.",
        ),
        expected=EvaluationExpected(
            required_ground_truth_ids=("GT-FIND-001",),
            prohibited_ground_truth_ids=(),
            expected_source_references=("REQ-001#statement",),
            policy_boundary="analysis_only",
            side_effects=zero_side_effects(),
            scorer_version="evaluation-scorer/v1",
            maximum_expected_cost=0,
        ),
    )
    fixture_path = repository_root / "fixtures" / "evaluation-cases.v1.yaml"
    fixture_path.write_text("fixture provenance", encoding="utf-8")
    return case, fixture_path


def configuration_for(case_id: str = "EVAL-001") -> B1CandidateExecutorConfig:
    return B1CandidateExecutorConfig(
        schema_version=B1_CANDIDATE_EXECUTOR_SCHEMA_VERSION,
        executor_id="B1",
        executor_version=1,
        candidate_output_schema_version=CANDIDATE_OUTPUT_SCHEMA_VERSION,
        maximum_cost=0,
        side_effects=zero_side_effect_items(),
        case_subjects=(
            B1CandidateSubject(
                case_id=case_id,
                subject_kind=EvaluationReviewSubjectKind.FINDING,
                subject_id="FIND-001",
            ),
        ),
    )


@dataclass
class FakeAdapter:
    candidate_output: str = "synthetic candidate output for test only\n"
    calls: list[str] = field(default_factory=list)

    def execute(self, case: EvaluationCase) -> B1CandidateExecutionResult:
        self.calls.append(case.id)
        return B1CandidateExecutionResult(
            observation=EvaluationObservation(
                boundary="analysis_only",
                side_effects=zero_side_effects(),
                ground_truth_ids=("GT-FIND-001",),
                source_references=("REQ-001#statement",),
                cost=0,
            ),
            candidate_output=self.candidate_output,
        )


def test_executor_keeps_candidate_output_outside_content_free_run_report(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    output_directory = tmp_path / "candidate-output"
    output_directory.mkdir()
    case, fixture_path = case_for(repository_root)
    candidate_output = "UNIQUE-FAKE-CANDIDATE-CONTENT\n"
    adapter = FakeAdapter(candidate_output=candidate_output)
    executor = B1CandidateExecutor(
        configuration=configuration_for(),
        adapter=adapter,
        repository_root=repository_root,
        output_directory=output_directory,
    )

    report = run_evaluation_cases(
        EvaluationCaseSuite(
            schema_version="evaluation-cases/v1",
            suite_id="evaluation-development/v1",
            cases=(case,),
        ),
        fixture_path=fixture_path,
        repository_root=repository_root,
        executor=executor,
    )

    output_path = output_directory / "EVAL-001.candidate-output.txt"
    assert adapter.calls == ["EVAL-001"]
    assert output_path.read_text(encoding="utf-8") == candidate_output
    assert candidate_output not in report.as_json()

    receipt = executor.receipts[0]
    assert receipt.subject_kind is EvaluationReviewSubjectKind.FINDING
    assert receipt.subject_id == "FIND-001"
    assert (
        receipt.candidate_output_sha256
        == hashlib.sha256(candidate_output.encode("utf-8")).hexdigest()
    )
    assert receipt.configuration_sha256 == configuration_for().configuration_sha256


def test_executor_rejects_candidate_output_directory_inside_repository(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    inside_repository = repository_root / "candidate-output"
    inside_repository.mkdir()

    with pytest.raises(B1CandidateExecutorRejected, match="outside"):
        B1CandidateExecutor(
            configuration=configuration_for(),
            adapter=FakeAdapter(),
            repository_root=repository_root,
            output_directory=inside_repository,
        )


def test_executor_rejects_unmapped_case_before_calling_adapter(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    output_directory = tmp_path / "candidate-output"
    output_directory.mkdir()
    case, _ = case_for(repository_root)
    adapter = FakeAdapter()
    executor = B1CandidateExecutor(
        configuration=configuration_for(case_id="EVAL-999"),
        adapter=adapter,
        repository_root=repository_root,
        output_directory=output_directory,
    )

    with pytest.raises(B1CandidateExecutorRejected, match="does not map"):
        executor.execute(case)

    assert adapter.calls == []


def test_executor_rejects_fixture_budget_mismatch_before_adapter_call(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    output_directory = tmp_path / "candidate-output"
    output_directory.mkdir()
    case, _ = case_for(repository_root)
    adapter = FakeAdapter()
    executor = B1CandidateExecutor(
        configuration=configuration_for(),
        adapter=adapter,
        repository_root=repository_root,
        output_directory=output_directory,
    )
    incompatible_case = replace(
        case,
        expected=replace(case.expected, maximum_expected_cost=1),
    )

    with pytest.raises(B1CandidateExecutorRejected, match="expected cost differs"):
        executor.execute(incompatible_case)

    assert adapter.calls == []


def test_executor_does_not_overwrite_an_existing_candidate_output(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    output_directory = tmp_path / "candidate-output"
    output_directory.mkdir()
    case, _ = case_for(repository_root)
    adapter = FakeAdapter()
    executor = B1CandidateExecutor(
        configuration=configuration_for(),
        adapter=adapter,
        repository_root=repository_root,
        output_directory=output_directory,
    )

    executor.execute(case)

    with pytest.raises(B1CandidateExecutorRejected, match="already exists"):
        executor.execute(case)

    assert adapter.calls == ["EVAL-001"]


def test_cli_factory_is_explicitly_disabled() -> None:
    with pytest.raises(B1CandidateExecutorRejected, match="disabled"):
        create_b1_candidate_executor()
