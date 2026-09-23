"""Fail-closed B1 candidate-executor contract.

This module defines only the bounded contract and fake-adapter test seam. It
does not configure a provider, make network calls, or authorize B1 execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from threading import Lock
from typing import Final, Protocol

from ai_qa_copilot_api.evaluation_cases import (
    SIDE_EFFECT_FIELD_NAMES,
    EvaluationCase,
)
from ai_qa_copilot_api.evaluation_reviews import EvaluationReviewSubjectKind
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationCaseExecutor,
    EvaluationObservation,
    EvaluationRunRejected,
)


B1_CANDIDATE_EXECUTOR_SCHEMA_VERSION: Final = "b1-candidate-executor/v1"
CANDIDATE_OUTPUT_SCHEMA_VERSION: Final = "candidate-output/v1"
B1_CANDIDATE_EXECUTOR_FACTORY: Final = (
    "ai_qa_copilot_api.b1_candidate_executor:create_b1_candidate_executor"
)


class B1CandidateExecutorRejected(EvaluationRunRejected):
    """Raised before an unapproved or incompatible B1 candidate action occurs."""


@dataclass(frozen=True)
class B1CandidateSubject:
    """One explicit review subject produced for one evaluation case."""

    case_id: str
    subject_kind: EvaluationReviewSubjectKind
    subject_id: str


@dataclass(frozen=True)
class B1CandidateExecutorConfig:
    """Immutable, hashable configuration for the B1 executor contract.

    The current evaluation-case v1 fixtures allow no cost and no side effects.
    Consequently this contract accepts only zero-cost, zero-side-effect
    configurations until a separately approved fixture/configuration revision
    exists.
    """

    schema_version: str
    executor_id: str
    executor_version: int
    candidate_output_schema_version: str
    maximum_cost: int | float
    side_effects: tuple[tuple[str, int], ...]
    case_subjects: tuple[B1CandidateSubject, ...]

    def __post_init__(self) -> None:
        if self.schema_version != B1_CANDIDATE_EXECUTOR_SCHEMA_VERSION:
            raise B1CandidateExecutorRejected(
                "B1 candidate executor has an unsupported schema version"
            )
        if not self.executor_id.strip():
            raise B1CandidateExecutorRejected(
                "B1 candidate executor ID must be non-empty"
            )
        if (
            isinstance(self.executor_version, bool)
            or not isinstance(self.executor_version, int)
            or self.executor_version < 1
        ):
            raise B1CandidateExecutorRejected(
                "B1 candidate executor version must be a positive integer"
            )
        if self.candidate_output_schema_version != CANDIDATE_OUTPUT_SCHEMA_VERSION:
            raise B1CandidateExecutorRejected(
                "B1 candidate output has an unsupported schema version"
            )

        maximum_cost = _finite_non_negative_number(
            self.maximum_cost,
            "B1 candidate executor maximum cost",
        )
        if maximum_cost != 0:
            raise B1CandidateExecutorRejected(
                "Evaluation-case v1 permits only zero-cost B1 configurations"
            )
        object.__setattr__(self, "maximum_cost", maximum_cost)

        canonical_side_effects = _canonical_side_effects(self.side_effects)
        if any(value != 0 for _, value in canonical_side_effects):
            raise B1CandidateExecutorRejected(
                "Evaluation-case v1 permits only zero-side-effect B1 configurations"
            )
        object.__setattr__(self, "side_effects", canonical_side_effects)

        case_ids: set[str] = set()
        for subject in self.case_subjects:
            if not subject.case_id.strip() or not subject.subject_id.strip():
                raise B1CandidateExecutorRejected(
                    "B1 case and subject identifiers must be non-empty"
                )
            if subject.case_id in case_ids:
                raise B1CandidateExecutorRejected(
                    f"B1 configuration maps case {subject.case_id} more than once"
                )
            case_ids.add(subject.case_id)

        if not case_ids:
            raise B1CandidateExecutorRejected(
                "B1 configuration must define at least one case-to-subject mapping"
            )

    @property
    def side_effects_mapping(self) -> dict[str, int]:
        return dict(self.side_effects)

    @property
    def configuration_sha256(self) -> str:
        return hashlib.sha256(self.as_json().encode("utf-8")).hexdigest()

    def as_json(self) -> str:
        return json.dumps(
            {
                "candidate_output_schema_version": self.candidate_output_schema_version,
                "case_subjects": [
                    {
                        "case_id": subject.case_id,
                        "subject_id": subject.subject_id,
                        "subject_kind": subject.subject_kind.value,
                    }
                    for subject in sorted(
                        self.case_subjects,
                        key=lambda subject: subject.case_id,
                    )
                ],
                "executor_factory": B1_CANDIDATE_EXECUTOR_FACTORY,
                "executor_id": self.executor_id,
                "executor_version": self.executor_version,
                "maximum_cost": self.maximum_cost,
                "schema_version": self.schema_version,
                "side_effects": dict(self.side_effects),
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class B1CandidateExecutionResult:
    """Content-bearing adapter result kept out of the evaluation-run report."""

    observation: EvaluationObservation
    candidate_output: str


class B1CandidateExecutionAdapter(Protocol):
    """Bounded seam for a future approved B1 implementation."""

    def execute(self, case: EvaluationCase) -> B1CandidateExecutionResult: ...


@dataclass(frozen=True)
class B1CandidateOutputReceipt:
    """Content-free binding for an externally stored candidate-output file."""

    case_id: str
    subject_kind: EvaluationReviewSubjectKind
    subject_id: str
    candidate_output_sha256: str
    configuration_sha256: str
    output_path: Path


class B1CandidateExecutor(EvaluationCaseExecutor):
    """Execute only a supplied adapter under the current v1 zero-effect limits."""

    def __init__(
        self,
        *,
        configuration: B1CandidateExecutorConfig,
        adapter: B1CandidateExecutionAdapter,
        repository_root: Path,
        output_directory: Path,
    ) -> None:
        self._configuration = configuration
        self._adapter = adapter
        self._repository_root = repository_root.resolve()
        self._output_directory = output_directory.resolve()
        self._lock = Lock()
        self._receipts: dict[str, B1CandidateOutputReceipt] = {}
        self._reserved_case_ids: set[str] = set()

        if not self._repository_root.is_dir():
            raise B1CandidateExecutorRejected("Repository root must be a directory")
        if not self._output_directory.is_dir():
            raise B1CandidateExecutorRejected(
                "Candidate-output directory must already exist"
            )
        try:
            self._output_directory.relative_to(self._repository_root)
        except ValueError:
            pass
        else:
            raise B1CandidateExecutorRejected(
                "Candidate-output directory must be outside the repository root"
            )

    @property
    def receipts(self) -> tuple[B1CandidateOutputReceipt, ...]:
        with self._lock:
            return tuple(self._receipts[case_id] for case_id in sorted(self._receipts))

    def execute(self, case: EvaluationCase) -> EvaluationObservation:
        subject = self._subject_for(case)
        output_path = self._output_path(case)

        with self._lock:
            if case.id in self._receipts or case.id in self._reserved_case_ids:
                raise B1CandidateExecutorRejected(
                    f"B1 candidate output already exists for {case.id}"
                )
            if output_path.exists():
                raise B1CandidateExecutorRejected(
                    f"B1 candidate-output path already exists for {case.id}"
                )
            self._reserved_case_ids.add(case.id)

        try:
            self._validate_case_budget(case)
            result = self._adapter.execute(case)
            observation = self._validated_observation(result.observation)
            candidate_output = _utf8_candidate_output(result.candidate_output)

            try:
                with output_path.open("xb") as output_file:
                    output_file.write(candidate_output)
            except FileExistsError as error:
                raise B1CandidateExecutorRejected(
                    f"B1 candidate-output path already exists for {case.id}"
                ) from error

            receipt = B1CandidateOutputReceipt(
                case_id=case.id,
                subject_kind=subject.subject_kind,
                subject_id=subject.subject_id,
                candidate_output_sha256=hashlib.sha256(candidate_output).hexdigest(),
                configuration_sha256=self._configuration.configuration_sha256,
                output_path=output_path,
            )
            with self._lock:
                self._receipts[case.id] = receipt
            return observation
        finally:
            with self._lock:
                self._reserved_case_ids.discard(case.id)

    def _subject_for(self, case: EvaluationCase) -> B1CandidateSubject:
        for subject in self._configuration.case_subjects:
            if subject.case_id == case.id:
                return subject
        raise B1CandidateExecutorRejected(
            f"B1 configuration does not map evaluation case {case.id}"
        )

    def _output_path(self, case: EvaluationCase) -> Path:
        output_path = (
            self._output_directory / f"{case.id}.candidate-output.txt"
        ).resolve()
        try:
            output_path.relative_to(self._output_directory)
        except ValueError as error:
            raise B1CandidateExecutorRejected(
                f"B1 candidate-output path escapes its configured directory for {case.id}"
            ) from error
        return output_path

    def _validate_case_budget(self, case: EvaluationCase) -> None:
        if dict(case.expected.side_effects) != self._configuration.side_effects_mapping:
            raise B1CandidateExecutorRejected(
                f"Evaluation case {case.id} side effects differ from B1 configuration"
            )
        if case.expected.maximum_expected_cost != self._configuration.maximum_cost:
            raise B1CandidateExecutorRejected(
                f"Evaluation case {case.id} expected cost differs from B1 configuration"
            )

    def _validated_observation(
        self,
        observation: EvaluationObservation,
    ) -> EvaluationObservation:
        if not observation.boundary.strip():
            raise B1CandidateExecutorRejected(
                "B1 candidate observation boundary must be non-empty"
            )

        side_effects = _canonical_side_effects(tuple(observation.side_effects.items()))
        if dict(side_effects) != self._configuration.side_effects_mapping:
            raise B1CandidateExecutorRejected(
                "B1 candidate observation side effects differ from configuration"
            )

        cost = _finite_non_negative_number(
            observation.cost,
            "B1 candidate observation cost",
        )
        if cost != self._configuration.maximum_cost:
            raise B1CandidateExecutorRejected(
                "B1 candidate observation cost differs from configuration"
            )

        return EvaluationObservation(
            boundary=observation.boundary.strip(),
            side_effects=dict(side_effects),
            ground_truth_ids=tuple(observation.ground_truth_ids),
            source_references=tuple(observation.source_references),
            cost=cost,
        )


def create_b1_candidate_executor() -> B1CandidateExecutor:
    """Fail closed when invoked through scripts/run_evaluation.py."""

    raise B1CandidateExecutorRejected(
        "B1 candidate executor is disabled until an approved adapter, configuration, "
        "and external candidate-output location are supplied"
    )


def _canonical_side_effects(
    side_effects: tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    values = dict(side_effects)
    if len(values) != len(side_effects) or set(values) != SIDE_EFFECT_FIELD_NAMES:
        raise B1CandidateExecutorRejected(
            "B1 candidate executor must use the exact side-effects/v1 fields"
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in values.values()
    ):
        raise B1CandidateExecutorRejected(
            "B1 candidate executor side effects must be non-negative integers"
        )
    return tuple((field_name, values[field_name]) for field_name in sorted(values))


def _finite_non_negative_number(value: int | float, description: str) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
    ):
        raise B1CandidateExecutorRejected(
            f"{description} must be a finite non-negative number"
        )
    return value


def _utf8_candidate_output(candidate_output: str) -> bytes:
    if not isinstance(candidate_output, str) or not candidate_output.strip():
        raise B1CandidateExecutorRejected(
            "B1 candidate output must be non-empty UTF-8 text"
        )
    return candidate_output.encode("utf-8")
