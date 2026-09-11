from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import threading
import time
import json
import pytest

from ai_qa_copilot_api.evaluation_cases import (
    EvaluationArtifact,
    EvaluationCase,
    EvaluationCaseSuite,
    EvaluationExpected,
    EvaluationInputs,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationCaseExecutor,
    EvaluationObservation,
    EvaluationRunRejected,
    run_evaluation_cases,
    evaluation_run_from_json,
)


def zero_side_effects() -> dict[str, int]:
    return {
        "chunks": 0,
        "embeddings": 0,
        "model_calls": 0,
        "execution_candidates": 0,
        "automatic_retries": 0,
        "dns_requests": 0,
        "http_requests": 0,
        "execution_plans": 0,
        "target_configuration_mutations": 0,
        "approval_mutations": 0,
        "secret_exposures": 0,
    }


def suite_for(
    tmp_path: Path,
    *,
    count: int = 2,
    cost: int = 1,
) -> tuple[EvaluationCaseSuite, Path]:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    cases: list[EvaluationCase] = []
    for number in range(1, count + 1):
        artifact_path = artifacts / f"case-{number}.txt"
        artifact_path.write_text(f"case {number}", encoding="utf-8")
        relative_path = artifact_path.relative_to(tmp_path).as_posix()

        cases.append(
            EvaluationCase(
                id=f"EVAL-{number:03}",
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
                            artifact_id=f"ART-{number:03}",
                            path=relative_path,
                            sha256=hashlib.sha256(
                                artifact_path.read_bytes()
                            ).hexdigest(),
                        ),
                    ),
                    overlays=(),
                    user_request="Identify contradictions.",
                ),
                expected=EvaluationExpected(
                    required_ground_truth_ids=("GT-FIND-001",),
                    prohibited_ground_truth_ids=(),
                    expected_source_references=(
                        "REQ-BASE-001#REQ-ORDER-004:statement",
                    ),
                    policy_boundary="analysis_only",
                    side_effects=zero_side_effects(),
                    scorer_version="evaluation-scorer/v1",
                    maximum_expected_cost=cost,
                ),
            )
        )

    fixture_path = tmp_path / "evaluation-cases.v1.yaml"
    fixture_path.write_text("fixture provenance", encoding="utf-8")

    return (
        EvaluationCaseSuite(
            schema_version="evaluation-cases/v1",
            suite_id="evaluation-development/v1",
            cases=tuple(cases),
        ),
        fixture_path,
    )


class RecordingExecutor(EvaluationCaseExecutor):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, case: EvaluationCase) -> EvaluationObservation:
        self.calls.append(case.id)
        return EvaluationObservation(
            boundary="analysis_only",
            side_effects=zero_side_effects(),
            ground_truth_ids=("GT-FIND-001",),
            source_references=("REQ-BASE-001#REQ-ORDER-004:statement",),
            cost=case.expected.maximum_expected_cost,
        )


class ConcurrentExecutor(EvaluationCaseExecutor):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0

    def execute(self, case: EvaluationCase) -> EvaluationObservation:
        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)

        try:
            time.sleep(0.02)
            return EvaluationObservation(
                boundary="analysis_only",
                side_effects=zero_side_effects(),
                ground_truth_ids=("GT-FIND-001",),
                source_references=("REQ-BASE-001#REQ-ORDER-004:statement",),
                cost=case.expected.maximum_expected_cost,
            )
        finally:
            with self._lock:
                self.active -= 1


def test_runner_preserves_selected_fixture_order(tmp_path: Path) -> None:
    suite, fixture_path = suite_for(tmp_path, count=3)
    executor = RecordingExecutor()

    report = run_evaluation_cases(
        suite,
        fixture_path=fixture_path,
        repository_root=tmp_path,
        executor=executor,
        case_ids={"EVAL-003", "EVAL-001"},
    )

    assert report.selected_case_ids == ("EVAL-001", "EVAL-003")
    assert [result.case_id for result in report.results] == [
        "EVAL-001",
        "EVAL-003",
    ]
    assert sorted(executor.calls) == ["EVAL-001", "EVAL-003"]


