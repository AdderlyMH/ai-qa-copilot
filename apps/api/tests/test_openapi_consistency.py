from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ai_qa_copilot_api.citations import Citation, SourceLocation
from ai_qa_copilot_api.findings import FindingCategory
from ai_qa_copilot_api.openapi_consistency import (
    OpenApiConsistencyExpectation,
    OpenApiConsistencyKind,
    OpenApiConsistencyRejected,
    SeededConsistencyBaseline,
    analyze_openapi_consistency,
    measure_seeded_consistency_baseline,
)
from ai_qa_copilot_api.openapi_facts import extract_openapi_facts


BASE_SPEC = b"""{
  "openapi": "3.1.0",
  "security": [{"bearerAuth": []}],
  "paths": {
    "/pets/{petId}": {
      "get": {
        "operationId": "getPet",
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "schema": {"$ref": "#/components/schemas/Pet"}
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "securitySchemes": {
      "bearerAuth": {"type": "http", "scheme": "bearer"}
    },
    "schemas": {
      "Pet": {
        "type": "object",
        "properties": {
          "status": {
            "type": "string",
            "enum": ["available", "sold"]
          },
          "name": {
            "type": "string",
            "maxLength": 120
          }
        }
      }
    }
  }
}"""


def citation(*, citation_id: str, passage: str) -> Citation:
    """Build one stable cited requirement for deterministic analyzer tests."""

    return Citation(
        id=UUID(citation_id),
        project_id=UUID("00000000-0000-0000-0000-000000000001"),
        retrieval_trace_id=UUID("00000000-0000-0000-0000-000000000002"),
        document_chunk_id=UUID("00000000-0000-0000-0000-000000000003"),
        document_version_id=UUID("00000000-0000-0000-0000-000000000004"),
        source_location=SourceLocation(
            id=UUID("00000000-0000-0000-0000-000000000005"),
            location_kind="text",
            heading="Pet API requirements",
            line_start=1,
            line_end=1,
            page_start=None,
            page_end=None,
            json_pointer=None,
        ),
        document_type="requirements",
        display_name="pet-api-requirements.md",
        passage=passage,
        created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )


def seeded_defects() -> tuple[OpenApiConsistencyExpectation, ...]:
    """One deliberately incorrect cited expectation per ANA-004 mismatch type."""

    return (
        OpenApiConsistencyExpectation(
            citation=citation(
                citation_id="10000000-0000-0000-0000-000000000001",
                passage="The Pet name field must be an integer.",
            ),
            kind=OpenApiConsistencyKind.FIELD,
            fact_identifier="component:Pet.name",
            expected_attributes=(("type", '"integer"'),),
        ),
        OpenApiConsistencyExpectation(
            citation=citation(
                citation_id="10000000-0000-0000-0000-000000000002",
                passage=(
                    "GET /pets/{petId} must return application/problem+json for 200."
                ),
            ),
            kind=OpenApiConsistencyKind.RESPONSE,
            fact_identifier="GET /pets/{petId}::200",
            expected_attributes=(("media_types", '["application/problem+json"]'),),
        ),
        OpenApiConsistencyExpectation(
            citation=citation(
                citation_id="10000000-0000-0000-0000-000000000003",
                passage="Pet status may only be available.",
            ),
            kind=OpenApiConsistencyKind.ENUM,
            fact_identifier="component:Pet.status::enum",
            expected_attributes=(("values", '["available"]'),),
        ),
        OpenApiConsistencyExpectation(
            citation=citation(
                citation_id="10000000-0000-0000-0000-000000000004",
                passage="The bearerAuth security scheme must use apiKey authentication.",
            ),
            kind=OpenApiConsistencyKind.SECURITY,
            fact_identifier="scheme:bearerAuth",
            expected_attributes=(("scheme", '"apiKey"'),),
        ),
        OpenApiConsistencyExpectation(
            citation=citation(
                citation_id="10000000-0000-0000-0000-000000000005",
                passage="The API must provide POST /pets.",
            ),
            kind=OpenApiConsistencyKind.OPERATION,
            fact_identifier="POST /pets",
            expected_attributes=(),
        ),
        OpenApiConsistencyExpectation(
            citation=citation(
                citation_id="10000000-0000-0000-0000-000000000006",
                passage="Pet names must have a maximum length of 80 characters.",
            ),
            kind=OpenApiConsistencyKind.LIMIT,
            fact_identifier="component:Pet.name::maxLength",
            expected_attributes=(("value", "80"),),
        ),
    )


def test_detects_every_seeded_ana_004_defect_at_the_measurable_baseline() -> None:
    facts = extract_openapi_facts(document_type="openapi-json", raw=BASE_SPEC)
    defects = seeded_defects()

    mismatches = analyze_openapi_consistency(
        expectations=defects,
        facts=facts,
    )
    baseline = measure_seeded_consistency_baseline(
        seeded_defects=defects,
        mismatches=mismatches,
    )

    assert {mismatch.kind for mismatch in mismatches} == {
        OpenApiConsistencyKind.FIELD,
        OpenApiConsistencyKind.RESPONSE,
        OpenApiConsistencyKind.ENUM,
        OpenApiConsistencyKind.SECURITY,
        OpenApiConsistencyKind.OPERATION,
        OpenApiConsistencyKind.LIMIT,
    }
    assert all(
        mismatch.finding.category is FindingCategory.REQUIREMENTS_CONTRACT_MISMATCH
        for mismatch in mismatches
    )
    assert baseline == SeededConsistencyBaseline(
        total_seeded_defects=6,
        detected_defects=6,
        recall=1.0,
        false_positives=0,
    )


def test_returns_no_finding_when_a_cited_requirement_matches_the_contract() -> None:
    facts = extract_openapi_facts(document_type="openapi-json", raw=BASE_SPEC)
    expectation = OpenApiConsistencyExpectation(
        citation=citation(
            citation_id="20000000-0000-0000-0000-000000000001",
            passage="The Pet name field must be a string.",
        ),
        kind=OpenApiConsistencyKind.FIELD,
        fact_identifier="component:Pet.name",
        expected_attributes=(("type", '"string"'),),
    )

    assert (
        analyze_openapi_consistency(
            expectations=(expectation,),
            facts=facts,
        )
        == ()
    )


def test_results_are_stable_when_input_expectations_are_reordered() -> None:
    facts = extract_openapi_facts(document_type="openapi-json", raw=BASE_SPEC)
    defects = seeded_defects()

    assert analyze_openapi_consistency(
        expectations=defects,
        facts=facts,
    ) == analyze_openapi_consistency(
        expectations=tuple(reversed(defects)),
        facts=facts,
    )


def test_rejects_noncanonical_expected_attribute_values() -> None:
    facts = extract_openapi_facts(document_type="openapi-json", raw=BASE_SPEC)
    invalid_expectation = OpenApiConsistencyExpectation(
        citation=citation(
            citation_id="30000000-0000-0000-0000-000000000001",
            passage="The Pet name field must be a string.",
        ),
        kind=OpenApiConsistencyKind.FIELD,
        fact_identifier="component:Pet.name",
        expected_attributes=(("type", '"string" '),),
    )

    with pytest.raises(
        OpenApiConsistencyRejected,
        match="canonical JSON",
    ):
        analyze_openapi_consistency(
            expectations=(invalid_expectation,),
            facts=facts,
        )
