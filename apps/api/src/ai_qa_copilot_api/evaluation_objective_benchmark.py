"""Deterministically derive the objective-bearing v4 corpus from v3 development cases.

v4 (ADR-016) gives every case a request that says which area to examine, so the
model-visible inputs identify the expected answer. Each case is built from:

- the committed v3 fixture, pinned by SHA-256, of which only development-split
  cases are used (validation and holdout records are discarded unread); and
- the owner-authored objectives file, whose objective text is copied verbatim.

For an analysis case, everything is copied from its v3 source case except the
case ID, the request, the owner's repaired references (when the decision is
``repair``) and the budget. The request is the v3 base request without its
"Development scenario NN." suffix, then ``" Objective: "`` and the objective.

A negative control takes its base request from the lowest-numbered kept v3
source case of its category, its artifact records from v3, empty expected
labels and references, the ``analysis_only`` boundary, and the side-effect
vector shared by every v3 development analysis case (one model call).

Per-case budget derivation (ADR-016 rule, computed 2026-10-08 from the real v4
prompts with the committed informed builder):

- Pricing: 2.50 USD per million input tokens (the OpenAI cache-write rate, the
  highest input rate either provider may charge until a probe shows zero cache
  tokens) and 10 USD per million output tokens.
- Most expensive case: EVAL-111, 43,253 characters (developer text, user
  message and output schema) at 2.1 characters per token = 20,597 input tokens,
  plus the 4,096-token output cap.
- Worst case 0.0924525 USD, plus 10 percent = 0.10169775 USD, rounded up to the
  cent: 0.11 USD. (At the standard 2 USD input rate it would be 0.10 USD.)
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Final, cast

import yaml


OBJECTIVE_EVALUATION_CORPUS_SUITE_ID: Final = "evaluation-corpus/v4"
OBJECTIVE_CASE_MAXIMUM_EXPECTED_COST_USD: Final = 0.11
OBJECTIVE_DELIMITER: Final = " Objective: "
OBJECTIVES_SCHEMA_VERSION: Final = "evaluation-objectives/v1"
OBJECTIVES_RELATIVE_PATH: Final = Path(
    "fixtures/benchmark/evaluation-objectives.v4.yaml"
)
SOURCE_FIXTURE_RELATIVE_PATH: Final = Path(
    "fixtures/benchmark/evaluation-cases.v3.yaml"
)
SOURCE_FIXTURE_SHA256: Final = (
    "8511b573d57e24436a705cb119b4c2db47b5883bdcbb9f498d3adfc5e35b69ae"
)
NEGATIVE_CONTROL_TAG: Final = "negative_control"

_SCENARIO_SUFFIX: Final = re.compile(r" Development scenario \d{2}\.$")
_ANALYSIS_DECISIONS: Final = frozenset({"keep", "repair"})
_NEGATIVE_CONTROL_DECISION: Final = "negative_control"
_FIRST_CASE_NUMBER: Final = 101

Record = dict[str, object]


class EvaluationObjectiveBenchmarkRejected(ValueError):
    """Raised when the v4 corpus cannot be derived safely."""


def render_objective_evaluation_cases(repository_root: Path) -> str:
    """Render the v4 corpus with the v1 to v3 YAML conventions."""

    return yaml.safe_dump(
        build_objective_evaluation_cases(repository_root),
        sort_keys=False,
        allow_unicode=False,
    )


def build_objective_evaluation_cases(repository_root: Path) -> dict[str, object]:
    """Build v4 from v3 development cases and the owner's objectives file."""

    source = _load_source_fixture(repository_root)
    development = _development_cases(source)
    objectives = _load_objectives(repository_root)

    analysis_side_effects = _shared_analysis_side_effects(development)
    kept_sources = {
        _text(objective.get("source_case_id"), "source_case_id")
        for objective in objectives
        if objective.get("decision") in _ANALYSIS_DECISIONS
    }
    cases: list[Record] = []
    for index, objective in enumerate(objectives):
        case_id = _text(objective.get("id"), "objective id")
        if case_id != f"EVAL-{_FIRST_CASE_NUMBER + index}":
            raise EvaluationObjectiveBenchmarkRejected(
                f"Objective IDs must run consecutively from EVAL-{_FIRST_CASE_NUMBER}: "
                f"{case_id}"
            )
        decision = _text(objective.get("decision"), f"{case_id}.decision")
        if decision in _ANALYSIS_DECISIONS:
            cases.append(_analysis_case(case_id, decision, objective, development))
        elif decision == _NEGATIVE_CONTROL_DECISION:
            cases.append(
                _negative_control(
                    case_id,
                    objective,
                    {
                        key: development[key]
                        for key in kept_sources
                        if key in development
                    },
                    development,
                    analysis_side_effects,
                )
            )
        else:
            raise EvaluationObjectiveBenchmarkRejected(
                f"{case_id} has unsupported decision {decision}"
            )

    return {
        "schema_version": source["schema_version"],
        "suite_id": OBJECTIVE_EVALUATION_CORPUS_SUITE_ID,
        "cases": cases,
    }


