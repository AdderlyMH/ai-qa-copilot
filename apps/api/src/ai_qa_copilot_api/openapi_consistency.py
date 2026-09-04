"""Deterministic requirement/OpenAPI consistency analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Final
from uuid import UUID, uuid5

from ai_qa_copilot_api.citations import Citation
from ai_qa_copilot_api.findings import (
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    MAX_FINDING_TEXT_LENGTH,
    RequirementFindingV1,
    validate_requirement_finding,
)
from ai_qa_copilot_api.openapi_facts import (
    OPENAPI_FACT_SCHEMA_VERSION,
    OpenApiFact,
    OpenApiFactKind,
    OpenApiFactsV1,
)


OPENAPI_CONSISTENCY_ANALYZER_VERSION: Final = "openapi-consistency-rules/v1"


class OpenApiConsistencyKind(StrEnum):
    """Closed set of ANA-004 consistency comparisons."""

    FIELD = "field"
    RESPONSE = "response"
    ENUM = "enum"
    SECURITY = "security"
    OPERATION = "operation"
    LIMIT = "limit"


_EXPECTED_FACT_KINDS: Final = {
    OpenApiConsistencyKind.FIELD: OpenApiFactKind.SCHEMA,
    OpenApiConsistencyKind.RESPONSE: OpenApiFactKind.RESPONSE,
    OpenApiConsistencyKind.ENUM: OpenApiFactKind.ENUM,
    OpenApiConsistencyKind.SECURITY: OpenApiFactKind.SECURITY,
    OpenApiConsistencyKind.OPERATION: OpenApiFactKind.OPERATION,
    OpenApiConsistencyKind.LIMIT: OpenApiFactKind.LIMIT,
}


@dataclass(frozen=True)
class OpenApiConsistencyExpectation:
    """One cited requirement expectation compared with one OpenAPI fact."""

    citation: Citation
    kind: OpenApiConsistencyKind
    fact_identifier: str
    expected_attributes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class OpenApiConsistencyMismatch:
    """A typed cited finding plus its deterministic fact comparison."""

    kind: OpenApiConsistencyKind
    fact_identifier: str
    expected_attributes: tuple[tuple[str, str], ...]
    actual_attributes: tuple[tuple[str, str], ...] | None
    finding: RequirementFindingV1


@dataclass(frozen=True)
class SeededConsistencyBaseline:
    """Measurable result for the versioned ANA-004 defect fixture."""

    total_seeded_defects: int
    detected_defects: int
    recall: float
    false_positives: int


def expected_fact_kind(kind: OpenApiConsistencyKind) -> OpenApiFactKind:
    """Return the ANA-002 fact kind required by one comparison kind."""

    return _EXPECTED_FACT_KINDS[kind]


OPENAPI_CONSISTENCY_FINDING_NAMESPACE: Final = UUID(
    "4b4a0ff0-2b7c-4a10-9d1b-c1d8c8e7ad93"
)
_MAX_FACT_IDENTIFIER_LENGTH: Final = 1_000


class OpenApiConsistencyRejected(ValueError):
    """Raised when consistency inputs cannot be compared deterministically."""


def analyze_openapi_consistency(
    *,
    expectations: Sequence[OpenApiConsistencyExpectation],
    facts: OpenApiFactsV1,
) -> tuple[OpenApiConsistencyMismatch, ...]:
    """Compare cited requirement expectations with ANA-002 OpenAPI facts."""

    if facts.schema_version != OPENAPI_FACT_SCHEMA_VERSION:
        raise OpenApiConsistencyRejected("Unsupported OpenAPI facts schema version")

    _validate_expectations(expectations)
    fact_index = _index_facts(facts.facts)
    mismatches: list[OpenApiConsistencyMismatch] = []

    for expectation in sorted(expectations, key=_expectation_sort_key):
        fact = fact_index.get(
            (expected_fact_kind(expectation.kind), expectation.fact_identifier)
        )
        if _matches_expectation(expectation, fact):
            continue

        actual_attributes = fact.attributes if fact is not None else None
        mismatches.append(
            OpenApiConsistencyMismatch(
                kind=expectation.kind,
                fact_identifier=expectation.fact_identifier,
                expected_attributes=expectation.expected_attributes,
                actual_attributes=actual_attributes,
                finding=_finding_for_mismatch(expectation, actual_attributes),
            )
        )

    return tuple(mismatches)


def measure_seeded_consistency_baseline(
    *,
    seeded_defects: Sequence[OpenApiConsistencyExpectation],
    mismatches: Sequence[OpenApiConsistencyMismatch],
) -> SeededConsistencyBaseline:
    """Measure seeded-defect recall and false positives for ANA-004 tests."""

    if not seeded_defects:
        raise OpenApiConsistencyRejected("At least one seeded defect is required")

    expected_keys = {_expectation_key(expectation) for expectation in seeded_defects}
    detected_keys = {_mismatch_key(mismatch) for mismatch in mismatches}
    detected_defects = len(expected_keys & detected_keys)

    return SeededConsistencyBaseline(
        total_seeded_defects=len(expected_keys),
        detected_defects=detected_defects,
        recall=detected_defects / len(expected_keys),
        false_positives=len(detected_keys - expected_keys),
    )


def _validate_expectations(
    expectations: Sequence[OpenApiConsistencyExpectation],
) -> None:
    keys: set[tuple[str, str, str, tuple[tuple[str, str], ...]]] = set()

    for expectation in expectations:
        if (
            not expectation.fact_identifier.strip()
            or len(expectation.fact_identifier) > _MAX_FACT_IDENTIFIER_LENGTH
        ):
            raise OpenApiConsistencyRejected(
                "Fact identifiers must be bounded, non-empty text"
            )
        if (
            expectation.kind is not OpenApiConsistencyKind.OPERATION
            and not expectation.expected_attributes
        ):
            raise OpenApiConsistencyRejected(
                "Non-operation expectations require at least one attribute"
            )
        if (
            tuple(sorted(expectation.expected_attributes))
            != expectation.expected_attributes
        ):
            raise OpenApiConsistencyRejected(
                "Expected attributes must be sorted deterministically"
            )
        if len({name for name, _ in expectation.expected_attributes}) != len(
            expectation.expected_attributes
        ):
            raise OpenApiConsistencyRejected("Expected attribute names must not repeat")
        for _, value in expectation.expected_attributes:
            _require_canonical_json(value)

        key = _expectation_key(expectation)
        if key in keys:
            raise OpenApiConsistencyRejected(
                "Cited consistency expectations must not repeat"
            )
        keys.add(key)


def _index_facts(
    facts: Sequence[OpenApiFact],
) -> dict[tuple[OpenApiFactKind, str], OpenApiFact]:
    index = {(fact.kind, fact.identifier): fact for fact in facts}
    if len(index) != len(facts):
        raise OpenApiConsistencyRejected(
            "OpenAPI facts must have unique kind and identifier pairs"
        )
    return index


def _matches_expectation(
    expectation: OpenApiConsistencyExpectation,
    fact: OpenApiFact | None,
) -> bool:
    if fact is None:
        return False

    actual_attributes = dict(fact.attributes)
    return all(
        actual_attributes.get(name) == value
        for name, value in expectation.expected_attributes
    )


def _finding_for_mismatch(
    expectation: OpenApiConsistencyExpectation,
    actual_attributes: tuple[tuple[str, str], ...] | None,
) -> RequirementFindingV1:
    """Create one validated, cited strict finding from a fact mismatch."""

    actual_description = (
        _attributes_description(actual_attributes)
        if actual_attributes is not None
        else "the OpenAPI fact is missing"
    )
    finding = RequirementFindingV1(
        id=uuid5(
            OPENAPI_CONSISTENCY_FINDING_NAMESPACE,
            _finding_identity(expectation, actual_attributes),
        ),
        category=FindingCategory.REQUIREMENTS_CONTRACT_MISMATCH,
        severity=(
            FindingSeverity.HIGH
            if expectation.kind is OpenApiConsistencyKind.SECURITY
            else FindingSeverity.MEDIUM
        ),
        evidence=(
            FindingEvidence(
                citation_id=expectation.citation.id,
                observed_fact=_bounded_evidence_text(expectation.citation.passage),
            ),
        ),
        analysis=(
            f"{expectation.kind.value} mismatch for "
            f"'{expectation.fact_identifier}': expected "
            f"{_attributes_description(expectation.expected_attributes)}; "
            f"observed {actual_description}."
        ),
        confidence=1.0,
        recommendation=(
            f"Align the requirement and OpenAPI contract for "
            f"'{expectation.fact_identifier}'."
        ),
        unsupported=False,
        unsupported_reason=None,
    )
    return validate_requirement_finding(finding.as_payload())


def _expectation_sort_key(
    expectation: OpenApiConsistencyExpectation,
) -> tuple[str, str, str]:
    return (
        expectation.kind.value,
        expectation.fact_identifier,
        str(expectation.citation.id),
    )


def _expectation_key(
    expectation: OpenApiConsistencyExpectation,
) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    return (
        str(expectation.citation.id),
        expectation.kind.value,
        expectation.fact_identifier,
        expectation.expected_attributes,
    )


def _mismatch_key(
    mismatch: OpenApiConsistencyMismatch,
) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    return (
        str(mismatch.finding.evidence[0].citation_id),
        mismatch.kind.value,
        mismatch.fact_identifier,
        mismatch.expected_attributes,
    )


def _finding_identity(
    expectation: OpenApiConsistencyExpectation,
    actual_attributes: tuple[tuple[str, str], ...] | None,
) -> str:
    return json.dumps(
        {
            "analyzer_version": OPENAPI_CONSISTENCY_ANALYZER_VERSION,
            "citation_id": str(expectation.citation.id),
            "kind": expectation.kind.value,
            "fact_identifier": expectation.fact_identifier,
            "expected_attributes": expectation.expected_attributes,
            "actual_attributes": actual_attributes,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _attributes_description(attributes: tuple[tuple[str, str], ...]) -> str:
    return ", ".join(f"{name}={value}" for name, value in attributes)


def _bounded_evidence_text(passage: str) -> str:
    normalized = passage.strip()
    if not normalized:
        raise OpenApiConsistencyRejected(
            "Cited requirement passages must contain non-empty text"
        )
    if len(normalized) <= MAX_FINDING_TEXT_LENGTH:
        return normalized
    return f"{normalized[: MAX_FINDING_TEXT_LENGTH - 1]}…"


def _require_canonical_json(value: str) -> None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise OpenApiConsistencyRejected(
            "Expected attributes must use canonical JSON values"
        ) from error

    if (
        json.dumps(parsed, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        != value
    ):
        raise OpenApiConsistencyRejected(
            "Expected attributes must use canonical JSON values"
        )
