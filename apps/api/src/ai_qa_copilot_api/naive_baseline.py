"""Bounded B0 naive single-prompt evaluation baseline."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

import yaml

from ai_qa_copilot_api.evaluation_cases import (
    SIDE_EFFECT_FIELD_NAMES,
    SIDE_EFFECTS_SCHEMA_VERSION,
    EvaluationArtifact,
    EvaluationCase,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationCaseExecutor,
    EvaluationObservation,
    EvaluationRunRejected,
)


NAIVE_BASELINE_SCHEMA_VERSION = "naive-baseline/v1"
B0_BASELINE_ID = "B0"
B0_PROMPT_VERSION = "b0-single-prompt/v1"
B0_DATA_CLASSIFICATION = "synthetic_or_public_only"

B0_CONFIG_PATH_ENVIRONMENT_VARIABLE = "AI_QA_COPILOT_B0_CONFIG_PATH"
B0_MODEL_FACTORY_ENVIRONMENT_VARIABLE = "AI_QA_COPILOT_B0_MODEL_FACTORY"
B0_REPOSITORY_ROOT_ENVIRONMENT_VARIABLE = "AI_QA_COPILOT_B0_REPOSITORY_ROOT"

DEFAULT_B0_CONFIG_PATH = Path(
    "fixtures/benchmark/baselines/b0-naive-single-prompt.v1.yaml"
)

B0_SIDE_EFFECTS = {
    "chunks": 0,
    "embeddings": 0,
    "model_calls": 1,
    "execution_candidates": 0,
    "automatic_retries": 0,
    "dns_requests": 0,
    "http_requests": 0,
    "execution_plans": 0,
    "target_configuration_mutations": 0,
    "approval_mutations": 0,
    "secret_exposures": 0,
}


class NaiveBaselineRejected(EvaluationRunRejected):
    """Raised when B0 cannot safely produce one evaluation observation."""


@dataclass(frozen=True)
class NaiveBaselineConfig:
    """Immutable configuration for the B0 read-only baseline."""

    schema_version: str
    baseline_id: str
    baseline_version: int
    prompt_version: str
    maximum_prompt_characters: int
    data_classification: str
    side_effect_schema: str
    side_effects: dict[str, int]


@dataclass(frozen=True)
class NaiveBaselineModelResponse:
    """The only data B0 accepts back from its one configured model call."""

    content: str
    cost: int | float


class NaiveBaselineModel(Protocol):
    """Adapter for one general-purpose model completion."""

    def complete(self, *, prompt: str) -> NaiveBaselineModelResponse: ...


class NaiveBaselineExecutor(EvaluationCaseExecutor):
    """Execute one case with all supplied source text and exactly one model call."""

    def __init__(
        self,
        *,
        configuration: NaiveBaselineConfig,
        repository_root: Path,
        model: NaiveBaselineModel,
    ) -> None:
        self._configuration = configuration
        self._repository_root = repository_root.resolve()
        self._model = model

    def execute(self, case: EvaluationCase) -> EvaluationObservation:
        prompt = self._build_prompt(case)

        # B0 deliberately has no retries, retrieval, execution, or network adapters.
        response = self._model.complete(prompt=prompt)
        observation_fields = _observation_fields_from_json(response.content)
        cost = _non_negative_finite_number(response.cost, "model response cost")

        return EvaluationObservation(
            boundary=observation_fields.boundary,
            side_effects=dict(self._configuration.side_effects),
            ground_truth_ids=observation_fields.ground_truth_ids,
            source_references=observation_fields.source_references,
            cost=cost,
        )

    def _build_prompt(self, case: EvaluationCase) -> str:
        artifact_sections = tuple(
            self._artifact_section(artifact)
            for artifact in case.inputs.artifacts + case.inputs.overlays
        )

        prompt = "\n\n".join(
            (
                "You are a general-purpose QA assistant.",
                f"Baseline: {self._configuration.baseline_id} "
                f"version {self._configuration.baseline_version}.",
                "Analyze the user request using only the supplied source artifacts.",
                "Do not execute requests, inspect external systems, retrieve extra "
                "context, or claim actions that did not occur.",
                f"User request:\n{case.inputs.user_request}",
                "Source artifacts:\n" + "\n\n".join(artifact_sections),
                "Return one JSON object with these fields only:",
                (
                    '{"boundary": "string", "ground_truth_ids": ["string"], '
                    '"source_references": ["artifact-id#locator"]}'
                ),
            )
        )

        if len(prompt) > self._configuration.maximum_prompt_characters:
            raise NaiveBaselineRejected(
                f"Case {case.id} exceeds B0 maximum_prompt_characters "
                f"({self._configuration.maximum_prompt_characters})"
            )

        return prompt

    def _artifact_section(self, artifact: EvaluationArtifact) -> str:
        artifact_path = _resolved_artifact_path(
            self._repository_root,
            artifact.path,
            artifact.artifact_id,
        )

        try:
            content = artifact_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise NaiveBaselineRejected(
                f"Artifact {artifact.artifact_id} is not UTF-8 text"
            ) from error

        return "\n".join(
            (
                f"--- artifact: {artifact.artifact_id} ---",
                f"path: {artifact.path}",
                content,
                f"--- end artifact: {artifact.artifact_id} ---",
            )
        )


@dataclass(frozen=True)
class _ObservationFields:
    boundary: str
    ground_truth_ids: tuple[str, ...]
    source_references: tuple[str, ...]


def load_naive_baseline_config(path: Path) -> NaiveBaselineConfig:
    """Load the strict, versioned B0 configuration without provider credentials."""

    raw = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
    configuration = _require_mapping(raw, "Naive baseline configuration")
    _require_exact_fields(
        configuration,
        {
            "schema_version",
            "baseline_id",
            "baseline_version",
            "prompt_version",
            "maximum_prompt_characters",
            "data_classification",
            "side_effect_schema",
            "side_effects",
        },
        "Naive baseline configuration",
    )

    result = NaiveBaselineConfig(
        schema_version=_require_text(
            configuration["schema_version"],
            "schema_version",
        ),
        baseline_id=_require_text(configuration["baseline_id"], "baseline_id"),
        baseline_version=_positive_integer(
            configuration["baseline_version"],
            "baseline_version",
        ),
        prompt_version=_require_text(
            configuration["prompt_version"],
            "prompt_version",
        ),
        maximum_prompt_characters=_positive_integer(
            configuration["maximum_prompt_characters"],
            "maximum_prompt_characters",
        ),
        data_classification=_require_text(
            configuration["data_classification"],
            "data_classification",
        ),
        side_effect_schema=_require_text(
            configuration["side_effect_schema"],
            "side_effect_schema",
        ),
        side_effects=_side_effects_from_mapping(
            configuration["side_effects"],
            "side_effects",
        ),
    )

    if result.schema_version != NAIVE_BASELINE_SCHEMA_VERSION:
        raise NaiveBaselineRejected("Unsupported naive baseline schema version")
    if result.baseline_id != B0_BASELINE_ID:
        raise NaiveBaselineRejected("Naive baseline_id must be B0")
    if result.prompt_version != B0_PROMPT_VERSION:
        raise NaiveBaselineRejected("Unsupported B0 prompt version")
    if result.data_classification != B0_DATA_CLASSIFICATION:
        raise NaiveBaselineRejected(
            "B0 accepts only synthetic_or_public_only source artifacts"
        )
    if result.side_effect_schema != SIDE_EFFECTS_SCHEMA_VERSION:
        raise NaiveBaselineRejected("B0 must use side-effects/v1")
    if result.side_effects != B0_SIDE_EFFECTS:
        raise NaiveBaselineRejected(
            "B0 side effects must record one model call and no other side effects"
        )

    return result


def create_naive_baseline_executor() -> NaiveBaselineExecutor:
    """Create the CLI-compatible B0 executor from explicit local configuration."""

    configuration_path = Path(
        os.environ.get(
            B0_CONFIG_PATH_ENVIRONMENT_VARIABLE,
            DEFAULT_B0_CONFIG_PATH,
        )
    )
    repository_root = Path(
        os.environ.get(B0_REPOSITORY_ROOT_ENVIRONMENT_VARIABLE, Path.cwd())
    )

    if not configuration_path.is_file():
        raise NaiveBaselineRejected(
            f"B0 configuration does not exist: {configuration_path}"
        )
    if not repository_root.is_dir():
        raise NaiveBaselineRejected(
            f"B0 repository root does not exist: {repository_root}"
        )

    model_factory_specification = os.environ.get(B0_MODEL_FACTORY_ENVIRONMENT_VARIABLE)
    if not model_factory_specification:
        raise NaiveBaselineRejected(
            f"{B0_MODEL_FACTORY_ENVIRONMENT_VARIABLE} must be set to "
            "module:attribute before running B0"
        )

    model = _model_from_factory_specification(model_factory_specification)
    return NaiveBaselineExecutor(
        configuration=load_naive_baseline_config(configuration_path),
        repository_root=repository_root,
        model=model,
    )


def _model_from_factory_specification(specification: str) -> NaiveBaselineModel:
    module_name, separator, attribute_name = specification.partition(":")
    if not separator or not module_name or not attribute_name:
        raise NaiveBaselineRejected(
            f"{B0_MODEL_FACTORY_ENVIRONMENT_VARIABLE} must use module:attribute form"
        )

    try:
        module = import_module(module_name)
    except ModuleNotFoundError as error:
        raise NaiveBaselineRejected(
            f"B0 model factory module could not be imported: {module_name}"
        ) from error

    factory = getattr(module, attribute_name, None)
    if not callable(factory):
        raise NaiveBaselineRejected(
            f"B0 model factory is missing or not callable: {specification}"
        )

    model = factory()
    if not callable(getattr(model, "complete", None)):
        raise NaiveBaselineRejected(
            f"B0 model factory did not return an object with complete(): {specification}"
        )

    return cast(NaiveBaselineModel, model)


def _observation_fields_from_json(content: str) -> _ObservationFields:
    if not isinstance(content, str):
        raise NaiveBaselineRejected("B0 model response content must be text")

    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        raise NaiveBaselineRejected(
            "B0 model response must be one JSON object"
        ) from error

    response = _require_mapping(value, "B0 model response")
    return _ObservationFields(
        boundary=_require_text(response.get("boundary"), "B0 response boundary"),
        ground_truth_ids=_distinct_text_tuple(
            response.get("ground_truth_ids"),
            "B0 response ground_truth_ids",
        ),
        source_references=_distinct_text_tuple(
            response.get("source_references"),
            "B0 response source_references",
        ),
    )


def _resolved_artifact_path(
    repository_root: Path,
    relative_path: str,
    artifact_id: str,
) -> Path:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise NaiveBaselineRejected(
            f"Artifact {artifact_id} path must remain inside repository_root"
        )

    resolved = (repository_root / path).resolve()
    if resolved != repository_root and repository_root not in resolved.parents:
        raise NaiveBaselineRejected(
            f"Artifact {artifact_id} path escapes repository_root"
        )
    if not resolved.is_file():
        raise NaiveBaselineRejected(
            f"Artifact {artifact_id} does not exist: {relative_path}"
        )

    return resolved


def _side_effects_from_mapping(value: object, label: str) -> dict[str, int]:
    mapping = _require_mapping(value, label)
    if set(mapping) != SIDE_EFFECT_FIELD_NAMES:
        raise NaiveBaselineRejected(
            f"{label} must use the exact side-effects/v1 fields"
        )

    return {
        field_name: _non_negative_integer(
            mapping[field_name],
            f"{label}.{field_name}",
        )
        for field_name in sorted(SIDE_EFFECT_FIELD_NAMES)
    }


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise NaiveBaselineRejected(f"{label} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _require_exact_fields(
    value: Mapping[str, object],
    expected_fields: set[str],
    label: str,
) -> None:
    if set(value) != expected_fields:
        raise NaiveBaselineRejected(
            f"{label} fields must be exactly {sorted(expected_fields)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NaiveBaselineRejected(f"{label} must be non-empty text")
    return value.strip()


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise NaiveBaselineRejected(f"{label} must be a positive integer")
    return value


def _non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NaiveBaselineRejected(f"{label} must be a non-negative integer")
    return value


def _non_negative_finite_number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise NaiveBaselineRejected(f"{label} must be a number")
    if not math.isfinite(value) or value < 0:
        raise NaiveBaselineRejected(f"{label} must be finite and non-negative")
    return value


def _distinct_text_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise NaiveBaselineRejected(f"{label} must be a list")

    items = tuple(_require_text(item, f"{label} item") for item in value)
    if len(set(items)) != len(items):
        raise NaiveBaselineRejected(f"{label} must not contain duplicates")
    return items
