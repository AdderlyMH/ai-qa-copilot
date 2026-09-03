from __future__ import annotations

from ai_qa_copilot_api.openapi_facts import (
    OPENAPI_FACT_SCHEMA_VERSION,
    OpenApiFactDifferenceKind,
    OpenApiFactKind,
    diff_openapi_facts,
    extract_openapi_facts,
)


BASE_SPEC = b"""{
  "openapi": "3.1.0",
  "security": [{"bearerAuth": []}],
  "paths": {
    "/pets/{petId}": {
      "parameters": [{"name": "petId", "in": "path", "required": true, "schema": {"type": "string", "maxLength": 36}}],
      "get": {
        "operationId": "getPet",
        "parameters": [{"name": "include", "in": "query", "schema": {"type": "string", "enum": ["owner", "visits"]}}],
        "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}}}
      }
    }
  },
  "components": {
    "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
    "schemas": {
      "Pet": {"type": "object", "properties": {"status": {"type": "string", "enum": ["available", "sold"]}, "name": {"type": "string", "minLength": 1, "maxLength": 120}}}
    }
  }
}"""


def fact_map(
    raw: bytes,
) -> dict[tuple[OpenApiFactKind, str], tuple[tuple[str, str], ...]]:
    extracted = extract_openapi_facts(document_type="openapi-json", raw=raw)
    assert extracted.schema_version == OPENAPI_FACT_SCHEMA_VERSION
    return {(fact.kind, fact.identifier): fact.attributes for fact in extracted.facts}


def test_extracts_operations_parameters_schemas_responses_security_enums_and_limits() -> (
    None
):
    facts = fact_map(BASE_SPEC)

    assert facts[(OpenApiFactKind.OPERATION, "GET /pets/{petId}")] == (
        ("operationId", '"getPet"'),
    )
    assert facts[(OpenApiFactKind.PARAMETER, "path:/pets/{petId}::path:petId")] == (
        ("name", '"petId"'),
        ("in", '"path"'),
        ("required", "true"),
    )
    assert facts[(OpenApiFactKind.RESPONSE, "GET /pets/{petId}::200")] == (
        ("media_types", '["application/json"]'),
    )
    assert facts[(OpenApiFactKind.SECURITY, "scheme:bearerAuth")] == (
        ("type", '"http"'),
        ("scheme", '"bearer"'),
    )
    assert facts[(OpenApiFactKind.ENUM, "component:Pet.status::enum")] == (
        ("values", '["available","sold"]'),
    )
    assert facts[(OpenApiFactKind.LIMIT, "component:Pet.name::maxLength")] == (
        ("value", "120"),
    )


def test_diff_represents_known_contract_mismatches_without_an_llm() -> None:
    changed = BASE_SPEC.replace(b'"maxLength": 120', b'"maxLength": 80').replace(
        b'"sold"]', b'"archived", "sold"]'
    )
    before = extract_openapi_facts(document_type="openapi-json", raw=BASE_SPEC)
    after = extract_openapi_facts(document_type="openapi-json", raw=changed)

    differences = diff_openapi_facts(before, after)

    assert [
        (difference.kind, difference.fact_kind, difference.identifier)
        for difference in differences
    ] == [
        (
            OpenApiFactDifferenceKind.CHANGED,
            OpenApiFactKind.ENUM,
            "component:Pet.status::enum",
        ),
        (
            OpenApiFactDifferenceKind.CHANGED,
            OpenApiFactKind.LIMIT,
            "component:Pet.name::maxLength",
        ),
    ]
    assert differences[0].before is not None
    assert differences[0].after is not None
    assert differences[1].before is not None
    assert differences[1].after is not None


def test_diff_represents_added_and_removed_operations_deterministically() -> None:
    before = extract_openapi_facts(
        document_type="openapi-json",
        raw=b'{"openapi":"3.1.0","paths":{"/pets":{"get":{"responses":{}}}}}',
    )
    after = extract_openapi_facts(
        document_type="openapi-json",
        raw=b'{"openapi":"3.1.0","paths":{"/pets":{"post":{"responses":{}}}}}',
    )

    differences = diff_openapi_facts(before, after)

    assert [
        (difference.kind, difference.fact_kind, difference.identifier)
        for difference in differences
    ] == [
        (OpenApiFactDifferenceKind.REMOVED, OpenApiFactKind.OPERATION, "GET /pets"),
        (OpenApiFactDifferenceKind.ADDED, OpenApiFactKind.OPERATION, "POST /pets"),
    ]
