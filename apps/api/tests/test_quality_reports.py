from __future__ import annotations

from copy import deepcopy

import pytest

from ai_qa_copilot_api.quality_reports import (
    QUALITY_REPORT_SCHEMA_VERSION,
    QualityReportSectionName,
    QualityReportValidationError,
    validate_quality_report,
)


REPORT_ID = "00000000-0000-0000-0000-00000000e001"
PROJECT_ID = "00000000-0000-0000-0000-00000000e002"
CITATION_ID = "00000000-0000-0000-0000-00000000e003"
CLAIM_ID = "00000000-0000-0000-0000-00000000e004"


def report_payload() -> dict[str, object]:
    incomplete_sections = [
        {
            "name": name.value,
            "state": "not_run",
            "state_reason": "This report revision has no collected evidence yet.",
            "claims": [],
        }
        for name in QualityReportSectionName
        if name is not QualityReportSectionName.SCOPE
    ]

    return {
        "schema_version": QUALITY_REPORT_SCHEMA_VERSION,
        "id": REPORT_ID,
        "project_id": PROJECT_ID,
        "created_at": "2026-09-10T12:00:00Z",
        "generator_version": "quality-report-contract/v1",
        "evidence_catalog": [
            {
                "kind": "citation",
                "id": CITATION_ID,
            }
        ],
        "provenance": {
            "source_document_version_ids": [],
            "requirement_analysis_run_ids": [],
            "generated_test_case_ids": [],
            "execution_job_ids": [],
        },
        "sections": [
            {
                "name": "scope",
                "state": "complete",
                "state_reason": None,
                "claims": [
                    {
                        "id": CLAIM_ID,
                        "kind": "observation",
                        "statement": "One validated source citation is included.",
                        "evidence": [
                            {
                                "kind": "citation",
                                "id": CITATION_ID,
                            }
                        ],
                        "unsupported": False,
                        "unsupported_reason": None,
                    }
                ],
            },
            *incomplete_sections,
        ],
    }


def test_quality_report_validates_every_required_section_and_catalogued_claim() -> None:
    payload = report_payload()

    report = validate_quality_report(payload)

    assert report.as_payload() == payload
    assert len(report.sections) == len(QualityReportSectionName)
    assert report.content_sha256() == report.content_sha256()
    assert len(report.content_sha256()) == 64


def test_quality_report_hash_is_stable_for_equivalent_payloads() -> None:
    first = validate_quality_report(report_payload())
    second = validate_quality_report(deepcopy(report_payload()))

    assert first.canonical_json() == second.canonical_json()
    assert first.content_sha256() == second.content_sha256()


def test_supported_claim_requires_evidence_catalogued_by_the_same_report() -> None:
    payload = report_payload()
    sections = payload["sections"]
    assert isinstance(sections, list)
    scope = sections[0]
    assert isinstance(scope, dict)
    claims = scope["claims"]
    assert isinstance(claims, list)
    claim = claims[0]
    assert isinstance(claim, dict)
    claim["evidence"] = [
        {
            "kind": "citation",
            "id": "00000000-0000-0000-0000-00000000e099",
        }
    ]

    with pytest.raises(
        QualityReportValidationError,
        match="must be catalogued",
    ):
        validate_quality_report(payload)


def test_unsupported_claim_is_an_explicit_evidence_gap_not_a_material_fact() -> None:
    payload = report_payload()
    sections = payload["sections"]
    assert isinstance(sections, list)
    scope = sections[0]
    assert isinstance(scope, dict)
    claims = scope["claims"]
    assert isinstance(claims, list)
    claim = claims[0]
    assert isinstance(claim, dict)
    claim.update(
        {
            "kind": "unsupported",
            "evidence": [],
            "unsupported": True,
            "unsupported_reason": "No validated evidence establishes this claim.",
        }
    )

    report = validate_quality_report(payload)

    assert report.sections[0].claims[0].unsupported is True
    assert report.sections[0].claims[0].evidence == ()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["sections"].pop(),
        lambda payload: payload["sections"].append(deepcopy(payload["sections"][0])),
        lambda payload: payload["sections"][0].update(
            {"state_reason": "Complete sections cannot have a reason."}
        ),
        lambda payload: payload["sections"][1].update(
            {
                "claims": [
                    {
                        "id": "00000000-0000-0000-0000-00000000e005",
                        "kind": "observation",
                        "statement": "A claim cannot exist in an incomplete section.",
                        "evidence": [
                            {
                                "kind": "citation",
                                "id": CITATION_ID,
                            }
                        ],
                        "unsupported": False,
                        "unsupported_reason": None,
                    }
                ]
            }
        ),
    ],
)
def test_quality_report_rejects_missing_duplicate_or_inconsistent_sections(
    mutation: object,
) -> None:
    payload = report_payload()
    assert callable(mutation)
    mutation(payload)

    with pytest.raises(QualityReportValidationError):
        validate_quality_report(payload)


def test_supported_claim_cannot_silently_become_unsupported_or_unsupported_kind() -> (
    None
):
    payload = report_payload()
    sections = payload["sections"]
    assert isinstance(sections, list)
    scope = sections[0]
    assert isinstance(scope, dict)
    claims = scope["claims"]
    assert isinstance(claims, list)
    claim = claims[0]
    assert isinstance(claim, dict)
    claim["unsupported_reason"] = "This must not be attached to a supported claim."

    with pytest.raises(
        QualityReportValidationError,
        match="must not include an unsupported reason",
    ):
        validate_quality_report(payload)
