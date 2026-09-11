"""Deterministic scoring for versioned evaluation observations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import cast

import yaml

from ai_qa_copilot_api.evaluation_cases import (
    SIDE_EFFECT_FIELD_NAMES,
    EvaluationCase,
    EvaluationCaseSuite,
)
from ai_qa_copilot_api.evaluation_runner import (
    EVALUATION_RUN_SCHEMA_VERSION,
    EvaluationObservation,
    EvaluationRun,
    EvaluationRunCaseResult,
    evaluation_case_sha256,
)


GROUND_TRUTH_SCHEMA_VERSION = "ground-truth/v1"
DETERMINISTIC_SCORER_VERSION = "deterministic-evaluation-scorer/v1"


class EvaluationScoringRejected(ValueError):
    """Raised when a ground-truth catalog or score input is invalid."""


@dataclass(frozen=True)
class GroundTruthRecord:
    id: str
    kind: str
    status: str
    source_artifacts: tuple[str, ...]
    source_locators: tuple[str, ...]
    scorer: str
    category: str | None
    severity: str | None
    normalized_concept: str | None
    expected_boundary: str | None
    expected_side_effects: dict[str, int] | None


@dataclass(frozen=True)
class GroundTruthCatalog:
    catalog_id: str
    records: tuple[GroundTruthRecord, ...]

    def record_for(self, ground_truth_id: str) -> GroundTruthRecord:
        for record in self.records:
            if record.id == ground_truth_id:
                return record
        raise EvaluationScoringRejected(
            f"Ground-truth record does not exist: {ground_truth_id}"
        )


@dataclass(frozen=True)
class EvaluationScoreCheck:
    code: str
    passed: bool
    expected: object
    actual: object


@dataclass(frozen=True)
class EvaluationScore:
    case_id: str
    scorer_version: str
    passed: bool
    checks: tuple[EvaluationScoreCheck, ...]


EVALUATION_SCORE_REPORT_SCHEMA_VERSION = "evaluation-score-report/v1"


@dataclass(frozen=True)
class EvaluationScoreReport:
    schema_version: str
    scorer_version: str
    suite_id: str
    case_fixture_sha256: str
    ground_truth_sha256: str
    run_sha256: str
    passed: bool
    scores: tuple[EvaluationScore, ...]

    def as_json(self) -> str:
        return (
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "scorer_version": self.scorer_version,
                    "suite_id": self.suite_id,
                    "case_fixture_sha256": self.case_fixture_sha256,
                    "ground_truth_sha256": self.ground_truth_sha256,
                    "run_sha256": self.run_sha256,
                    "passed": self.passed,
                    "scores": [
                        {
                            "case_id": score.case_id,
                            "scorer_version": score.scorer_version,
                            "passed": score.passed,
                            "checks": [
                                {
                                    "code": check.code,
                                    "passed": check.passed,
                                    "expected": _json_value(check.expected),
                                    "actual": _json_value(check.actual),
                                }
                                for check in score.checks
                            ],
                        }
                        for score in self.scores
                    ],
                },
                indent=2,
                sort_keys=True,
                separators=(",", ": "),
            )
            + "\n"
        )


def score_evaluation_run(
    suite: EvaluationCaseSuite,
    run: EvaluationRun,
    catalog: GroundTruthCatalog,
    *,
    case_fixture_path: Path,
    ground_truth_path: Path,
) -> EvaluationScoreReport:
    """Score a completed run only when its immutable provenance still matches."""

    case_fixture_sha256 = _sha256_file(case_fixture_path)
    ground_truth_sha256 = _sha256_file(ground_truth_path)

    if run.schema_version != EVALUATION_RUN_SCHEMA_VERSION:
        raise EvaluationScoringRejected(
            "Evaluation run has an unsupported schema version"
        )
    if run.suite_id != suite.suite_id:
        raise EvaluationScoringRejected("Evaluation run belongs to another suite")
    if run.fixture_sha256 != case_fixture_sha256:
        raise EvaluationScoringRejected(
            "Evaluation run fixture provenance does not match"
        )

    case_by_id = {case.id: case for case in suite.cases}
    result_ids = tuple(result.case_id for result in run.results)
    if result_ids != run.selected_case_ids:
        raise EvaluationScoringRejected(
            "Evaluation run results do not match the selected-case order"
        )

    scores = tuple(
        _score_run_result(result, case_by_id, catalog) for result in run.results
    )

    return EvaluationScoreReport(
        schema_version=EVALUATION_SCORE_REPORT_SCHEMA_VERSION,
        scorer_version=DETERMINISTIC_SCORER_VERSION,
        suite_id=suite.suite_id,
        case_fixture_sha256=case_fixture_sha256,
        ground_truth_sha256=ground_truth_sha256,
        run_sha256=hashlib.sha256(run.as_json().encode("utf-8")).hexdigest(),
        passed=all(score.passed for score in scores),
        scores=scores,
    )


def _score_run_result(
    result: EvaluationRunCaseResult,
    case_by_id: dict[str, EvaluationCase],
    catalog: GroundTruthCatalog,
) -> EvaluationScore:
    case = case_by_id.get(result.case_id)
    if case is None:
        raise EvaluationScoringRejected(
            f"Evaluation run refers to an unknown case: {result.case_id}"
        )
    if result.case_version != case.version:
        raise EvaluationScoringRejected(
            f"Evaluation run case version differs for {case.id}"
        )
    if result.case_sha256 != evaluation_case_sha256(case):
        raise EvaluationScoringRejected(
            f"Evaluation run case provenance differs for {case.id}"
        )

    return score_evaluation_observation(case, result.observation, catalog)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, set | frozenset):
        serialised_items = [_json_value(item) for item in value]
        return sorted(
            serialised_items,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    raise EvaluationScoringRejected(
        f"Score report contains a non-serializable value: {type(value).__name__}"
    )


def load_ground_truth_catalog(path: Path) -> GroundTruthCatalog:
    """Load the approved ground-truth registry used by deterministic scorers."""

    raw = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
    catalog = _require_mapping(raw, "Ground-truth catalog")

    if _require_text(catalog.get("schema_version"), "schema_version") != (
        GROUND_TRUTH_SCHEMA_VERSION
    ):
        raise EvaluationScoringRejected("Unsupported ground-truth schema version")

    records = _records_from_list(
        catalog.get("findings"), "findings", kind="finding"
    ) + _records_from_list(catalog.get("policies"), "policies", kind="policy")
    if not records:
        raise EvaluationScoringRejected(
            "Ground-truth catalog must declare at least one record"
        )

    record_ids = tuple(record.id for record in records)
    if len(set(record_ids)) != len(record_ids):
        raise EvaluationScoringRejected(
            "Ground-truth catalog contains duplicate record IDs"
        )

    return GroundTruthCatalog(
        catalog_id=_require_text(catalog.get("catalog_id"), "catalog_id"),
        records=records,
    )


def score_evaluation_observation(
    case: EvaluationCase,
    observation: EvaluationObservation,
    catalog: GroundTruthCatalog,
) -> EvaluationScore:
    """Score only objective EVAL-002 checks from one recorded observation."""

    expected_required_ids = set(case.expected.required_ground_truth_ids)
    expected_prohibited_ids = set(case.expected.prohibited_ground_truth_ids)
    observed_ids = set(observation.ground_truth_ids)

    referenced_artifact_ids = {
        artifact.artifact_id
        for artifact in case.inputs.artifacts + case.inputs.overlays
    }
    known_record_ids = {record.id for record in catalog.records}
    expected_record_ids = expected_required_ids | expected_prohibited_ids

    checks: list[EvaluationScoreCheck] = [
        _check(
            "known_expected_ground_truth_ids",
            expected_record_ids,
            expected_record_ids & known_record_ids,
        ),
        _check(
            "required_ground_truth_ids",
            expected_required_ids,
            observed_ids & expected_required_ids,
        ),
        _check(
            "prohibited_ground_truth_ids",
            set(),
            observed_ids & expected_prohibited_ids,
        ),
        _check(
            "unexpected_ground_truth_ids",
            set(),
            observed_ids - expected_required_ids,
        ),
        _check(
            "known_observed_ground_truth_ids",
            observed_ids,
            observed_ids & known_record_ids,
        ),
        _check(
            "expected_source_references",
            set(case.expected.expected_source_references),
            set(case.expected.expected_source_references)
            & set(observation.source_references),
        ),
        _check(
            "policy_boundary",
            case.expected.policy_boundary,
            observation.boundary,
        ),
        _check(
            "side_effects",
            case.expected.side_effects,
            dict(observation.side_effects),
        ),
        _check(
            "maximum_expected_cost",
            case.expected.maximum_expected_cost,
            observation.cost,
            passed=observation.cost <= case.expected.maximum_expected_cost,
        ),
    ]

    for ground_truth_id in sorted(expected_required_ids):
        if ground_truth_id not in known_record_ids:
            continue
        record = catalog.record_for(ground_truth_id)
        checks.append(
            _check(
                f"source_artifacts:{ground_truth_id}",
                set(record.source_artifacts),
                set(record.source_artifacts) & referenced_artifact_ids,
            )
        )

    return EvaluationScore(
        case_id=case.id,
        scorer_version=DETERMINISTIC_SCORER_VERSION,
        passed=all(check.passed for check in checks),
        checks=tuple(checks),
    )


def _records_from_list(
    value: object,
    label: str,
    *,
    kind: str,
) -> tuple[GroundTruthRecord, ...]:
    records = _require_list(value, label)
    return tuple(
        _record_from_mapping(record, f"{label}[{index}]", kind=kind)
        for index, record in enumerate(records)
    )


def _record_from_mapping(
    value: object,
    label: str,
    *,
    kind: str,
) -> GroundTruthRecord:
    record = _require_mapping(value, label)
    record_kind = _require_text(record.get("kind"), f"{label}.kind")
    if record_kind != kind:
        raise EvaluationScoringRejected(
            f"{label}.kind must be {kind}, got {record_kind}"
        )

    expected_boundary: str | None = None
    expected_side_effects: dict[str, int] | None = None

    if kind == "finding":
        category = _require_text(record.get("category"), f"{label}.category")
        severity = _require_text(record.get("severity"), f"{label}.severity")
        normalized_concept = _require_text(
            record.get("normalized_concept"),
            f"{label}.normalized_concept",
        )
    else:
        category = None
        severity = None
        normalized_concept = None
        expected_boundary = _require_text(
            record.get("expected_boundary"),
            f"{label}.expected_boundary",
        )
        expected_side_effects = _side_effects_from_mapping(
            record.get("expected_side_effects"),
            f"{label}.expected_side_effects",
        )

    return GroundTruthRecord(
        id=_require_text(record.get("id"), f"{label}.id"),
        kind=record_kind,
        status=_require_text(record.get("status"), f"{label}.status"),
        source_artifacts=_require_distinct_text_list(
            record.get("source_artifacts"),
            f"{label}.source_artifacts",
            non_empty=True,
        ),
        source_locators=_require_distinct_text_list(
            record.get("source_locators"),
            f"{label}.source_locators",
            non_empty=True,
        ),
        scorer=_require_text(record.get("scorer"), f"{label}.scorer"),
        category=category,
        severity=severity,
        normalized_concept=normalized_concept,
        expected_boundary=expected_boundary,
        expected_side_effects=expected_side_effects,
    )


def _side_effects_from_mapping(value: object, label: str) -> dict[str, int]:
    side_effects = _require_mapping(value, label)
    if set(side_effects) != SIDE_EFFECT_FIELD_NAMES:
        raise EvaluationScoringRejected(
            f"{label} must use the exact side-effects/v1 fields"
        )

    return {
        field_name: _require_non_negative_integer(
            side_effects[field_name],
            f"{label}.{field_name}",
        )
        for field_name in sorted(SIDE_EFFECT_FIELD_NAMES)
    }


def _check(
    code: str,
    expected: object,
    actual: object,
    *,
    passed: bool | None = None,
) -> EvaluationScoreCheck:
    return EvaluationScoreCheck(
        code=code,
        passed=expected == actual if passed is None else passed,
        expected=expected,
        actual=actual,
    )


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise EvaluationScoringRejected(f"{label} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise EvaluationScoringRejected(f"{label} must be a list")
    return cast(list[object], value)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationScoringRejected(f"{label} must be non-empty text")
    return value.strip()


def _require_distinct_text_list(
    value: object,
    label: str,
    *,
    non_empty: bool,
) -> tuple[str, ...]:
    values = tuple(
        _require_text(item, f"{label} item") for item in _require_list(value, label)
    )
    if non_empty and not values:
        raise EvaluationScoringRejected(f"{label} must contain at least one value")
    if len(set(values)) != len(values):
        raise EvaluationScoringRejected(f"{label} must not contain duplicate values")
    return values


def _require_non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationScoringRejected(f"{label} must be a non-negative integer")
    return value
