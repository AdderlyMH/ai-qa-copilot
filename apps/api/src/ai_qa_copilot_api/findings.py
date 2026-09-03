"""Strict, versioned contract for grounded requirement-analysis findings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Final
from uuid import UUID


REQUIREMENT_FINDING_SCHEMA_VERSION: Final = "requirement-finding/v1"
MAX_FINDING_TEXT_LENGTH: Final = 4_000


class FindingCategory(StrEnum):
    """The published, closed taxonomy for material quality findings."""

    AMBIGUITY = "ambiguity"
    CONTRADICTION = "contradiction"
    MISSING_ACCEPTANCE_CRITERIA = "missing_acceptance_criteria"
    VALIDATION_GAP = "validation_gap"
    AUTHORIZATION_GAP = "authorization_gap"
    ERROR_HANDLING_GAP = "error_handling_gap"
    STATE_TRANSITION_GAP = "state_transition_gap"
    REQUIREMENTS_CONTRACT_MISMATCH = "requirements_contract_mismatch"
    UNMAPPED_REQUIREMENT = "unmapped_requirement"
    UNMAPPED_OPERATION = "unmapped_operation"
    SECURITY_RISK = "security_risk"
    PERFORMANCE_RISK = "performance_risk"
    UNSUPPORTED_CLAIM = "unsupported_claim"


class FindingSeverity(StrEnum):
    """The published, closed severity taxonomy for requirement findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RequirementFindingValidationError(ValueError):
    """Raised when untrusted model output violates the finding contract."""


@dataclass(frozen=True)
class FindingEvidence:
    """One observed fact linked to a previously validated citation object."""

    citation_id: UUID
    observed_fact: str


@dataclass(frozen=True)
class RequirementFindingV1:
    """A bounded, reviewable finding without inferred facts disguised as evidence."""

    id: UUID
    category: FindingCategory
    severity: FindingSeverity
    evidence: tuple[FindingEvidence, ...]
    analysis: str
    confidence: float
    recommendation: str
    unsupported: bool
    unsupported_reason: str | None

    def as_payload(self) -> dict[str, object]:
        """Render the canonical strict-schema payload for model or API boundaries."""

        return {
            "schema_version": REQUIREMENT_FINDING_SCHEMA_VERSION,
            "id": str(self.id),
            "category": self.category.value,
            "severity": self.severity.value,
            "evidence": [
                {
                    "citation_id": str(evidence.citation_id),
                    "observed_fact": evidence.observed_fact,
                }
                for evidence in self.evidence
            ],
            "analysis": self.analysis,
            "confidence": self.confidence,
            "recommendation": self.recommendation,
            "unsupported": self.unsupported,
            "unsupported_reason": self.unsupported_reason,
        }


_FINDING_FIELDS: Final = frozenset(
    {
        "schema_version",
        "id",
        "category",
        "severity",
        "evidence",
        "analysis",
        "confidence",
        "recommendation",
        "unsupported",
        "unsupported_reason",
    }
)
_EVIDENCE_FIELDS: Final = frozenset({"citation_id", "observed_fact"})


def validate_requirement_finding(payload: Mapping[str, object]) -> RequirementFindingV1:
    """Validate one untrusted payload into the immutable ``RequirementFindingV1``."""

    _require_exact_fields(payload, _FINDING_FIELDS, "Finding")
    if payload["schema_version"] != REQUIREMENT_FINDING_SCHEMA_VERSION:
        raise RequirementFindingValidationError("Unsupported finding schema version")

    finding = RequirementFindingV1(
        id=_uuid(payload["id"], "Finding id"),
        category=_enum(FindingCategory, payload["category"], "Finding category"),
        severity=_enum(FindingSeverity, payload["severity"], "Finding severity"),
        evidence=_evidence(payload["evidence"]),
        analysis=_text(payload["analysis"], "Finding analysis"),
        confidence=_confidence(payload["confidence"]),
        recommendation=_text(payload["recommendation"], "Finding recommendation"),
        unsupported=_bool(payload["unsupported"], "Finding unsupported state"),
        unsupported_reason=_optional_text(
            payload["unsupported_reason"], "Finding unsupported reason"
        ),
    )
    _validate_evidence_state(finding)
    return finding


