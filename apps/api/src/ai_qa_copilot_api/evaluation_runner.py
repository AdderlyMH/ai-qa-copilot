"""Deterministic, bounded execution of versioned evaluation cases."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Protocol, cast

from ai_qa_copilot_api.evaluation_cases import (
    SIDE_EFFECT_FIELD_NAMES,
    EvaluationCase,
    EvaluationCaseSuite,
    filter_evaluation_cases,
)


EVALUATION_RUN_SCHEMA_VERSION = "evaluation-run/v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EvaluationRunRejected(ValueError):
    """Raised before an invalid or over-budget evaluation run can execute."""


@dataclass(frozen=True)
class EvaluationObservation:
    """One executor observation; scoring is added in EVAL-002."""

    boundary: str
    side_effects: Mapping[str, int]
    ground_truth_ids: tuple[str, ...]
    source_references: tuple[str, ...]
    cost: int | float


class EvaluationCaseExecutor(Protocol):
    """Adapter that executes one selected case without choosing the case itself."""

    def execute(self, case: EvaluationCase) -> EvaluationObservation: ...


@dataclass(frozen=True)
class EvaluationRunCaseResult:
    case_id: str
    case_version: int
    case_sha256: str
    observation: EvaluationObservation
    reused: bool


@dataclass(frozen=True)
class EvaluationRun:
    schema_version: str
    suite_id: str
    fixture_sha256: str
    selected_case_ids: tuple[str, ...]
    max_expected_cost: int | float | None
    max_concurrency: int
    results: tuple[EvaluationRunCaseResult, ...]

    def as_json(self) -> str:
        return (
            json.dumps(
                asdict(self),
                indent=2,
                sort_keys=True,
                separators=(",", ": "),
            )
            + "\n"
        )


def run_evaluation_cases(
    suite: EvaluationCaseSuite,
    *,
    fixture_path: Path,
    repository_root: Path,
    executor: EvaluationCaseExecutor,
    case_ids: Collection[str] | None = None,
    splits: Collection[str] | None = None,
    categories: Collection[str] | None = None,
    tags: Collection[str] | None = None,
    criticalities: Collection[str] | None = None,
    max_expected_cost: int | float | None = None,
    max_concurrency: int = 1,
    resume_from: EvaluationRun | None = None,
) -> EvaluationRun:
    """Validate, select, and execute cases within deterministic resource limits."""

    _validate_run_limits(
        max_expected_cost=max_expected_cost,
        max_concurrency=max_concurrency,
    )

    fixture_sha256 = _sha256_file(fixture_path)
    selected_cases = filter_evaluation_cases(
        suite.cases,
        case_ids=case_ids,
        splits=splits,
        categories=categories,
        tags=tags,
        criticalities=criticalities,
    )
    if not selected_cases:
        raise EvaluationRunRejected("Evaluation selection did not match any cases")

    for case in selected_cases:
        _verify_case_artifacts(case, repository_root)

    resumed_results = _resumed_results(
        resume_from=resume_from,
        suite=suite,
        fixture_sha256=fixture_sha256,
        selected_cases=selected_cases,
    )

    pending_cases = tuple(
        case for case in selected_cases if case.id not in resumed_results
    )
    expected_cost = sum(case.expected.maximum_expected_cost for case in pending_cases)
    if max_expected_cost is not None and expected_cost > max_expected_cost:
        raise EvaluationRunRejected(
            "Selected evaluation cases exceed the configured expected-cost budget"
        )

    completed_results = _execute_pending_cases(
        pending_cases,
        executor=executor,
        max_concurrency=max_concurrency,
    )

    result_by_case_id = {result.case_id: result for result in completed_results}
    result_by_case_id.update(resumed_results)

    return EvaluationRun(
        schema_version=EVALUATION_RUN_SCHEMA_VERSION,
        suite_id=suite.suite_id,
        fixture_sha256=fixture_sha256,
        selected_case_ids=tuple(case.id for case in selected_cases),
        max_expected_cost=max_expected_cost,
        max_concurrency=max_concurrency,
        results=tuple(result_by_case_id[case.id] for case in selected_cases),
    )


def _execute_pending_cases(
    cases: tuple[EvaluationCase, ...],
    *,
    executor: EvaluationCaseExecutor,
    max_concurrency: int,
) -> tuple[EvaluationRunCaseResult, ...]:
    if not cases:
        return ()

    results: list[EvaluationRunCaseResult] = []
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        submitted = {pool.submit(executor.execute, case): case for case in cases}
        for future in as_completed(submitted):
            case = submitted[future]
            results.append(
                _result_from_observation(
                    case,
                    future.result(),
                    reused=False,
                )
            )

    return tuple(results)


def _resumed_results(
    *,
    resume_from: EvaluationRun | None,
    suite: EvaluationCaseSuite,
    fixture_sha256: str,
    selected_cases: tuple[EvaluationCase, ...],
) -> dict[str, EvaluationRunCaseResult]:
    if resume_from is None:
        return {}

    if resume_from.schema_version != EVALUATION_RUN_SCHEMA_VERSION:
        raise EvaluationRunRejected("Resume report has an unsupported schema version")
    if resume_from.suite_id != suite.suite_id:
        raise EvaluationRunRejected("Resume report belongs to another evaluation suite")
    if resume_from.fixture_sha256 != fixture_sha256:
        raise EvaluationRunRejected("Resume report fixture provenance does not match")

    selected_case_by_id = {case.id: case for case in selected_cases}
    resumed: dict[str, EvaluationRunCaseResult] = {}

    for result in resume_from.results:
        case = selected_case_by_id.get(result.case_id)
        if case is None:
            continue
        if result.case_version != case.version:
            raise EvaluationRunRejected(
                f"Resume report case version differs for {case.id}"
            )
        if result.case_sha256 != _case_sha256(case):
            raise EvaluationRunRejected(
                f"Resume report case provenance differs for {case.id}"
            )
        if result.case_id in resumed:
            raise EvaluationRunRejected(
                f"Resume report contains duplicate result for {case.id}"
            )
        resumed[result.case_id] = EvaluationRunCaseResult(
            case_id=result.case_id,
            case_version=result.case_version,
            case_sha256=result.case_sha256,
            observation=_validated_observation(result.observation),
            reused=True,
        )

    return resumed


def _result_from_observation(
    case: EvaluationCase,
    observation: EvaluationObservation,
    *,
    reused: bool,
) -> EvaluationRunCaseResult:
    return EvaluationRunCaseResult(
        case_id=case.id,
        case_version=case.version,
        case_sha256=_case_sha256(case),
        observation=_validated_observation(observation),
        reused=reused,
    )


def _validated_observation(
    observation: EvaluationObservation,
) -> EvaluationObservation:
    if not observation.boundary.strip():
        raise EvaluationRunRejected("Evaluation observation boundary must be non-empty")

    side_effects = dict(observation.side_effects)
    if set(side_effects) != SIDE_EFFECT_FIELD_NAMES:
        raise EvaluationRunRejected(
            "Evaluation observation must use the exact side-effects/v1 fields"
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in side_effects.values()
    ):
        raise EvaluationRunRejected(
            "Evaluation observation side effects must be non-negative integers"
        )

    if (
        isinstance(observation.cost, bool)
        or not isinstance(observation.cost, int | float)
        or not math.isfinite(observation.cost)
        or observation.cost < 0
    ):
        raise EvaluationRunRejected(
            "Evaluation observation cost must be a finite non-negative number"
        )

    return EvaluationObservation(
        boundary=observation.boundary.strip(),
        side_effects={
            field_name: side_effects[field_name]
            for field_name in sorted(SIDE_EFFECT_FIELD_NAMES)
        },
        ground_truth_ids=_distinct_texts(
            observation.ground_truth_ids,
            "Evaluation observation ground-truth IDs",
        ),
        source_references=_distinct_texts(
            observation.source_references,
            "Evaluation observation source references",
        ),
        cost=observation.cost,
    )


def _verify_case_artifacts(case: EvaluationCase, repository_root: Path) -> None:
    root = repository_root.resolve()

    for artifact in case.inputs.artifacts + case.inputs.overlays:
        artifact_path = (root / artifact.path).resolve()
        try:
            artifact_path.relative_to(root)
        except ValueError as error:
            raise EvaluationRunRejected(
                f"Artifact path escapes the repository root: {artifact.path}"
            ) from error

        if not artifact_path.is_file():
            raise EvaluationRunRejected(
                f"Evaluation artifact does not exist: {artifact.path}"
            )
        if _sha256_file(artifact_path) != artifact.sha256:
            raise EvaluationRunRejected(
                f"Evaluation artifact hash differs: {artifact.artifact_id}"
            )


def _validate_run_limits(
    *,
    max_expected_cost: int | float | None,
    max_concurrency: int,
) -> None:
    if (
        isinstance(max_concurrency, bool)
        or not isinstance(max_concurrency, int)
        or max_concurrency < 1
    ):
        raise EvaluationRunRejected("max_concurrency must be at least one")

    if max_expected_cost is None:
        return
    if (
        isinstance(max_expected_cost, bool)
        or not isinstance(max_expected_cost, int | float)
        or not math.isfinite(max_expected_cost)
        or max_expected_cost < 0
    ):
        raise EvaluationRunRejected(
            "max_expected_cost must be a finite non-negative number"
        )


def _case_sha256(case: EvaluationCase) -> str:
    canonical_case = json.dumps(
        asdict(case),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical_case).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _distinct_texts(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalised = tuple(value.strip() for value in values)
    if any(not value for value in normalised):
        raise EvaluationRunRejected(f"{label} must contain non-empty text")
    if len(set(normalised)) != len(normalised):
        raise EvaluationRunRejected(f"{label} must not contain duplicate values")
    return normalised


def evaluation_run_from_json(serialized: str) -> EvaluationRun:
    """Load a strict machine-readable EVAL-001 run report."""

    try:
        raw = cast(object, json.loads(serialized))
    except json.JSONDecodeError as error:
        raise EvaluationRunRejected(
            "Evaluation run report is not valid JSON"
        ) from error

    report = _require_mapping(raw, "Evaluation run report")
    _require_exact_fields(
        report,
        {
            "schema_version",
            "suite_id",
            "fixture_sha256",
            "selected_case_ids",
            "max_expected_cost",
            "max_concurrency",
            "results",
        },
        "Evaluation run report",
    )

    schema_version = _require_text(report["schema_version"], "schema_version")
    if schema_version != EVALUATION_RUN_SCHEMA_VERSION:
        raise EvaluationRunRejected("Resume report has an unsupported schema version")

    fixture_sha256 = _require_sha256(
        report["fixture_sha256"],
        "fixture_sha256",
    )
    max_concurrency = _require_positive_integer(
        report["max_concurrency"],
        "max_concurrency",
    )
    max_expected_cost = _optional_non_negative_number(
        report["max_expected_cost"],
        "max_expected_cost",
    )

    selected_case_ids = _require_distinct_text_list(
        report["selected_case_ids"],
        "selected_case_ids",
    )
    result_records = _require_list(report["results"], "results")
    results = tuple(
        _result_from_mapping(record, index)
        for index, record in enumerate(result_records)
    )

    result_ids = tuple(result.case_id for result in results)
    if len(set(result_ids)) != len(result_ids):
        raise EvaluationRunRejected("Resume report contains duplicate case results")

    return EvaluationRun(
        schema_version=schema_version,
        suite_id=_require_text(report["suite_id"], "suite_id"),
        fixture_sha256=fixture_sha256,
        selected_case_ids=selected_case_ids,
        max_expected_cost=max_expected_cost,
        max_concurrency=max_concurrency,
        results=results,
    )


def _result_from_mapping(
    value: object,
    index: int,
) -> EvaluationRunCaseResult:
    label = f"results[{index}]"
    result = _require_mapping(value, label)
    _require_exact_fields(
        result,
        {
            "case_id",
            "case_version",
            "case_sha256",
            "observation",
            "reused",
        },
        label,
    )

    reused = result["reused"]
    if not isinstance(reused, bool):
        raise EvaluationRunRejected(f"{label}.reused must be a boolean")

    return EvaluationRunCaseResult(
        case_id=_require_text(result["case_id"], f"{label}.case_id"),
        case_version=_require_positive_integer(
            result["case_version"],
            f"{label}.case_version",
        ),
        case_sha256=_require_sha256(
            result["case_sha256"],
            f"{label}.case_sha256",
        ),
        observation=_observation_from_mapping(
            result["observation"],
            f"{label}.observation",
        ),
        reused=reused,
    )


def _observation_from_mapping(
    value: object,
    label: str,
) -> EvaluationObservation:
    observation = _require_mapping(value, label)
    _require_exact_fields(
        observation,
        {
            "boundary",
            "side_effects",
            "ground_truth_ids",
            "source_references",
            "cost",
        },
        label,
    )

    side_effects = _require_mapping(
        observation["side_effects"],
        f"{label}.side_effects",
    )
    if set(side_effects) != SIDE_EFFECT_FIELD_NAMES:
        raise EvaluationRunRejected(
            f"{label}.side_effects must use the exact side-effects/v1 fields"
        )

    return _validated_observation(
        EvaluationObservation(
            boundary=_require_text(observation["boundary"], f"{label}.boundary"),
            side_effects={
                field_name: _require_non_negative_integer(
                    side_effects[field_name],
                    f"{label}.side_effects.{field_name}",
                )
                for field_name in sorted(SIDE_EFFECT_FIELD_NAMES)
            },
            ground_truth_ids=_require_distinct_text_list(
                observation["ground_truth_ids"],
                f"{label}.ground_truth_ids",
            ),
            source_references=_require_distinct_text_list(
                observation["source_references"],
                f"{label}.source_references",
            ),
            cost=_require_non_negative_number(
                observation["cost"],
                f"{label}.cost",
            ),
        )
    )


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise EvaluationRunRejected(f"{label} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise EvaluationRunRejected(f"{label} must be a list")
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
        raise EvaluationRunRejected(
            f"{label} fields are invalid; "
            f"missing={missing_fields}, unexpected={unexpected_fields}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationRunRejected(f"{label} must be non-empty text")
    return value.strip()


def _require_distinct_text_list(value: object, label: str) -> tuple[str, ...]:
    values = tuple(
        _require_text(item, f"{label} item") for item in _require_list(value, label)
    )
    if len(set(values)) != len(values):
        raise EvaluationRunRejected(f"{label} must not contain duplicate values")
    return values


def _require_positive_integer(value: object, label: str) -> int:
    integer = _require_non_negative_integer(value, label)
    if integer == 0:
        raise EvaluationRunRejected(f"{label} must be greater than zero")
    return integer


def _require_non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationRunRejected(f"{label} must be a non-negative integer")
    return value


def _require_non_negative_number(value: object, label: str) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
    ):
        raise EvaluationRunRejected(f"{label} must be a finite non-negative number")
    return value


def _optional_non_negative_number(
    value: object,
    label: str,
) -> int | float | None:
    if value is None:
        return None
    return _require_non_negative_number(value, label)


def _require_sha256(value: object, label: str) -> str:
    sha256 = _require_text(value, label)
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise EvaluationRunRejected(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return sha256
