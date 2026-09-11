from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import cast

import yaml


EVALUATION_CASES_SCHEMA_VERSION = "evaluation-cases/v1"
SIDE_EFFECTS_SCHEMA_VERSION = "side-effects/v1"

SIDE_EFFECT_FIELD_NAMES = frozenset(
    {
        "chunks",
        "embeddings",
        "model_calls",
        "execution_candidates",
        "automatic_retries",
        "dns_requests",
        "http_requests",
        "execution_plans",
        "target_configuration_mutations",
        "approval_mutations",
        "secret_exposures",
    }
)

VALID_SPLITS = frozenset({"development", "validation", "holdout"})
VALID_CRITICALITIES = frozenset({"low", "medium", "high", "critical"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EvaluationCasesRejected(ValueError):
    """Raised when an evaluation-case fixture violates its strict contract."""


@dataclass(frozen=True)
class EvaluationArtifact:
    artifact_id: str
    path: str
    sha256: str


@dataclass(frozen=True)
class EvaluationInputs:
    artifacts: tuple[EvaluationArtifact, ...]
    overlays: tuple[EvaluationArtifact, ...]
    user_request: str


@dataclass(frozen=True)
class EvaluationExpected:
    required_ground_truth_ids: tuple[str, ...]
    prohibited_ground_truth_ids: tuple[str, ...]
    expected_source_references: tuple[str, ...]
    policy_boundary: str
    side_effects: dict[str, int]
    scorer_version: str
    maximum_expected_cost: int | float


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    version: int
    split: str
    category: str
    tags: tuple[str, ...]
    criticality: str
    run_mode: str
    side_effect_schema: str
    inputs: EvaluationInputs
    expected: EvaluationExpected


@dataclass(frozen=True)
class EvaluationCaseSuite:
    schema_version: str
    suite_id: str
    cases: tuple[EvaluationCase, ...]


def load_evaluation_case_suite(path: Path) -> EvaluationCaseSuite:
    """Load one strict, versioned evaluation-case suite from YAML."""

    raw = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
    suite = _require_mapping(raw, "Evaluation-case suite")
    _require_exact_fields(
        suite,
        {"schema_version", "suite_id", "cases"},
        "Evaluation-case suite",
    )

    schema_version = _require_text(suite["schema_version"], "schema_version")
    if schema_version != EVALUATION_CASES_SCHEMA_VERSION:
        raise EvaluationCasesRejected("Unsupported evaluation-case schema version")

    suite_id = _require_text(suite["suite_id"], "suite_id")
    records = _require_list(suite["cases"], "cases")
    if not records:
        raise EvaluationCasesRejected(
            "Evaluation-case suite must declare at least one case"
        )

    cases = tuple(
        _case_from_mapping(record, index) for index, record in enumerate(records)
    )
    case_ids = tuple(case.id for case in cases)
    if len(set(case_ids)) != len(case_ids):
        raise EvaluationCasesRejected(
            "Evaluation-case suite contains duplicate case IDs"
        )

    return EvaluationCaseSuite(
        schema_version=schema_version,
        suite_id=suite_id,
        cases=cases,
    )


def filter_evaluation_cases(
    cases: Iterable[EvaluationCase],
    *,
    case_ids: Collection[str] | None = None,
    splits: Collection[str] | None = None,
    categories: Collection[str] | None = None,
    tags: Collection[str] | None = None,
    criticalities: Collection[str] | None = None,
) -> tuple[EvaluationCase, ...]:
    """Return fixture-order cases matching every supplied filter."""

    selected_case_ids = _normalise_filter(case_ids, "case_ids")
    selected_splits = _normalise_filter(splits, "splits")
    selected_categories = _normalise_filter(categories, "categories")
    selected_tags = _normalise_filter(tags, "tags")
    selected_criticalities = _normalise_filter(criticalities, "criticalities")

    selected: list[EvaluationCase] = []
    for case in cases:
        if selected_case_ids is not None and case.id not in selected_case_ids:
            continue
        if selected_splits is not None and case.split not in selected_splits:
            continue
        if selected_categories is not None and case.category not in selected_categories:
            continue
        if selected_tags is not None and not selected_tags.issubset(case.tags):
            continue
        if (
            selected_criticalities is not None
            and case.criticality not in selected_criticalities
        ):
            continue
        selected.append(case)

    return tuple(selected)


def _case_from_mapping(value: object, index: int) -> EvaluationCase:
    label = f"cases[{index}]"
    record = _require_mapping(value, label)
    _require_exact_fields(
        record,
        {
            "id",
            "version",
            "split",
            "category",
            "tags",
            "criticality",
            "run_mode",
            "side_effect_schema",
            "inputs",
            "expected",
        },
        label,
    )

    case_id = _require_text(record["id"], f"{label}.id")
    version = _require_positive_integer(record["version"], f"{label}.version")
    split = _require_text(record["split"], f"{label}.split")
    if split not in VALID_SPLITS:
        raise EvaluationCasesRejected(f"{label}.split is unsupported: {split}")

    criticality = _require_text(record["criticality"], f"{label}.criticality")
    if criticality not in VALID_CRITICALITIES:
        raise EvaluationCasesRejected(
            f"{label}.criticality is unsupported: {criticality}"
        )

    side_effect_schema = _require_text(
        record["side_effect_schema"],
        f"{label}.side_effect_schema",
    )
    if side_effect_schema != SIDE_EFFECTS_SCHEMA_VERSION:
        raise EvaluationCasesRejected(f"{label} must use side-effects/v1")

    return EvaluationCase(
        id=case_id,
        version=version,
        split=split,
        category=_require_text(record["category"], f"{label}.category"),
        tags=_require_distinct_text_list(
            record["tags"], f"{label}.tags", non_empty=True
        ),
        criticality=criticality,
        run_mode=_require_text(record["run_mode"], f"{label}.run_mode"),
        side_effect_schema=side_effect_schema,
        inputs=_inputs_from_mapping(record["inputs"], label),
        expected=_expected_from_mapping(record["expected"], label),
    )


def _inputs_from_mapping(value: object, case_label: str) -> EvaluationInputs:
    label = f"{case_label}.inputs"
    inputs = _require_mapping(value, label)
    _require_exact_fields(inputs, {"artifacts", "overlays", "user_request"}, label)

    artifacts = _artifacts_from_list(
        inputs["artifacts"], f"{label}.artifacts", non_empty=True
    )
    overlays = _artifacts_from_list(
        inputs["overlays"], f"{label}.overlays", non_empty=False
    )

    artifact_ids = tuple(artifact.artifact_id for artifact in artifacts + overlays)
    if len(set(artifact_ids)) != len(artifact_ids):
        raise EvaluationCasesRejected(f"{label} contains duplicate artifact IDs")

    return EvaluationInputs(
        artifacts=artifacts,
        overlays=overlays,
        user_request=_require_text(inputs["user_request"], f"{label}.user_request"),
    )


def _artifacts_from_list(
    value: object,
    label: str,
    *,
    non_empty: bool,
) -> tuple[EvaluationArtifact, ...]:
    records = _require_list(value, label)
    if non_empty and not records:
        raise EvaluationCasesRejected(f"{label} must contain at least one artifact")

    artifacts: list[EvaluationArtifact] = []
    for index, item in enumerate(records):
        item_label = f"{label}[{index}]"
        artifact = _require_mapping(item, item_label)
        _require_exact_fields(artifact, {"artifact_id", "path", "sha256"}, item_label)

        sha256 = _require_text(artifact["sha256"], f"{item_label}.sha256")
        if not _SHA256_PATTERN.fullmatch(sha256):
            raise EvaluationCasesRejected(
                f"{item_label}.sha256 must be 64 lowercase hexadecimal characters"
            )

        artifacts.append(
            EvaluationArtifact(
                artifact_id=_require_text(
                    artifact["artifact_id"],
                    f"{item_label}.artifact_id",
                ),
                path=_require_text(artifact["path"], f"{item_label}.path"),
                sha256=sha256,
            )
        )

    return tuple(artifacts)


def _expected_from_mapping(value: object, case_label: str) -> EvaluationExpected:
    label = f"{case_label}.expected"
    expected = _require_mapping(value, label)
    _require_exact_fields(
        expected,
        {
            "required_ground_truth_ids",
            "prohibited_ground_truth_ids",
            "expected_source_references",
            "policy_boundary",
            "side_effects",
            "scorer_version",
            "maximum_expected_cost",
        },
        label,
    )

    required_ground_truth_ids = _require_distinct_text_list(
        expected["required_ground_truth_ids"],
        f"{label}.required_ground_truth_ids",
        non_empty=False,
    )
    prohibited_ground_truth_ids = _require_distinct_text_list(
        expected["prohibited_ground_truth_ids"],
        f"{label}.prohibited_ground_truth_ids",
        non_empty=False,
    )
    if set(required_ground_truth_ids) & set(prohibited_ground_truth_ids):
        raise EvaluationCasesRejected(
            f"{label} cannot require and prohibit the same ground-truth ID"
        )

    return EvaluationExpected(
        required_ground_truth_ids=required_ground_truth_ids,
        prohibited_ground_truth_ids=prohibited_ground_truth_ids,
        expected_source_references=_require_distinct_text_list(
            expected["expected_source_references"],
            f"{label}.expected_source_references",
            non_empty=False,
        ),
        policy_boundary=_require_text(
            expected["policy_boundary"],
            f"{label}.policy_boundary",
        ),
        side_effects=_side_effects_from_mapping(
            expected["side_effects"],
            f"{label}.side_effects",
        ),
        scorer_version=_require_text(
            expected["scorer_version"],
            f"{label}.scorer_version",
        ),
        maximum_expected_cost=_require_non_negative_number(
            expected["maximum_expected_cost"],
            f"{label}.maximum_expected_cost",
        ),
    )


def _side_effects_from_mapping(value: object, label: str) -> dict[str, int]:
    effects = _require_mapping(value, label)
    _require_exact_fields(effects, SIDE_EFFECT_FIELD_NAMES, label)

    return {
        field_name: _require_non_negative_integer(
            effects[field_name],
            f"{label}.{field_name}",
        )
        for field_name in sorted(SIDE_EFFECT_FIELD_NAMES)
    }


def _normalise_filter(
    values: Collection[str] | None,
    label: str,
) -> frozenset[str] | None:
    if values is None:
        return None

    normalised = frozenset(
        _require_text(value, f"{label} filter value") for value in values
    )
    if not normalised:
        raise EvaluationCasesRejected(f"{label} filter cannot be empty")

    return normalised


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise EvaluationCasesRejected(f"{label} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise EvaluationCasesRejected(f"{label} must be a list")
    return cast(list[object], value)


def _require_exact_fields(
    value: Mapping[str, object],
    expected_fields: Collection[str],
    label: str,
) -> None:
    actual_fields = set(value)
    required_fields = set(expected_fields)

    missing_fields = sorted(required_fields - actual_fields)
    unexpected_fields = sorted(actual_fields - required_fields)
    if missing_fields or unexpected_fields:
        raise EvaluationCasesRejected(
            f"{label} fields are invalid; "
            f"missing={missing_fields}, unexpected={unexpected_fields}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationCasesRejected(f"{label} must be non-empty text")
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
        raise EvaluationCasesRejected(f"{label} must contain at least one value")
    if len(set(values)) != len(values):
        raise EvaluationCasesRejected(f"{label} must not contain duplicate values")
    return values


def _require_positive_integer(value: object, label: str) -> int:
    integer = _require_non_negative_integer(value, label)
    if integer == 0:
        raise EvaluationCasesRejected(f"{label} must be greater than zero")
    return integer


def _require_non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationCasesRejected(f"{label} must be a non-negative integer")
    return value


def _require_non_negative_number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EvaluationCasesRejected(f"{label} must be a non-negative number")
    if not math.isfinite(value) or value < 0:
        raise EvaluationCasesRejected(f"{label} must be a finite non-negative number")
    return value
