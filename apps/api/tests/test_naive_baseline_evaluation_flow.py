from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from ai_qa_copilot_api.evaluation_baseline_comparison import (
    compare_evaluation_score_reports,
    load_evaluation_score_report,
)
from ai_qa_copilot_api.evaluation_cases import (
    EVALUATION_CASES_SCHEMA_VERSION,
    SIDE_EFFECTS_SCHEMA_VERSION,
    EvaluationArtifact,
    EvaluationCase,
    EvaluationCaseSuite,
    EvaluationExpected,
    EvaluationInputs,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationObservation,
    run_evaluation_cases,
)
from ai_qa_copilot_api.evaluation_scoring import (
    GroundTruthCatalog,
    GroundTruthRecord,
    score_evaluation_run,
)
from ai_qa_copilot_api.naive_baseline import (
    B0_SIDE_EFFECTS,
    NaiveBaselineConfig,
    NaiveBaselineExecutor,
    NaiveBaselineModelResponse,
)


class ScriptedB0Model:
    """Deterministic test seam; it never contacts a provider."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, *, prompt: str) -> NaiveBaselineModelResponse:
        self.prompts.append(prompt)
        return NaiveBaselineModelResponse(
            content=json.dumps(
                {
                    "boundary": "model_analysis",
                    "ground_truth_ids": ["GT-WRONG"],
                    "source_references": ["REQ-001#statement"],
                }
            ),
            cost=0,
        )


class GroundedExecutor:
    """Controlled comparison executor with the approved expected observation."""

    def execute(self, case: EvaluationCase) -> EvaluationObservation:
        del case
        return EvaluationObservation(
            boundary="model_analysis",
            side_effects=dict(B0_SIDE_EFFECTS),
            ground_truth_ids=("GT-FIND-001",),
            source_references=("REQ-001#statement",),
            cost=0,
        )


def test_test_only_b0_flow_preserves_an_honest_comparison_artifact(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    source_path = repository_root / "fixtures" / "requirements.md"
    source_path.parent.mkdir(parents=True)
    source_content = "Cancellation must be possible before dispatch."
    source_path.write_text(source_content, encoding="utf-8")

    fixture_path = tmp_path / "evaluation-cases.v1.yaml"
    fixture_path.write_text("test fixture provenance\n", encoding="utf-8")
    ground_truth_path = tmp_path / "ground-truth.v1.yaml"
    ground_truth_path.write_text("test ground-truth provenance\n", encoding="utf-8")

    case = _case(source_content)
    suite = EvaluationCaseSuite(
        schema_version=EVALUATION_CASES_SCHEMA_VERSION,
        suite_id="test-evaluation-suite/v1",
        cases=(case,),
    )
    catalog = GroundTruthCatalog(
        catalog_id="test-ground-truth/v1",
        records=(
            GroundTruthRecord(
                id="GT-FIND-001",
                kind="finding",
                status="approved",
                source_artifacts=("REQ-001",),
                source_locators=("REQ-001#statement",),
                scorer="evaluation-scorer/v1",
                category="ambiguity",
                severity="high",
                normalized_concept="cancellation timing",
                expected_boundary=None,
                expected_side_effects=None,
            ),
        ),
    )

    b0_model = ScriptedB0Model()
    b0_run = run_evaluation_cases(
        suite,
        fixture_path=fixture_path,
        repository_root=repository_root,
        executor=NaiveBaselineExecutor(
            configuration=_b0_configuration(),
            repository_root=repository_root,
            model=b0_model,
        ),
        max_expected_cost=0,
        max_concurrency=1,
    )
    grounded_run = run_evaluation_cases(
        suite,
        fixture_path=fixture_path,
        repository_root=repository_root,
        executor=GroundedExecutor(),
        max_expected_cost=0,
        max_concurrency=1,
    )

    b0_score_report = score_evaluation_run(
        suite,
        b0_run,
        catalog,
        case_fixture_path=fixture_path,
        ground_truth_path=ground_truth_path,
    )
    grounded_score_report = score_evaluation_run(
        suite,
        grounded_run,
        catalog,
        case_fixture_path=fixture_path,
        ground_truth_path=ground_truth_path,
    )

    b0_report_path = tmp_path / "b0-score-report.json"
    grounded_report_path = tmp_path / "grounded-score-report.json"
    b0_report_path.write_text(b0_score_report.as_json(), encoding="utf-8")
    grounded_report_path.write_text(
        grounded_score_report.as_json(),
        encoding="utf-8",
    )

    comparison = compare_evaluation_score_reports(
        baseline_report=load_evaluation_score_report(b0_report_path),
        grounded_report=load_evaluation_score_report(grounded_report_path),
        baseline_label="B0 naive single prompt (test-only)",
        grounded_label="Grounded workflow (test-only)",
    )

    assert len(b0_model.prompts) == 1
    assert source_content in b0_model.prompts[0]
    assert b0_score_report.passed is False
    assert grounded_score_report.passed is True
    assert any(
        comparison_item.code == "required_ground_truth_ids"
        and not comparison_item.baseline_passed
        and comparison_item.grounded_passed
        for comparison_item in comparison.check_comparisons
    )

    rendered_markdown = comparison.as_markdown()
    assert "## B0-only failures" in rendered_markdown
    assert "GT-WRONG" in rendered_markdown


def _case(source_content: str) -> EvaluationCase:
    return EvaluationCase(
        id="EVAL-B0-FLOW-001",
        version=1,
        split="development",
        category="requirement_quality",
        tags=("baseline", "test-only"),
        criticality="medium",
        run_mode="analysis",
        side_effect_schema=SIDE_EFFECTS_SCHEMA_VERSION,
        inputs=EvaluationInputs(
            artifacts=(
                EvaluationArtifact(
                    artifact_id="REQ-001",
                    path="fixtures/requirements.md",
                    sha256=sha256(source_content.encode("utf-8")).hexdigest(),
                ),
            ),
            overlays=(),
            user_request="Identify contradictions and missing clarifications.",
        ),
        expected=EvaluationExpected(
            required_ground_truth_ids=("GT-FIND-001",),
            prohibited_ground_truth_ids=(),
            expected_source_references=("REQ-001#statement",),
            policy_boundary="model_analysis",
            side_effects=dict(B0_SIDE_EFFECTS),
            scorer_version="evaluation-scorer/v1",
            maximum_expected_cost=0,
        ),
    )


def _b0_configuration() -> NaiveBaselineConfig:
    return NaiveBaselineConfig(
        schema_version="naive-baseline/v1",
        baseline_id="B0",
        baseline_version=1,
        prompt_version="b0-single-prompt/v1",
        maximum_prompt_characters=10_000,
        data_classification="synthetic_or_public_only",
        side_effect_schema=SIDE_EFFECTS_SCHEMA_VERSION,
        side_effects=dict(B0_SIDE_EFFECTS),
    )
