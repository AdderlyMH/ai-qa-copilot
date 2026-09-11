from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ai_qa_copilot_api.evaluation_cases import EvaluationCase
from ai_qa_copilot_api.evaluation_runner import EvaluationObservation

SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from run_evaluation import main  # noqa: E402


class StaticExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, case: EvaluationCase) -> EvaluationObservation:
        self.calls += 1
        return EvaluationObservation(
            boundary="analysis_only",
            side_effects={
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
            },
            ground_truth_ids=("GT-FIND-001",),
            source_references=("REQ-BASE-001#REQ-ORDER-004:statement",),
            cost=0,
        )


def evaluation_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repository_root = tmp_path / "repository"
    artifact_path = repository_root / "fixtures" / "sample-requirements.md"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("Synthetic requirement fixture.", encoding="utf-8")
    artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    fixture_path = repository_root / "fixtures" / "benchmark" / "cases.yaml"
    fixture_path.parent.mkdir(parents=True)
    fixture_path.write_text(
        f"""\
schema_version: evaluation-cases/v1
suite_id: evaluation-development/v1
cases:
  - id: EVAL-001
    version: 1
    split: development
    category: requirement_quality
    tags: [requirements, control]
    criticality: high
    run_mode: analysis
    side_effect_schema: side-effects/v1
    inputs:
      artifacts:
        - artifact_id: REQ-BASE-001
          path: fixtures/sample-requirements.md
          sha256: {artifact_sha256}
      overlays: []
      user_request: Identify contradictions and missing clarifications.
    expected:
      required_ground_truth_ids: [GT-FIND-001]
      prohibited_ground_truth_ids: []
      expected_source_references:
        - REQ-BASE-001#REQ-ORDER-004:statement
      policy_boundary: analysis_only
      side_effects:
        chunks: 0
        embeddings: 0
        model_calls: 0
        execution_candidates: 0
        automatic_retries: 0
        dns_requests: 0
        http_requests: 0
        execution_plans: 0
        target_configuration_mutations: 0
        approval_mutations: 0
        secret_exposures: 0
      scorer_version: evaluation-scorer/v1
      maximum_expected_cost: 0
""",
        encoding="utf-8",
    )
    return repository_root, fixture_path


def install_executor_module(
    monkeypatch: pytest.MonkeyPatch,
) -> StaticExecutor:
    executor = StaticExecutor()
    module = ModuleType("test_evaluation_executor")

    def create_executor() -> StaticExecutor:
        return executor

    setattr(module, "create_executor", create_executor)
    monkeypatch.setitem(sys.modules, "test_evaluation_executor", module)
    return executor


def test_cli_writes_and_resumes_a_machine_readable_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root, fixture_path = evaluation_fixture(tmp_path)
    executor = install_executor_module(monkeypatch)
    output_path = tmp_path / "evaluation-run.json"

    assert (
        main(
            [
                "--fixture",
                str(fixture_path),
                "--repository-root",
                str(repository_root),
                "--executor",
                "test_evaluation_executor:create_executor",
                "--output",
                str(output_path),
                "--max-concurrency",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "evaluation-run/v1"
    assert payload["selected_case_ids"] == ["EVAL-001"]
    assert payload["results"][0]["reused"] is False
    assert executor.calls == 1

    assert (
        main(
            [
                "--fixture",
                str(fixture_path),
                "--repository-root",
                str(repository_root),
                "--executor",
                "test_evaluation_executor:create_executor",
                "--output",
                str(output_path),
                "--resume",
                str(output_path),
            ]
        )
        == 0
    )

    resumed_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert resumed_payload["results"][0]["reused"] is True
    assert executor.calls == 1


def test_cli_refuses_to_overwrite_without_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root, fixture_path = evaluation_fixture(tmp_path)
    install_executor_module(monkeypatch)
    output_path = tmp_path / "evaluation-run.json"
    output_path.write_text("already exists", encoding="utf-8")

    with pytest.raises(SystemExit, match="Output already exists"):
        main(
            [
                "--fixture",
                str(fixture_path),
                "--repository-root",
                str(repository_root),
                "--executor",
                "test_evaluation_executor:create_executor",
                "--output",
                str(output_path),
            ]
        )