def base_request(user_request: str) -> str:
    """Return the v3 request without its scenario suffix; refuse any other form."""

    if not _SCENARIO_SUFFIX.search(user_request):
        raise EvaluationObjectiveBenchmarkRejected(
            "v3 request does not end in a development scenario suffix"
        )
    return _SCENARIO_SUFFIX.sub("", user_request)


def objective_request(base: str, objective: str) -> str:
    """The v4 request: base text, the fixed delimiter, then the objective verbatim."""

    return f"{base}{OBJECTIVE_DELIMITER}{objective}"


def _analysis_case(
    case_id: str,
    decision: str,
    objective: Mapping[str, object],
    development: Mapping[str, Record],
) -> Record:
    source_id = _text(objective.get("source_case_id"), f"{case_id}.source_case_id")
    if source_id not in development:
        raise EvaluationObjectiveBenchmarkRejected(
            f"{case_id} source {source_id} is not a v3 development case"
        )
    repaired = _text_list(
        objective.get("repaired_references"), f"{case_id}.repaired_references"
    )
    if (decision == "repair") != bool(repaired):
        raise EvaluationObjectiveBenchmarkRejected(
            f"{case_id}: repaired references are required for repair and only for repair"
        )

    case = deepcopy(development[source_id])
    case["id"] = case_id
    inputs = cast(Record, case["inputs"])
    inputs["user_request"] = objective_request(
        base_request(_text(inputs.get("user_request"), f"{source_id}.user_request")),
        _objective_text(objective, case_id),
    )
    expected = cast(Record, case["expected"])
    if repaired:
        expected["expected_source_references"] = repaired
    expected["maximum_expected_cost"] = OBJECTIVE_CASE_MAXIMUM_EXPECTED_COST_USD
    return case


def _negative_control(
    case_id: str,
    objective: Mapping[str, object],
    kept_sources: Mapping[str, Record],
    development: Mapping[str, Record],
    analysis_side_effects: Record,
) -> Record:
    category = _text(objective.get("category"), f"{case_id}.category")
    # The base text of the kept group for this category: the lowest-numbered v3
    # source case that an analysis objective uses. (EVAL-001, the dropped G0
    # control, has a different request and no scenario suffix.)
    templates = [case for case in kept_sources.values() if case["category"] == category]
    if not templates:
        raise EvaluationObjectiveBenchmarkRejected(
            f"{case_id} category {category} has no kept v3 source case"
        )
    template = min(templates, key=lambda case: _text(case.get("id"), "case id"))
    if _text_list(objective.get("repaired_references"), f"{case_id}.references"):
        raise EvaluationObjectiveBenchmarkRejected(
            f"{case_id}: a negative control has no references"
        )

    artifact_records = _artifact_records(development)
    artifact_ids = _text_list(objective.get("artifacts"), f"{case_id}.artifacts")
    if not artifact_ids or any(item not in artifact_records for item in artifact_ids):
        raise EvaluationObjectiveBenchmarkRejected(
            f"{case_id} artifacts must be v3 development artifacts"
        )

    template_inputs = cast(Record, template["inputs"])
    template_expected = cast(Record, template["expected"])
    return {
        "id": case_id,
        "version": 1,
        "split": "development",
        "category": category,
        "tags": ["development", "synthetic", category, NEGATIVE_CONTROL_TAG],
        # Same rule as the v1 development builder for finding (analysis) cases.
        "criticality": "high" if category == "requirement_quality" else "medium",
        "run_mode": "analysis",
        "side_effect_schema": template["side_effect_schema"],
        "inputs": {
            "artifacts": [deepcopy(artifact_records[item]) for item in artifact_ids],
            "overlays": [],
            "user_request": objective_request(
                base_request(
                    _text(template_inputs.get("user_request"), "template request")
                ),
                _objective_text(objective, case_id),
            ),
        },
        "expected": {
            "required_ground_truth_ids": [],
            "prohibited_ground_truth_ids": [],
            "expected_source_references": [],
            "policy_boundary": "analysis_only",
            "side_effects": deepcopy(analysis_side_effects),
            "scorer_version": template_expected["scorer_version"],
            "maximum_expected_cost": OBJECTIVE_CASE_MAXIMUM_EXPECTED_COST_USD,
        },
    }


