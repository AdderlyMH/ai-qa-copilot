from __future__ import annotations

import pytest
import json
from pathlib import Path

from ai_qa_copilot_api.evaluation_baseline_comparison import (
    EvaluationBaselineComparisonRejected,
    compare_evaluation_score_reports,
)
from ai_qa_copilot_api.evaluation_scoring import (
    EVALUATION_SCORE_REPORT_SCHEMA_VERSION,
    EvaluationScore,
    EvaluationScoreCheck,
    EvaluationScoreReport,
)


def test_comparison_documents_b0_only_failure_in_json_and_markdown() -> None:
    comparison = compare_evaluation_score_reports(
        baseline_report=_report(
            passed=False,
            check_passed=False,
            actual=["GT-WRONG"],
        ),
        grounded_report=_report(
            passed=True,
            check_passed=True,
            actual=["GT-FIND-001"],
        ),
        baseline_label="B0 naive single prompt",
        grounded_label="Grounded workflow",
    )

    assert comparison.baseline.failed_case_count == 1
    assert comparison.grounded.failed_case_count == 0
    assert len(comparison.check_comparisons) == 1

    rendered_json = comparison.as_json()
    rendered_markdown = comparison.as_markdown()

    assert '"baseline_passed": false' in rendered_json
    assert "## B0-only failures" in rendered_markdown
    assert "`EVAL-001` — `required_ground_truth_ids`" in rendered_markdown
    assert "B0 naive single prompt: failed" in rendered_markdown


def test_comparison_preserves_shared_failures() -> None:
    comparison = compare_evaluation_score_reports(
        baseline_report=_report(
            passed=False,
            check_passed=False,
            actual=[],
        ),
        grounded_report=_report(
            passed=False,
            check_passed=False,
            actual=[],
        ),
        baseline_label="B0",
        grounded_label="Grounded",
    )

    rendered_markdown = comparison.as_markdown()

    assert "## Shared failures" in rendered_markdown
    assert "## B0-only failures\n\nNone." in rendered_markdown
    assert "## Grounded-only failures\n\nNone." in rendered_markdown


def test_comparison_rejects_different_ground_truth_provenance() -> None:
    baseline = _report(passed=True, check_passed=True, actual=["GT-FIND-001"])
    grounded = EvaluationScoreReport(
        schema_version=baseline.schema_version,
        scorer_version=baseline.scorer_version,
        suite_id=baseline.suite_id,
        case_fixture_sha256=baseline.case_fixture_sha256,
        ground_truth_sha256="d" * 64,
        run_sha256=baseline.run_sha256,
        passed=baseline.passed,
        scores=baseline.scores,
    )

    with pytest.raises(
        EvaluationBaselineComparisonRejected,
        match="ground_truth_sha256",
    ):
        compare_evaluation_score_reports(
            baseline_report=baseline,
            grounded_report=grounded,
            baseline_label="B0",
            grounded_label="Grounded",
        )


def test_comparison_rejects_different_check_contracts() -> None:
    baseline = _report(passed=True, check_passed=True, actual=["GT-FIND-001"])
    grounded = EvaluationScoreReport(
        schema_version=baseline.schema_version,
        scorer_version=baseline.scorer_version,
        suite_id=baseline.suite_id,
        case_fixture_sha256=baseline.case_fixture_sha256,
        ground_truth_sha256=baseline.ground_truth_sha256,
        run_sha256=baseline.run_sha256,
        passed=False,
        scores=(
            EvaluationScore(
                case_id="EVAL-001",
                scorer_version=baseline.scorer_version,
                passed=False,
                checks=(
                    EvaluationScoreCheck(
                        code="different_check",
                        passed=False,
                        expected=["GT-FIND-001"],
                        actual=[],
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(
        EvaluationBaselineComparisonRejected,
        match="check code",
    ):
        compare_evaluation_score_reports(
            baseline_report=baseline,
            grounded_report=grounded,
            baseline_label="B0",
            grounded_label="Grounded",
        )


def test_score_report_json_round_trip_preserves_comparable_report(
    tmp_path: Path,
) -> None:
    from ai_qa_copilot_api.evaluation_baseline_comparison import (
        evaluation_score_report_from_json,
        load_evaluation_score_report,
    )

    original = _report(passed=True, check_passed=True, actual=["GT-FIND-001"])
    report_path = tmp_path / "score-report.json"
    report_path.write_text(original.as_json(), encoding="utf-8")

    assert evaluation_score_report_from_json(original.as_json()) == original
    assert load_evaluation_score_report(report_path) == original


def test_score_report_loader_rejects_inconsistent_pass_status() -> None:
    from ai_qa_copilot_api.evaluation_baseline_comparison import (
        evaluation_score_report_from_json,
    )

    payload = json.loads(
        _report(
            passed=True,
            check_passed=True,
            actual=["GT-FIND-001"],
        ).as_json()
    )
    payload["passed"] = False

    with pytest.raises(
        EvaluationBaselineComparisonRejected,
        match="passed status",
    ):
        evaluation_score_report_from_json(json.dumps(payload))


def _report(
    *,
    passed: bool,
    check_passed: bool,
    actual: list[str],
) -> EvaluationScoreReport:
    return EvaluationScoreReport(
        schema_version=EVALUATION_SCORE_REPORT_SCHEMA_VERSION,
        scorer_version="deterministic-evaluation/v1",
        suite_id="evaluation-cases-dev/v1",
        case_fixture_sha256="a" * 64,
        ground_truth_sha256="b" * 64,
        run_sha256="c" * 64,
        passed=passed,
        scores=(
            EvaluationScore(
                case_id="EVAL-001",
                scorer_version="deterministic-evaluation/v1",
                passed=check_passed,
                checks=(
                    EvaluationScoreCheck(
                        code="required_ground_truth_ids",
                        passed=check_passed,
                        expected=["GT-FIND-001"],
                        actual=actual,
                    ),
                ),
            ),
        ),
    )


def test_comparison_allows_output_dependent_expected_values() -> None:
    baseline = _report(
        passed=False,
        check_passed=False,
        actual=["GT-WRONG"],
    )
    grounded = _report(
        passed=True,
        check_passed=True,
        actual=["GT-FIND-001"],
    )

    baseline_check = baseline.scores[0].checks[0]
    baseline_score = baseline.scores[0]
    baseline = EvaluationScoreReport(
        schema_version=baseline.schema_version,
        scorer_version=baseline.scorer_version,
        suite_id=baseline.suite_id,
        case_fixture_sha256=baseline.case_fixture_sha256,
        ground_truth_sha256=baseline.ground_truth_sha256,
        run_sha256=baseline.run_sha256,
        passed=baseline.passed,
        scores=(
            EvaluationScore(
                case_id=baseline_score.case_id,
                scorer_version=baseline_score.scorer_version,
                passed=baseline_score.passed,
                checks=(
                    EvaluationScoreCheck(
                        code=baseline_check.code,
                        passed=baseline_check.passed,
                        expected=["GT-WRONG"],
                        actual=baseline_check.actual,
                    ),
                ),
            ),
        ),
    )

    comparison = compare_evaluation_score_reports(
        baseline_report=baseline,
        grounded_report=grounded,
        baseline_label="B0",
        grounded_label="Grounded",
    )

    assert comparison.check_comparisons[0].baseline_expected == ["GT-WRONG"]
    assert comparison.check_comparisons[0].grounded_expected == ["GT-FIND-001"]