def validate_requirement_findings(
    payloads: Sequence[Mapping[str, object]],
) -> tuple[RequirementFindingV1, ...]:
    """Validate a bounded, duplicate-free set of findings deterministically."""

    if not payloads:
        raise RequirementFindingValidationError("At least one finding is required")
    findings = tuple(validate_requirement_finding(payload) for payload in payloads)
    if len({finding.id for finding in findings}) != len(findings):
        raise RequirementFindingValidationError("Finding IDs must be unique")
    return findings


def _require_exact_fields(
    payload: Mapping[str, object], expected: frozenset[str], label: str
) -> None:
    if set(payload) != expected:
        raise RequirementFindingValidationError(
            f"{label} fields must exactly match the versioned schema"
        )


def _uuid(value: object, label: str) -> UUID:
    if not isinstance(value, str):
        raise RequirementFindingValidationError(f"{label} must be a UUID string")
    try:
        return UUID(value)
    except ValueError as error:
        raise RequirementFindingValidationError(
            f"{label} must be a UUID string"
        ) from error


def _enum[T: StrEnum](enum_type: type[T], value: object, label: str) -> T:
    if not isinstance(value, str):
        raise RequirementFindingValidationError(f"{label} is not allowed")
    try:
        return enum_type(value)
    except ValueError as error:
        raise RequirementFindingValidationError(f"{label} is not allowed") from error


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RequirementFindingValidationError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_FINDING_TEXT_LENGTH:
        raise RequirementFindingValidationError(
            f"{label} must be bounded, non-empty text"
        )
    return normalized


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise RequirementFindingValidationError(f"{label} must be boolean")
    return value


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequirementFindingValidationError("Finding confidence must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 <= normalized <= 1:
        raise RequirementFindingValidationError(
            "Finding confidence must be between 0 and 1"
        )
    return normalized


def _evidence(value: object) -> tuple[FindingEvidence, ...]:
    if not isinstance(value, list):
        raise RequirementFindingValidationError("Finding evidence must be a list")
    evidence: list[FindingEvidence] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RequirementFindingValidationError(
                "Finding evidence item must be an object"
            )
        _require_exact_fields(item, _EVIDENCE_FIELDS, "Finding evidence")
        evidence.append(
            FindingEvidence(
                citation_id=_uuid(item["citation_id"], "Citation id"),
                observed_fact=_text(item["observed_fact"], "Observed fact"),
            )
        )
    if len(set(evidence)) != len(evidence):
        raise RequirementFindingValidationError("Finding evidence must not repeat")
    return tuple(evidence)


def _validate_evidence_state(finding: RequirementFindingV1) -> None:
    if finding.unsupported:
        if finding.evidence:
            raise RequirementFindingValidationError(
                "Unsupported findings must not present evidence"
            )
        if finding.category is not FindingCategory.UNSUPPORTED_CLAIM:
            raise RequirementFindingValidationError(
                "Unsupported findings must use the unsupported_claim category"
            )
        if finding.severity is not FindingSeverity.INFO:
            raise RequirementFindingValidationError(
                "Unsupported findings must use info severity"
            )
        if finding.unsupported_reason is None:
            raise RequirementFindingValidationError(
                "Unsupported findings require an evidence-gap reason"
            )
        return

    if not finding.evidence:
        raise RequirementFindingValidationError(
            "Supported findings require at least one citation"
        )
    if finding.category is FindingCategory.UNSUPPORTED_CLAIM:
        raise RequirementFindingValidationError(
            "Supported findings must use a material finding category"
        )
    if finding.unsupported_reason is not None:
        raise RequirementFindingValidationError(
            "Supported findings must not include an unsupported reason"
        )
