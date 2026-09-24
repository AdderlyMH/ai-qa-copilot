from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path

import pytest

from ai_qa_copilot_api.b1_candidate_executor import (
    B1_CANDIDATE_EXECUTOR_SCHEMA_VERSION,
    CANDIDATE_OUTPUT_SCHEMA_VERSION,
    B1CandidateAdapterInput,
    B1CandidateCaseLimit,
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
    load_evaluation_case_suite,
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


def side_effects_for(run_mode: str) -> dict[str, int]:
    values = zero_side_effects()
    if run_mode == "analysis":
        values["model_calls"] = 1
    return values


def case_for(
    repository_root: Path, *, run_mode: str = "analysis"
) -> tuple[EvaluationCase, Path]:
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
        run_mode=run_mode,
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
            required_ground_truth_ids=("PRIVATE-GROUND-TRUTH-MARKER",),
            prohibited_ground_truth_ids=(),
            expected_source_references=("REQ-001#statement",),
            policy_boundary="analysis_only",
            side_effects=side_effects_for(run_mode),
            scorer_version="evaluation-scorer/v1",
            maximum_expected_cost=0,
        ),
    )
    fixture_path = repository_root / "fixtures" / "evaluation-cases.v1.yaml"
    fixture_path.write_text("fixture provenance", encoding="utf-8")
    return case, fixture_path


def configuration_for(
    case_id: str = "EVAL-001", *, run_mode: str = "analysis"
) -> B1CandidateExecutorConfig:
    return B1CandidateExecutorConfig(
        schema_version=B1_CANDIDATE_EXECUTOR_SCHEMA_VERSION,
        executor_id="B1",
        executor_version=1,
        candidate_output_schema_version=CANDIDATE_OUTPUT_SCHEMA_VERSION,
        case_limits=(
            B1CandidateCaseLimit(
                case_id=case_id,
                maximum_cost=0,
                side_effects=tuple(side_effects_for(run_mode).items()),
            ),
        ),
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
    side_effects: dict[str, int] = field(
        default_factory=lambda: side_effects_for("analysis")
    )
    calls: list[B1CandidateAdapterInput] = field(default_factory=list)

    def execute(self, inputs: B1CandidateAdapterInput) -> B1CandidateExecutionResult:
        self.calls.append(inputs)
        return B1CandidateExecutionResult(
            observation=EvaluationObservation(
                boundary="analysis_only",
                side_effects=self.side_effects,
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
    assert [item.case_id for item in adapter.calls] == ["EVAL-001"]
    assert adapter.calls[0].user_request == "Identify contradictions."
    assert adapter.calls[0].source_snapshots[0].content == "Synthetic source fixture."
    assert not hasattr(adapter.calls[0], "expected")
    assert "PRIVATE-GROUND-TRUTH-MARKER" not in repr(adapter.calls[0])
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

    assert [item.case_id for item in adapter.calls] == ["EVAL-001"]


def test_policy_case_rejects_missing_zero_call_adapter(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    output_directory = tmp_path / "candidate-output"
    output_directory.mkdir()
    case, _ = case_for(repository_root, run_mode="policy")
    analysis_adapter = FakeAdapter()
    executor = B1CandidateExecutor(
        configuration=configuration_for(run_mode="policy"),
        adapter=analysis_adapter,
        repository_root=repository_root,
        output_directory=output_directory,
    )

    with pytest.raises(B1CandidateExecutorRejected, match="zero-call adapter"):
        executor.execute(case)

    assert analysis_adapter.calls == []
    assert not (output_directory / "EVAL-001.candidate-output.txt").exists()


def test_policy_case_uses_only_separate_zero_call_adapter(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    output_directory = tmp_path / "candidate-output"
    output_directory.mkdir()
    case, _ = case_for(repository_root, run_mode="policy")
    analysis_adapter = FakeAdapter()
    policy_adapter = FakeAdapter(side_effects=zero_side_effects())
    executor = B1CandidateExecutor(
        configuration=configuration_for(run_mode="policy"),
        adapter=analysis_adapter,
        policy_adapter=policy_adapter,
        repository_root=repository_root,
        output_directory=output_directory,
    )

    observation = executor.execute(case)

    assert analysis_adapter.calls == []
    assert [item.case_id for item in policy_adapter.calls] == ["EVAL-001"]
    assert observation.side_effects["model_calls"] == 0


def test_source_hash_is_checked_before_adapter_call(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    output_directory = tmp_path / "candidate-output"
    output_directory.mkdir()
    case, _ = case_for(repository_root)
    (repository_root / "fixtures" / "source.md").write_text(
        "Tampered source fixture.", encoding="utf-8"
    )
    adapter = FakeAdapter()
    executor = B1CandidateExecutor(
        configuration=configuration_for(),
        adapter=adapter,
        repository_root=repository_root,
        output_directory=output_directory,
    )

    with pytest.raises(B1CandidateExecutorRejected, match="source hash differs"):
        executor.execute(case)

    assert adapter.calls == []


def test_frozen_fixture_has_per_case_model_call_limits() -> None:
    fixture = (
        Path(__file__).resolve().parents[3]
        / "fixtures"
        / "benchmark"
        / "evaluation-cases.v1.yaml"
    )
    suite = load_evaluation_case_suite(fixture)

    assert len(suite.cases) == 100
    assert sum(case.run_mode == "analysis" for case in suite.cases) == 75
    assert sum(case.run_mode == "policy" for case in suite.cases) == 25
    for case in suite.cases:
        assert case.expected.maximum_expected_cost == 0
        assert (
            case.expected.side_effects["model_calls"]
            == side_effects_for(case.run_mode)["model_calls"]
        )


def test_configuration_hash_is_independent_of_limit_order() -> None:
    first = configuration_for()
    other_limit = B1CandidateCaseLimit(
        case_id="EVAL-002", maximum_cost=0, side_effects=zero_side_effect_items()
    )
    other_subject = B1CandidateSubject(
        case_id="EVAL-002",
        subject_kind=EvaluationReviewSubjectKind.FINDING,
        subject_id="FIND-002",
    )
    forward = replace(
        first,
        case_limits=first.case_limits + (other_limit,),
        case_subjects=first.case_subjects + (other_subject,),
    )
    reverse = replace(
        first,
        case_limits=tuple(reversed(forward.case_limits)),
        case_subjects=tuple(reversed(forward.case_subjects)),
    )

    assert forward.configuration_sha256 == reverse.configuration_sha256


def test_cli_factory_is_explicitly_disabled() -> None:
    with pytest.raises(B1CandidateExecutorRejected, match="disabled"):
        create_b1_candidate_executor()
