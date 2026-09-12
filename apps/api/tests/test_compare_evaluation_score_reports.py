from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ai_qa_copilot_api.evaluation_scoring import (
    EVALUATION_SCORE_REPORT_SCHEMA_VERSION,
    EvaluationScore,
    EvaluationScoreCheck,
    EvaluationScoreReport,
)


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "compare_evaluation_score_reports.py"


def test_cli_writes_json_and_markdown_comparison_artifacts(tmp_path: Path) -> None:
    baseline_path = tmp_path / "b0-score-report.json"
    grounded_path = tmp_path / "grounded-score-report.json"
    output_path = tmp_path / "comparison.json"
    markdown_path = tmp_path / "comparison.md"

    baseline_path.write_text(_report().as_json(), encoding="utf-8")
    grounded_path.write_text(_report().as_json(), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--baseline-score-report",
            str(baseline_path),
            "--grounded-score-report",
            str(grounded_path),
            "--output",
            str(output_path),
            "--markdown-output",
            str(markdown_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert output_path.is_file()
    assert markdown_path.is_file()
    assert '"schema_version": "baseline-comparison-report/v1"' in output_path.read_text(
        encoding="utf-8"
    )
    assert "# Evaluation Baseline Comparison" in markdown_path.read_text(
        encoding="utf-8"
    )


def test_cli_refuses_to_replace_existing_evidence(tmp_path: Path) -> None:
    baseline_path = tmp_path / "b0-score-report.json"
    grounded_path = tmp_path / "grounded-score-report.json"
    output_path = tmp_path / "comparison.json"
    markdown_path = tmp_path / "comparison.md"

    baseline_path.write_text(_report().as_json(), encoding="utf-8")
    grounded_path.write_text(_report().as_json(), encoding="utf-8")
    output_path.write_text("existing evidence\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--baseline-score-report",
            str(baseline_path),
            "--grounded-score-report",
            str(grounded_path),
            "--output",
            str(output_path),
            "--markdown-output",
            str(markdown_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "JSON output already exists" in result.stderr
    assert not markdown_path.exists()


def _report() -> EvaluationScoreReport:
    return EvaluationScoreReport(
        schema_version=EVALUATION_SCORE_REPORT_SCHEMA_VERSION,
        scorer_version="evaluation-scorer/v1",
        suite_id="test-suite/v1",
        case_fixture_sha256="a" * 64,
        ground_truth_sha256="b" * 64,
        run_sha256="c" * 64,
        passed=True,
        scores=(
            EvaluationScore(
                case_id="EVAL-001",
                scorer_version="evaluation-scorer/v1",
                passed=True,
                checks=(
                    EvaluationScoreCheck(
                        code="required_ground_truth_ids",
                        passed=True,
                        expected=["GT-FIND-001"],
                        actual=["GT-FIND-001"],
                    ),
                ),
            ),
        ),
    )