def _load_source_fixture(repository_root: Path) -> Record:
    path = repository_root / SOURCE_FIXTURE_RELATIVE_PATH
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != SOURCE_FIXTURE_SHA256:
        raise EvaluationObjectiveBenchmarkRejected(
            "v3 fixture does not match its pinned SHA-256"
        )
    return _mapping(yaml.safe_load(content.decode("utf-8")), "v3 fixture")


def _development_cases(source: Mapping[str, object]) -> dict[str, Record]:
    """Keep development cases only; other splits are discarded without inspection."""

    raw_cases = source.get("cases")
    if not isinstance(raw_cases, list):
        raise EvaluationObjectiveBenchmarkRejected("v3 fixture must contain cases")
    development: dict[str, Record] = {}
    for raw in cast(list[object], raw_cases):
        case = _mapping(raw, "v3 case")
        if case.get("split") != "development":
            continue
        development[_text(case.get("id"), "v3 case id")] = case
    if not development:
        raise EvaluationObjectiveBenchmarkRejected("v3 has no development cases")
    return development


def _load_objectives(repository_root: Path) -> list[Record]:
    path = repository_root / OBJECTIVES_RELATIVE_PATH
    document = _mapping(
        yaml.safe_load(path.read_text(encoding="utf-8")), "objectives file"
    )
    if document.get("schema_version") != OBJECTIVES_SCHEMA_VERSION:
        raise EvaluationObjectiveBenchmarkRejected("Unsupported objectives schema")
    if document.get("suite_id") != OBJECTIVE_EVALUATION_CORPUS_SUITE_ID:
        raise EvaluationObjectiveBenchmarkRejected("Objectives are not for v4")
    if document.get("source_fixture_sha256") != SOURCE_FIXTURE_SHA256:
        raise EvaluationObjectiveBenchmarkRejected(
            "Objectives were written against a different v3 fixture"
        )
    objectives = document.get("objectives")
    if not isinstance(objectives, list) or not objectives:
        raise EvaluationObjectiveBenchmarkRejected("Objectives file has no objectives")
    return [_mapping(item, "objective") for item in cast(list[object], objectives)]


def _shared_analysis_side_effects(development: Mapping[str, Record]) -> Record:
    vectors = {
        tuple(
            sorted(cast(Record, cast(Record, case["expected"])["side_effects"]).items())
        )
        for case in development.values()
        if case.get("run_mode") == "analysis"
    }
    if len(vectors) != 1:
        raise EvaluationObjectiveBenchmarkRejected(
            "v3 development analysis cases do not share one side-effect vector"
        )
    # Keep the field order v3 uses.
    first = next(
        case for case in development.values() if case.get("run_mode") == "analysis"
    )
    return deepcopy(cast(Record, cast(Record, first["expected"])["side_effects"]))


def _artifact_records(development: Mapping[str, Record]) -> dict[str, Record]:
    records: dict[str, Record] = {}
    for case in development.values():
        for artifact in cast(list[Record], cast(Record, case["inputs"])["artifacts"]):
            artifact_id = _text(artifact.get("artifact_id"), "artifact_id")
            if records.setdefault(artifact_id, artifact) != artifact:
                raise EvaluationObjectiveBenchmarkRejected(
                    f"v3 declares {artifact_id} inconsistently"
                )
    return records


def _objective_text(objective: Mapping[str, object], case_id: str) -> str:
    text = _text(objective.get("objective"), f"{case_id}.objective")
    if text != text.strip() or "\n" in text:
        raise EvaluationObjectiveBenchmarkRejected(
            f"{case_id} objective must be a single line without surrounding spaces"
        )
    return text


def _mapping(value: object, label: str) -> Record:
    if not isinstance(value, dict):
        raise EvaluationObjectiveBenchmarkRejected(f"{label} must be a mapping")
    return cast(Record, value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationObjectiveBenchmarkRejected(f"{label} must be non-empty text")
    return value


def _text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise EvaluationObjectiveBenchmarkRejected(f"{label} must be a list")
    items = [_text(item, label) for item in cast(list[object], value)]
    if len(set(items)) != len(items):
        raise EvaluationObjectiveBenchmarkRejected(f"{label} contains duplicates")
    return items