def test_runner_rejects_mismatched_artifact_before_execution(
    tmp_path: Path,
) -> None:
    suite, fixture_path = suite_for(tmp_path, count=1)
    case = suite.cases[0]
    invalid_artifact = replace(
        case.inputs.artifacts[0],
        sha256="0" * 64,
    )
    invalid_case = replace(
        case,
        inputs=replace(case.inputs, artifacts=(invalid_artifact,)),
    )
    executor = RecordingExecutor()

    with pytest.raises(EvaluationRunRejected, match="artifact hash differs"):
        run_evaluation_cases(
            replace(suite, cases=(invalid_case,)),
            fixture_path=fixture_path,
            repository_root=tmp_path,
            executor=executor,
        )

    assert executor.calls == []


def test_runner_rejects_over_budget_before_execution(tmp_path: Path) -> None:
    suite, fixture_path = suite_for(tmp_path, count=2, cost=2)
    executor = RecordingExecutor()

    with pytest.raises(EvaluationRunRejected, match="expected-cost budget"):
        run_evaluation_cases(
            suite,
            fixture_path=fixture_path,
            repository_root=tmp_path,
            executor=executor,
            max_expected_cost=3,
        )

    assert executor.calls == []


def test_runner_reuses_matching_prior_results(tmp_path: Path) -> None:
    suite, fixture_path = suite_for(tmp_path, count=2)
    executor = RecordingExecutor()

    initial_report = run_evaluation_cases(
        suite,
        fixture_path=fixture_path,
        repository_root=tmp_path,
        executor=executor,
    )
    resumed_report = run_evaluation_cases(
        suite,
        fixture_path=fixture_path,
        repository_root=tmp_path,
        executor=executor,
        resume_from=initial_report,
    )

    assert executor.calls == ["EVAL-001", "EVAL-002"]
    assert all(result.reused for result in resumed_report.results)


def test_runner_enforces_the_configured_concurrency_cap(tmp_path: Path) -> None:
    suite, fixture_path = suite_for(tmp_path, count=4)
    executor = ConcurrentExecutor()

    run_evaluation_cases(
        suite,
        fixture_path=fixture_path,
        repository_root=tmp_path,
        executor=executor,
        max_concurrency=2,
    )

    assert 1 <= executor.maximum_active <= 2


def test_runner_rejects_invalid_concurrency(tmp_path: Path) -> None:
    suite, fixture_path = suite_for(tmp_path, count=1)

    with pytest.raises(EvaluationRunRejected, match="at least one"):
        run_evaluation_cases(
            suite,
            fixture_path=fixture_path,
            repository_root=tmp_path,
            executor=RecordingExecutor(),
            max_concurrency=0,
        )


def test_runner_report_json_round_trips_with_stable_provenance(
    tmp_path: Path,
) -> None:
    suite, fixture_path = suite_for(tmp_path, count=1)

    report = run_evaluation_cases(
        suite,
        fixture_path=fixture_path,
        repository_root=tmp_path,
        executor=RecordingExecutor(),
        max_expected_cost=1,
    )

    assert evaluation_run_from_json(report.as_json()) == report


def test_runner_report_rejects_tampered_side_effect_contract(
    tmp_path: Path,
) -> None:
    suite, fixture_path = suite_for(tmp_path, count=1)

    report = run_evaluation_cases(
        suite,
        fixture_path=fixture_path,
        repository_root=tmp_path,
        executor=RecordingExecutor(),
    )
    payload = json.loads(report.as_json())
    side_effects = payload["results"][0]["observation"]["side_effects"]
    del side_effects["dns_requests"]
    side_effects["dns_calls"] = 0

    with pytest.raises(
        EvaluationRunRejected,
        match="exact side-effects/v1 fields",
    ):
        evaluation_run_from_json(json.dumps(payload))
