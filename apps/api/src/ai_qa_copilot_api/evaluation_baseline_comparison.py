"""Compare B0 baseline and grounded evaluation-score reports deterministically."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from pathlib import Path

from ai_qa_copilot_api.evaluation_scoring import (
    EVALUATION_SCORE_REPORT_SCHEMA_VERSION,
    EvaluationScore,
    EvaluationScoreCheck,
    EvaluationScoreReport,
)


BASELINE_COMPARISON_REPORT_SCHEMA_VERSION = "baseline-comparison-report/v1"


class EvaluationBaselineComparisonRejected(ValueError):
    """Raised when two score reports cannot be compared fairly."""


@dataclass(frozen=True)
class EvaluationScoreSummary:
    """A compact, explicit result summary for one scored workflow."""

    label: str
    score_report_sha256: str
    passed: bool
    case_count: int
    passed_case_count: int
    failed_case_count: int
    check_count: int
    passed_check_count: int
    failed_check_count: int


@dataclass(frozen=True)
class EvaluationCheckComparison:
    """One failed check from B0, the grounded workflow, or both."""

    case_id: str
    code: str
    baseline_expected: object
    baseline_passed: bool
    baseline_actual: object
    grounded_expected: object
    grounded_passed: bool
    grounded_actual: object


@dataclass(frozen=True)
class EvaluationBaselineComparisonReport:
    """Immutable comparison evidence explaining B0 relative to grounded results."""

    schema_version: str
    suite_id: str
    case_fixture_sha256: str
    ground_truth_sha256: str
    scorer_version: str
    baseline: EvaluationScoreSummary
    grounded: EvaluationScoreSummary
    check_comparisons: tuple[EvaluationCheckComparison, ...]

    def as_json(self) -> str:
        return (
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "suite_id": self.suite_id,
                    "case_fixture_sha256": self.case_fixture_sha256,
                    "ground_truth_sha256": self.ground_truth_sha256,
                    "scorer_version": self.scorer_version,
                    "baseline": _summary_as_mapping(self.baseline),
                    "grounded": _summary_as_mapping(self.grounded),
                    "check_comparisons": [
                        {
                            "case_id": comparison.case_id,
                            "code": comparison.code,
                            "baseline_expected": _json_value(
                                comparison.baseline_expected
                            ),
                            "grounded_expected": _json_value(
                                comparison.grounded_expected
                            ),
                            "baseline_passed": comparison.baseline_passed,
                            "baseline_actual": _json_value(comparison.baseline_actual),
                            "grounded_passed": comparison.grounded_passed,
                            "grounded_actual": _json_value(comparison.grounded_actual),
                        }
                        for comparison in self.check_comparisons
                    ],
                },
                indent=2,
                sort_keys=True,
                separators=(",", ": "),
            )
            + "\n"
        )

    def as_markdown(self) -> str:
        """Render a human-readable explanation without altering source reports."""

        lines = [
            "# Evaluation Baseline Comparison",
            "",
            "## Provenance",
            "",
            f"- Suite ID: `{self.suite_id}`",
            f"- Scorer version: `{self.scorer_version}`",
            f"- Case fixture SHA-256: `{self.case_fixture_sha256}`",
            f"- Ground-truth SHA-256: `{self.ground_truth_sha256}`",
            "",
            "## Results",
            "",
            _summary_markdown_line(self.baseline),
            _summary_markdown_line(self.grounded),
        ]

        baseline_only = tuple(
            comparison
            for comparison in self.check_comparisons
            if not comparison.baseline_passed and comparison.grounded_passed
        )
        grounded_only = tuple(
            comparison
            for comparison in self.check_comparisons
            if comparison.baseline_passed and not comparison.grounded_passed
        )
        shared_failures = tuple(
            comparison
            for comparison in self.check_comparisons
            if not comparison.baseline_passed and not comparison.grounded_passed
        )

        lines.extend(
            _comparison_section(
                "B0-only failures",
                baseline_only,
                baseline_label=self.baseline.label,
                grounded_label=self.grounded.label,
            )
        )
        lines.extend(
            _comparison_section(
                "Grounded-only failures",
                grounded_only,
                baseline_label=self.baseline.label,
                grounded_label=self.grounded.label,
            )
        )
        lines.extend(
            _comparison_section(
                "Shared failures",
                shared_failures,
                baseline_label=self.baseline.label,
                grounded_label=self.grounded.label,
            )
        )

        if not self.check_comparisons:
            lines.extend(
                (
                    "",
                    "## Check comparison",
                    "",
                    "Both workflows passed every deterministic check.",
                )
            )

        return "\n".join(lines) + "\n"


def compare_evaluation_score_reports(
    *,
    baseline_report: EvaluationScoreReport,
    grounded_report: EvaluationScoreReport,
    baseline_label: str,
    grounded_label: str,
) -> EvaluationBaselineComparisonReport:
    """Compare equivalent score reports and retain all failing-check evidence."""

    _validate_comparable_reports(baseline_report, grounded_report)

    comparisons: list[EvaluationCheckComparison] = []
    for baseline_score, grounded_score in zip(
        baseline_report.scores,
        grounded_report.scores,
        strict=True,
    ):
        if baseline_score.case_id != grounded_score.case_id:
            raise EvaluationBaselineComparisonRejected(
                "Score reports must use the same ordered case IDs"
            )

        _append_check_comparisons(
            comparisons,
            case_id=baseline_score.case_id,
            baseline_checks=baseline_score.checks,
            grounded_checks=grounded_score.checks,
        )

    return EvaluationBaselineComparisonReport(
        schema_version=BASELINE_COMPARISON_REPORT_SCHEMA_VERSION,
        suite_id=baseline_report.suite_id,
        case_fixture_sha256=baseline_report.case_fixture_sha256,
        ground_truth_sha256=baseline_report.ground_truth_sha256,
        scorer_version=baseline_report.scorer_version,
        baseline=_summary_from_report(baseline_label, baseline_report),
        grounded=_summary_from_report(grounded_label, grounded_report),
        check_comparisons=tuple(comparisons),
    )


def load_evaluation_score_report(path: Path) -> EvaluationScoreReport:
    """Load and validate one immutable evaluation-score-report/v1 artifact."""

    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as error:
        raise EvaluationBaselineComparisonRejected(
            f"Evaluation score report could not be read: {path}"
        ) from error

    return evaluation_score_report_from_json(payload)


def evaluation_score_report_from_json(payload: str) -> EvaluationScoreReport:
    """Parse only the strict JSON shape emitted by EvaluationScoreReport.as_json()."""

    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as error:
        raise EvaluationBaselineComparisonRejected(
            "Evaluation score report must be valid JSON"
        ) from error

    report = _json_mapping(raw, "Evaluation score report")
    _require_json_fields(
        report,
        {
            "schema_version",
            "scorer_version",
            "suite_id",
            "case_fixture_sha256",
            "ground_truth_sha256",
            "run_sha256",
            "passed",
            "scores",
        },
        "Evaluation score report",
    )

    scores = tuple(
        _score_from_json_mapping(score, f"scores[{index}]")
        for index, score in enumerate(_json_list(report["scores"], "scores"))
    )
    parsed = EvaluationScoreReport(
        schema_version=_json_text(report["schema_version"], "schema_version"),
        scorer_version=_json_text(report["scorer_version"], "scorer_version"),
        suite_id=_json_text(report["suite_id"], "suite_id"),
        case_fixture_sha256=_json_sha256(
            report["case_fixture_sha256"],
            "case_fixture_sha256",
        ),
        ground_truth_sha256=_json_sha256(
            report["ground_truth_sha256"],
            "ground_truth_sha256",
        ),
        run_sha256=_json_sha256(report["run_sha256"], "run_sha256"),
        passed=_json_boolean(report["passed"], "passed"),
        scores=scores,
    )

    if parsed.schema_version != EVALUATION_SCORE_REPORT_SCHEMA_VERSION:
        raise EvaluationBaselineComparisonRejected(
            "Evaluation score report has an unsupported schema version"
        )
    if parsed.passed != all(score.passed for score in parsed.scores):
        raise EvaluationBaselineComparisonRejected(
            "Evaluation score report passed status does not match its scores"
        )

    return parsed


def _score_from_json_mapping(value: object, label: str) -> EvaluationScore:
    score = _json_mapping(value, label)
    _require_json_fields(
        score,
        {"case_id", "scorer_version", "passed", "checks"},
        label,
    )

    checks = tuple(
        _check_from_json_mapping(check, f"{label}.checks[{index}]")
        for index, check in enumerate(_json_list(score["checks"], f"{label}.checks"))
    )
    parsed = EvaluationScore(
        case_id=_json_text(score["case_id"], f"{label}.case_id"),
        scorer_version=_json_text(
            score["scorer_version"],
            f"{label}.scorer_version",
        ),
        passed=_json_boolean(score["passed"], f"{label}.passed"),
        checks=checks,
    )

    if parsed.passed != all(check.passed for check in parsed.checks):
        raise EvaluationBaselineComparisonRejected(
            f"{label}.passed does not match its checks"
        )

    return parsed


def _check_from_json_mapping(value: object, label: str) -> EvaluationScoreCheck:
    check = _json_mapping(value, label)
    _require_json_fields(
        check,
        {"code", "passed", "expected", "actual"},
        label,
    )

    return EvaluationScoreCheck(
        code=_json_text(check["code"], f"{label}.code"),
        passed=_json_boolean(check["passed"], f"{label}.passed"),
        expected=check["expected"],
        actual=check["actual"],
    )


def _json_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise EvaluationBaselineComparisonRejected(
            f"{label} must be a mapping with string keys"
        )
    return cast(Mapping[str, object], value)


def _json_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise EvaluationBaselineComparisonRejected(f"{label} must be a list")
    return value


def _json_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationBaselineComparisonRejected(f"{label} must be non-empty text")
    return value.strip()


def _json_boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationBaselineComparisonRejected(f"{label} must be boolean")
    return value


def _json_sha256(value: object, label: str) -> str:
    sha256 = _json_text(value, label)
    if len(sha256) != 64 or any(
        character not in "0123456789abcdef" for character in sha256
    ):
        raise EvaluationBaselineComparisonRejected(
            f"{label} must be a lowercase SHA-256 value"
        )
    return sha256


def _require_json_fields(
    value: Mapping[str, object],
    expected_fields: set[str],
    label: str,
) -> None:
    if set(value) != expected_fields:
        raise EvaluationBaselineComparisonRejected(
            f"{label} fields must be exactly {sorted(expected_fields)}"
        )


def _validate_comparable_reports(
    baseline_report: EvaluationScoreReport,
    grounded_report: EvaluationScoreReport,
) -> None:
    for report, label in (
        (baseline_report, "Baseline"),
        (grounded_report, "Grounded"),
    ):
        if report.schema_version != EVALUATION_SCORE_REPORT_SCHEMA_VERSION:
            raise EvaluationBaselineComparisonRejected(
                f"{label} report has an unsupported schema version"
            )

    for attribute_name in (
        "suite_id",
        "case_fixture_sha256",
        "ground_truth_sha256",
        "scorer_version",
    ):
        if getattr(baseline_report, attribute_name) != getattr(
            grounded_report,
            attribute_name,
        ):
            raise EvaluationBaselineComparisonRejected(
                f"Score reports differ for {attribute_name}"
            )

    if len(baseline_report.scores) != len(grounded_report.scores):
        raise EvaluationBaselineComparisonRejected(
            "Score reports must contain the same number of cases"
        )


def _append_check_comparisons(
    comparisons: list[EvaluationCheckComparison],
    *,
    case_id: str,
    baseline_checks: tuple[EvaluationScoreCheck, ...],
    grounded_checks: tuple[EvaluationScoreCheck, ...],
) -> None:
    if len(baseline_checks) != len(grounded_checks):
        raise EvaluationBaselineComparisonRejected(
            f"Score reports differ in check count for {case_id}"
        )

    for baseline_check, grounded_check in zip(
        baseline_checks,
        grounded_checks,
        strict=True,
    ):
        if baseline_check.code != grounded_check.code:
            raise EvaluationBaselineComparisonRejected(
                f"Score reports differ in check code for {case_id}"
            )

        if not baseline_check.passed or not grounded_check.passed:
            comparisons.append(
                EvaluationCheckComparison(
                    case_id=case_id,
                    code=baseline_check.code,
                    baseline_expected=baseline_check.expected,
                    baseline_passed=baseline_check.passed,
                    baseline_actual=baseline_check.actual,
                    grounded_expected=grounded_check.expected,
                    grounded_passed=grounded_check.passed,
                    grounded_actual=grounded_check.actual,
                )
            )


def _summary_from_report(
    label: str,
    report: EvaluationScoreReport,
) -> EvaluationScoreSummary:
    check_count = sum(len(score.checks) for score in report.scores)
    passed_check_count = sum(
        check.passed for score in report.scores for check in score.checks
    )
    passed_case_count = sum(score.passed for score in report.scores)

    return EvaluationScoreSummary(
        label=_require_text(label, "label"),
        score_report_sha256=hashlib.sha256(
            report.as_json().encode("utf-8")
        ).hexdigest(),
        passed=report.passed,
        case_count=len(report.scores),
        passed_case_count=passed_case_count,
        failed_case_count=len(report.scores) - passed_case_count,
        check_count=check_count,
        passed_check_count=passed_check_count,
        failed_check_count=check_count - passed_check_count,
    )


def _summary_as_mapping(summary: EvaluationScoreSummary) -> dict[str, object]:
    return {
        "label": summary.label,
        "score_report_sha256": summary.score_report_sha256,
        "passed": summary.passed,
        "case_count": summary.case_count,
        "passed_case_count": summary.passed_case_count,
        "failed_case_count": summary.failed_case_count,
        "check_count": summary.check_count,
        "passed_check_count": summary.passed_check_count,
        "failed_check_count": summary.failed_check_count,
    }


def _summary_markdown_line(summary: EvaluationScoreSummary) -> str:
    status = "passed" if summary.passed else "failed"
    return (
        f"- **{summary.label}:** {status}; "
        f"{summary.passed_case_count}/{summary.case_count} cases passed; "
        f"{summary.passed_check_count}/{summary.check_count} checks passed."
    )


def _comparison_section(
    heading: str,
    comparisons: tuple[EvaluationCheckComparison, ...],
    *,
    baseline_label: str,
    grounded_label: str,
) -> tuple[str, ...]:
    lines = ["", f"## {heading}", ""]

    if not comparisons:
        return tuple(lines + ["None."])

    for comparison in comparisons:
        lines.extend(
            (
                f"### `{comparison.case_id}` — `{comparison.code}`",
                "",
                (
                    f"- {baseline_label} expected: "
                    f"`{_render_value(comparison.baseline_expected)}`"
                ),
                (
                    f"- {baseline_label}: "
                    f"{_status(comparison.baseline_passed)} "
                    f"(`{_render_value(comparison.baseline_actual)}`)"
                ),
                (
                    f"- {grounded_label} expected: "
                    f"`{_render_value(comparison.grounded_expected)}`"
                ),
                (
                    f"- {grounded_label}: "
                    f"{_status(comparison.grounded_passed)} "
                    f"(`{_render_value(comparison.grounded_actual)}`)"
                ),
                "",
            )
        )

    return tuple(lines)


def _status(passed: bool) -> str:
    return "passed" if passed else "failed"


def _render_value(value: object) -> str:
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_value(value: object) -> object:
    if isinstance(value, set | frozenset):
        converted = [_json_value(item) for item in value]
        return sorted(
            converted,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return value


def _require_text(value: str, label: str) -> str:
    if not value.strip():
        raise EvaluationBaselineComparisonRejected(f"{label} must be non-empty text")
    return value.strip()
