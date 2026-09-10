"""Strict, versioned canonical contract for immutable QA report revisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
from typing import Final
from uuid import UUID


QUALITY_REPORT_SCHEMA_VERSION: Final = "quality-report/v1"
MAX_REPORT_TEXT_LENGTH: Final = 4_000
MAX_REPORT_GENERATOR_VERSION_LENGTH: Final = 120


class QualityReportValidationError(ValueError):
    """Raised when a proposed canonical QA report violates its strict contract."""


class QualityReportSectionName(StrEnum):
    """The complete required set of canonical QA-report sections."""

    SCOPE = "scope"
    SOURCE_INVENTORY = "source_inventory"
    FINDINGS = "findings"
    GENERATED_TESTS = "generated_tests"
    REVIEWED_TESTS = "reviewed_tests"
    TRACEABILITY = "traceability"
    EXECUTION_EVIDENCE = "execution_evidence"
    FAILURE_ANALYSIS = "failure_analysis"
    METRICS = "metrics"
    PROVENANCE = "provenance"
    LIMITATIONS = "limitations"


class QualityReportSectionState(StrEnum):
    """Explicit completion or evidence-gap state for one required section."""

    COMPLETE = "complete"
    NOT_RUN = "not_run"
    FAILED = "failed"
    NOT_AVAILABLE = "not_available"
    NOT_APPLICABLE = "not_applicable"
    UNSUPPORTED = "unsupported"


class QualityReportClaimKind(StrEnum):
    """Classification that keeps observations and inferences distinguishable."""

    OBSERVATION = "observation"
    ANALYSIS = "analysis"
    HYPOTHESIS = "hypothesis"
    RECOMMENDATION = "recommendation"
    LIMITATION = "limitation"
    UNSUPPORTED = "unsupported"


class QualityReportEvidenceKind(StrEnum):
    """Closed evidence-reference taxonomy for canonical report claims."""

    CITATION = "citation"
    FINDING = "finding"
    TEST_CASE = "test_case"
    TRACEABILITY = "traceability"
    EXECUTION_RESULT = "execution_result"
    FAILURE_ANALYSIS = "failure_analysis"
    RETRIEVAL_TRACE = "retrieval_trace"
    MODEL_CONFIGURATION = "model_configuration"


@dataclass(frozen=True)
class QualityReportEvidenceReference:
    """One immutable evidence identity catalogued by the report revision."""

    kind: QualityReportEvidenceKind
    id: UUID

    def as_payload(self) -> dict[str, str]:
        """Render the strict JSON representation."""

        return {
            "kind": self.kind.value,
            "id": str(self.id),
        }


@dataclass(frozen=True)
class QualityReportClaimV1:
    """One bounded report claim with evidence or an explicit evidence gap."""

    id: UUID
    kind: QualityReportClaimKind
    statement: str
    evidence: tuple[QualityReportEvidenceReference, ...]
    unsupported: bool
    unsupported_reason: str | None

    def as_payload(self) -> dict[str, object]:
        """Render the strict JSON representation."""

        return {
            "id": str(self.id),
            "kind": self.kind.value,
            "statement": self.statement,
            "evidence": [item.as_payload() for item in self.evidence],
            "unsupported": self.unsupported,
            "unsupported_reason": self.unsupported_reason,
        }


@dataclass(frozen=True)
class QualityReportSectionV1:
    """One required report section and its explicit evidence state."""

    name: QualityReportSectionName
    state: QualityReportSectionState
    state_reason: str | None
    claims: tuple[QualityReportClaimV1, ...]

    def as_payload(self) -> dict[str, object]:
        """Render the strict JSON representation."""

        return {
            "name": self.name.value,
            "state": self.state.value,
            "state_reason": self.state_reason,
            "claims": [claim.as_payload() for claim in self.claims],
        }


@dataclass(frozen=True)
class QualityReportProvenanceV1:
    """Pinned revision identities required to reproduce report assembly later."""

    source_document_version_ids: tuple[UUID, ...]
    requirement_analysis_run_ids: tuple[UUID, ...]
    generated_test_case_ids: tuple[UUID, ...]
    execution_job_ids: tuple[UUID, ...]

    def as_payload(self) -> dict[str, list[str]]:
        """Render the strict JSON representation."""

        return {
            "source_document_version_ids": [
                str(value) for value in self.source_document_version_ids
            ],
            "requirement_analysis_run_ids": [
                str(value) for value in self.requirement_analysis_run_ids
            ],
            "generated_test_case_ids": [
                str(value) for value in self.generated_test_case_ids
            ],
            "execution_job_ids": [str(value) for value in self.execution_job_ids],
        }


@dataclass(frozen=True)
class QualityReportV1:
    """One immutable report payload before a future durable revision is stored."""

    id: UUID
    project_id: UUID
    created_at: datetime
    generator_version: str
    evidence_catalog: tuple[QualityReportEvidenceReference, ...]
    provenance: QualityReportProvenanceV1
    sections: tuple[QualityReportSectionV1, ...]

    def as_payload(self) -> dict[str, object]:
        """Return the versioned canonical payload from which all formats derive."""

        return {
            "schema_version": QUALITY_REPORT_SCHEMA_VERSION,
            "id": str(self.id),
            "project_id": str(self.project_id),
            "created_at": _timestamp_payload(self.created_at),
            "generator_version": self.generator_version,
            "evidence_catalog": [
                evidence.as_payload() for evidence in self.evidence_catalog
            ],
            "provenance": self.provenance.as_payload(),
            "sections": [section.as_payload() for section in self.sections],
        }

    def canonical_json(self) -> str:
        """Return stable JSON suitable for a future immutable content hash."""

        return json.dumps(
            self.as_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    def content_sha256(self) -> str:
        """Return the SHA-256 of this exact canonical report payload."""

        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


_REPORT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "id",
        "project_id",
        "created_at",
        "generator_version",
        "evidence_catalog",
        "provenance",
        "sections",
    }
)
_EVIDENCE_REFERENCE_FIELDS: Final = frozenset({"kind", "id"})
_CLAIM_FIELDS: Final = frozenset(
    {
        "id",
        "kind",
        "statement",
        "evidence",
        "unsupported",
        "unsupported_reason",
    }
)
_SECTION_FIELDS: Final = frozenset({"name", "state", "state_reason", "claims"})
_PROVENANCE_FIELDS: Final = frozenset(
    {
        "source_document_version_ids",
        "requirement_analysis_run_ids",
        "generated_test_case_ids",
        "execution_job_ids",
    }
)


def validate_quality_report(payload: Mapping[str, object]) -> QualityReportV1:
    """Validate an untrusted payload into an immutable canonical report."""

    _require_exact_fields(payload, _REPORT_FIELDS, "Quality report")
    if payload["schema_version"] != QUALITY_REPORT_SCHEMA_VERSION:
        raise QualityReportValidationError("Unsupported quality report schema version")

    evidence_catalog = _evidence_catalog(payload["evidence_catalog"])
    catalog_set = frozenset(evidence_catalog)
    sections = _sections(payload["sections"], catalog_set)
    _validate_section_set(sections)
    _validate_claim_ids(sections)

    return QualityReportV1(
        id=_uuid(payload["id"], "Quality report id"),
        project_id=_uuid(payload["project_id"], "Quality report project id"),
        created_at=_timestamp(payload["created_at"]),
        generator_version=_generator_version(payload["generator_version"]),
        evidence_catalog=evidence_catalog,
        provenance=_provenance(payload["provenance"]),
        sections=sections,
    )


def _require_exact_fields(
    payload: Mapping[str, object],
    expected: frozenset[str],
    label: str,
) -> None:
    if set(payload) != expected:
        raise QualityReportValidationError(
            f"{label} fields must exactly match the versioned schema"
        )


def _uuid(value: object, label: str) -> UUID:
    if not isinstance(value, str):
        raise QualityReportValidationError(f"{label} must be a UUID string")
    try:
        return UUID(value)
    except ValueError:
        raise QualityReportValidationError(f"{label} must be a UUID string") from None


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise QualityReportValidationError(
            "Quality report creation time must be an ISO-8601 timestamp"
        )

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise QualityReportValidationError(
            "Quality report creation time must be an ISO-8601 timestamp"
        ) from None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QualityReportValidationError(
            "Quality report creation time must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _timestamp_payload(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _generator_version(value: object) -> str:
    if not isinstance(value, str):
        raise QualityReportValidationError("Report generator version must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_REPORT_GENERATOR_VERSION_LENGTH:
        raise QualityReportValidationError(
            "Report generator version must be bounded, non-empty text"
        )
    return normalized


def _evidence_catalog(value: object) -> tuple[QualityReportEvidenceReference, ...]:
    items = _object_list(value, "Quality report evidence catalog")
    catalog = tuple(_evidence_reference(item) for item in items)
    if len(set(catalog)) != len(catalog):
        raise QualityReportValidationError(
            "Quality report evidence catalog must not repeat references"
        )
    return catalog


def _evidence_reference(
    payload: Mapping[str, object],
) -> QualityReportEvidenceReference:
    _require_exact_fields(
        payload,
        _EVIDENCE_REFERENCE_FIELDS,
        "Quality report evidence reference",
    )
    return QualityReportEvidenceReference(
        kind=_enum(
            QualityReportEvidenceKind,
            payload["kind"],
            "Quality report evidence kind",
        ),
        id=_uuid(payload["id"], "Quality report evidence id"),
    )


def _provenance(value: object) -> QualityReportProvenanceV1:
    if not isinstance(value, Mapping):
        raise QualityReportValidationError(
            "Quality report provenance must be an object"
        )
    _require_exact_fields(value, _PROVENANCE_FIELDS, "Quality report provenance")

    return QualityReportProvenanceV1(
        source_document_version_ids=_uuid_list(
            value["source_document_version_ids"],
            "Source document version ids",
        ),
        requirement_analysis_run_ids=_uuid_list(
            value["requirement_analysis_run_ids"],
            "Requirement analysis run ids",
        ),
        generated_test_case_ids=_uuid_list(
            value["generated_test_case_ids"],
            "Generated test case ids",
        ),
        execution_job_ids=_uuid_list(
            value["execution_job_ids"],
            "Execution job ids",
        ),
    )


def _uuid_list(value: object, label: str) -> tuple[UUID, ...]:
    if not isinstance(value, list):
        raise QualityReportValidationError(f"{label} must be a list")

    result = tuple(_uuid(item, label) for item in value)
    if len(set(result)) != len(result):
        raise QualityReportValidationError(f"{label} must not repeat")
    return result


def _sections(
    value: object,
    catalog: frozenset[QualityReportEvidenceReference],
) -> tuple[QualityReportSectionV1, ...]:
    items = _object_list(value, "Quality report sections")
    return tuple(_section(item, catalog) for item in items)


def _section(
    payload: Mapping[str, object],
    catalog: frozenset[QualityReportEvidenceReference],
) -> QualityReportSectionV1:
    _require_exact_fields(payload, _SECTION_FIELDS, "Quality report section")
    section = QualityReportSectionV1(
        name=_enum(
            QualityReportSectionName,
            payload["name"],
            "Quality report section name",
        ),
        state=_enum(
            QualityReportSectionState,
            payload["state"],
            "Quality report section state",
        ),
        state_reason=_optional_text(
            payload["state_reason"],
            "Quality report section state reason",
        ),
        claims=_claims(payload["claims"], catalog),
    )
    _validate_section_state(section)
    return section


def _claims(
    value: object,
    catalog: frozenset[QualityReportEvidenceReference],
) -> tuple[QualityReportClaimV1, ...]:
    items = _object_list(value, "Quality report claims")
    return tuple(_claim(item, catalog) for item in items)


def _claim(
    payload: Mapping[str, object],
    catalog: frozenset[QualityReportEvidenceReference],
) -> QualityReportClaimV1:
    _require_exact_fields(payload, _CLAIM_FIELDS, "Quality report claim")
    evidence = tuple(
        _evidence_reference(item)
        for item in _object_list(payload["evidence"], "Quality report claim evidence")
    )
    if len(set(evidence)) != len(evidence):
        raise QualityReportValidationError(
            "Quality report claim evidence must not repeat references"
        )
    if not set(evidence).issubset(catalog):
        raise QualityReportValidationError(
            "Quality report claim evidence must be catalogued by the report"
        )

    claim = QualityReportClaimV1(
        id=_uuid(payload["id"], "Quality report claim id"),
        kind=_enum(
            QualityReportClaimKind,
            payload["kind"],
            "Quality report claim kind",
        ),
        statement=_text(payload["statement"], "Quality report claim statement"),
        evidence=evidence,
        unsupported=_bool(
            payload["unsupported"],
            "Quality report claim unsupported state",
        ),
        unsupported_reason=_optional_text(
            payload["unsupported_reason"],
            "Quality report claim unsupported reason",
        ),
    )
    _validate_claim_state(claim)
    return claim


def _validate_claim_state(claim: QualityReportClaimV1) -> None:
    if claim.unsupported:
        if claim.kind is not QualityReportClaimKind.UNSUPPORTED:
            raise QualityReportValidationError(
                "Unsupported quality report claims must use the unsupported kind"
            )
        if claim.evidence:
            raise QualityReportValidationError(
                "Unsupported quality report claims must not present evidence"
            )
        if claim.unsupported_reason is None:
            raise QualityReportValidationError(
                "Unsupported quality report claims require an evidence-gap reason"
            )
        return

    if claim.kind is QualityReportClaimKind.UNSUPPORTED:
        raise QualityReportValidationError(
            "Supported quality report claims must use a material claim kind"
        )
    if not claim.evidence:
        raise QualityReportValidationError(
            "Supported quality report claims require catalogued evidence"
        )
    if claim.unsupported_reason is not None:
        raise QualityReportValidationError(
            "Supported quality report claims must not include an unsupported reason"
        )


def _validate_section_state(section: QualityReportSectionV1) -> None:
    if section.state is QualityReportSectionState.COMPLETE:
        if section.state_reason is not None:
            raise QualityReportValidationError(
                "Complete quality report sections must not include a state reason"
            )
        return

    if section.claims:
        raise QualityReportValidationError(
            "Incomplete quality report sections must not include material claims"
        )
    if section.state_reason is None:
        raise QualityReportValidationError(
            "Incomplete quality report sections require an explicit state reason"
        )


def _validate_section_set(sections: tuple[QualityReportSectionV1, ...]) -> None:
    names = tuple(section.name for section in sections)
    if len(set(names)) != len(names):
        raise QualityReportValidationError("Quality report sections must not repeat")
    if set(names) != set(QualityReportSectionName):
        raise QualityReportValidationError(
            "Quality report must include every required section exactly once"
        )


def _validate_claim_ids(sections: tuple[QualityReportSectionV1, ...]) -> None:
    claim_ids = tuple(claim.id for section in sections for claim in section.claims)
    if len(set(claim_ids)) != len(claim_ids):
        raise QualityReportValidationError(
            "Quality report claim ids must be unique across the report"
        )


def _object_list(value: object, label: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise QualityReportValidationError(f"{label} must be a list")

    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping) or not all(
            isinstance(key, str) for key in item
        ):
            raise QualityReportValidationError(f"{label} items must be objects")
        result.append(item)
    return result


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise QualityReportValidationError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_REPORT_TEXT_LENGTH:
        raise QualityReportValidationError(f"{label} must be bounded, non-empty text")
    return normalized


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise QualityReportValidationError(f"{label} must be boolean")
    return value


def _enum[T: StrEnum](enum_type: type[T], value: object, label: str) -> T:
    if not isinstance(value, str):
        raise QualityReportValidationError(f"{label} is not allowed")
    try:
        return enum_type(value)
    except ValueError:
        raise QualityReportValidationError(f"{label} is not allowed") from None
