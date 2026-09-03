from __future__ import annotations

from copy import deepcopy

import pytest

from ai_qa_copilot_api.findings import (
    FindingCategory,
    FindingSeverity,
    RequirementFindingValidationError,
    validate_requirement_finding,
    validate_requirement_findings,
)


FINDING_ID = "00000000-0000-0000-0000-000000000b01"
CITATION_ID = "00000000-0000-0000-0000-000000000b02"


def supported_payload() -> dict[str, object]:
    return {
        "schema_version": "requirement-finding/v1",
        "id": FINDING_ID,
        "category": "ambiguity",
        "severity": "medium",
        "evidence": [
            {
                "citation_id": CITATION_ID,
                "observed_fact": "The requirement says refunds happen promptly.",
            }
        ],
        "analysis": "Promptly is not a measurable completion criterion.",
        "confidence": 0.85,
        "recommendation": "Define a measurable refund completion timeframe.",
        "unsupported": False,
        "unsupported_reason": None,
    }


def unsupported_payload() -> dict[str, object]:
    payload = supported_payload()
    payload.update(
        {
            "category": "unsupported_claim",
            "severity": "info",
            "evidence": [],
            "analysis": "The available evidence does not establish a refund timeframe.",
            "recommendation": "Provide an authoritative refund policy source.",
            "unsupported": True,
            "unsupported_reason": "No validated source addresses the requested timeframe.",
        }
    )
    return payload


def test_supported_finding_has_controlled_taxonomy_and_citation_evidence() -> None:
    finding = validate_requirement_finding(supported_payload())

    assert finding.category is FindingCategory.AMBIGUITY
    assert finding.severity is FindingSeverity.MEDIUM
    assert finding.confidence == 0.85
    assert finding.unsupported is False
    assert finding.as_payload() == supported_payload()


def test_unsupported_finding_is_visibly_an_evidence_gap() -> None:
    finding = validate_requirement_finding(unsupported_payload())

    assert finding.category is FindingCategory.UNSUPPORTED_CLAIM
    assert finding.severity is FindingSeverity.INFO
    assert finding.evidence == ()
    assert finding.unsupported_reason is not None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update({"category": "invented_category"}), "category"),
        (lambda payload: payload.update({"severity": "urgent"}), "severity"),
        (lambda payload: payload.update({"evidence": []}), "at least one citation"),
        (lambda payload: payload.update({"confidence": 1.1}), "between 0 and 1"),
        (
            lambda payload: payload.update({"unsupported_reason": "not supported"}),
            "must not",
        ),
        (lambda payload: payload.update({"extra": "not allowed"}), "exactly match"),
    ],
)
def test_supported_finding_rejects_invalid_taxonomy_or_claim_state(
    mutation: object, message: str
) -> None:
    payload = supported_payload()
    assert callable(mutation)
    mutation(payload)

    with pytest.raises(RequirementFindingValidationError, match=message):
        validate_requirement_finding(payload)


def test_unsupported_finding_rejects_evidence_or_material_taxonomy() -> None:
    evidence_claim = unsupported_payload()
    evidence_claim["evidence"] = supported_payload()["evidence"]
    material_claim = unsupported_payload()
    material_claim["category"] = "ambiguity"

    with pytest.raises(RequirementFindingValidationError, match="must not present"):
        validate_requirement_finding(evidence_claim)
    with pytest.raises(RequirementFindingValidationError, match="unsupported_claim"):
        validate_requirement_finding(material_claim)


def test_finding_collection_rejects_duplicate_ids() -> None:
    first = supported_payload()
    second = deepcopy(supported_payload())

    with pytest.raises(RequirementFindingValidationError, match="IDs must be unique"):
        validate_requirement_findings([first, second])
