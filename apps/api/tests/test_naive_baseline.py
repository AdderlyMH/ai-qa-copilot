from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from ai_qa_copilot_api.evaluation_cases import (
    SIDE_EFFECTS_SCHEMA_VERSION,
    EvaluationArtifact,
    EvaluationCase,
    EvaluationExpected,
    EvaluationInputs,
)
from ai_qa_copilot_api.naive_baseline import (
    B0_SIDE_EFFECTS,
    NaiveBaselineConfig,
    NaiveBaselineExecutor,
    NaiveBaselineModelResponse,
    NaiveBaselineRejected,
    load_naive_baseline_config,
)


class StubModel:
    def __init__(self, response: NaiveBaselineModelResponse) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, *, prompt: str) -> NaiveBaselineModelResponse:
        self.prompts.append(prompt)
        return self.response


def test_load_naive_baseline_config_accepts_committed_b0_configuration() -> None:
    config_path = (
        Path(__file__).resolve().parents[3]
        / "fixtures"
        / "benchmark"
        / "baselines"
        / "b0-naive-single-prompt.v1.yaml"
    )

    configuration = load_naive_baseline_config(config_path)

    assert configuration.baseline_id == "B0"
    assert configuration.side_effects == B0_SIDE_EFFECTS


def test_b0_uses_all_case_artifacts_and_exactly_one_model_call(
    tmp_path: Path,
) -> None:
    case = _case_with_artifact(
        tmp_path,
        artifact_content="Cancellation must be possible before dispatch.",
    )
    model = StubModel(
        NaiveBaselineModelResponse(
            content=json.dumps(
                {
                    "boundary": "model_analysis",
                    "ground_truth_ids": ["GT-FIND-001"],
                    "source_references": ["REQ-001#statement"],
                }
            ),
            cost=0.25,
        )
    )
    executor = NaiveBaselineExecutor(
        configuration=_configuration(),
        repository_root=tmp_path,
        model=model,
    )

    observation = executor.execute(case)

    assert len(model.prompts) == 1
    assert "Identify contradictions and missing clarifications." in model.prompts[0]
    assert "Cancellation must be possible before dispatch." in model.prompts[0]
    assert "GT-FIND-001" not in model.prompts[0]
    assert observation.boundary == "model_analysis"
    assert observation.side_effects == B0_SIDE_EFFECTS
    assert observation.ground_truth_ids == ("GT-FIND-001",)
    assert observation.source_references == ("REQ-001#statement",)
    assert observation.cost == 0.25


def test_b0_rejects_oversized_prompt_before_calling_the_model(tmp_path: Path) -> None:
    case = _case_with_artifact(tmp_path, artifact_content="x" * 100)
    model = StubModel(
        NaiveBaselineModelResponse(
            content="{}",
            cost=0,
        )
    )
    executor = NaiveBaselineExecutor(
        configuration=_configuration(maximum_prompt_characters=50),
        repository_root=tmp_path,
        model=model,
    )

    with pytest.raises(NaiveBaselineRejected, match="maximum_prompt_characters"):
        executor.execute(case)

    assert model.prompts == []


def test_b0_rejects_non_json_model_response_after_its_single_call(
    tmp_path: Path,
) -> None:
    case = _case_with_artifact(tmp_path, artifact_content="Requirement text.")
    model = StubModel(
        NaiveBaselineModelResponse(
            content="This is not JSON.",
            cost=0.1,
        )
    )
    executor = NaiveBaselineExecutor(
        configuration=_configuration(),
        repository_root=tmp_path,
        model=model,
    )

    with pytest.raises(NaiveBaselineRejected, match="JSON object"):
        executor.execute(case)

    assert len(model.prompts) == 1


def test_b0_rejects_configuration_with_an_extra_side_effect(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        "\n".join(
            (
                "schema_version: naive-baseline/v1",
                "baseline_id: B0",
                "baseline_version: 1",
                "prompt_version: b0-single-prompt/v1",
                "maximum_prompt_characters: 100",
                "data_classification: synthetic_or_public_only",
                "side_effect_schema: side-effects/v1",
                "side_effects:",
                "  chunks: 1",
                "  embeddings: 0",
                "  model_calls: 1",
                "  execution_candidates: 0",
                "  automatic_retries: 0",
                "  dns_requests: 0",
                "  http_requests: 0",
                "  execution_plans: 0",
                "  target_configuration_mutations: 0",
                "  approval_mutations: 0",
                "  secret_exposures: 0",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(NaiveBaselineRejected, match="one model call"):
        load_naive_baseline_config(config_path)


def _case_with_artifact(tmp_path: Path, *, artifact_content: str) -> EvaluationCase:
    artifact_path = tmp_path / "fixtures" / "requirements.md"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(artifact_content, encoding="utf-8")

    artifact = EvaluationArtifact(
        artifact_id="REQ-001",
        path="fixtures/requirements.md",
        sha256=sha256(artifact_content.encode("utf-8")).hexdigest(),
    )

    return EvaluationCase(
        id="EVAL-B0-001",
        version=1,
        split="development",
        category="requirement_quality",
        tags=("baseline",),
        criticality="medium",
        run_mode="analysis",
        side_effect_schema=SIDE_EFFECTS_SCHEMA_VERSION,
        inputs=EvaluationInputs(
            artifacts=(artifact,),
            overlays=(),
            user_request="Identify contradictions and missing clarifications.",
        ),
        expected=EvaluationExpected(
            required_ground_truth_ids=("GT-FIND-001",),
            prohibited_ground_truth_ids=(),
            expected_source_references=("REQ-001#statement",),
            policy_boundary="model_analysis",
            side_effects=dict(B0_SIDE_EFFECTS),
            scorer_version="deterministic-evaluation/v1",
            maximum_expected_cost=1,
        ),
    )


def _configuration(
    *,
    maximum_prompt_characters: int = 10_000,
) -> NaiveBaselineConfig:
    return NaiveBaselineConfig(
        schema_version="naive-baseline/v1",
        baseline_id="B0",
        baseline_version=1,
        prompt_version="b0-single-prompt/v1",
        maximum_prompt_characters=maximum_prompt_characters,
        data_classification="synthetic_or_public_only",
        side_effect_schema=SIDE_EFFECTS_SCHEMA_VERSION,
        side_effects=dict(B0_SIDE_EFFECTS),
    )
