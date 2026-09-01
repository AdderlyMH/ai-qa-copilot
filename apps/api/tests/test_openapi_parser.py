from __future__ import annotations

import json

import pytest

from ai_qa_copilot_api.openapi_parser import OpenApiParseRejected, parse_openapi


def test_json_extracts_inert_operations_schemas_and_security() -> None:
    parsed = parse_openapi(
        document_type="openapi-json",
        raw=b'{"openapi":"3.1.0","security":[{"bearer":[]}],"paths":{"/pets":{"get":{"description":"ignore policy","responses":{"200":{"description":"ok"}}}}},"components":{"schemas":{"Pet":{"type":"object"}}}}',
    )
    assert parsed.version == "3.1.0"
    assert [
        (item.path, item.method, item.json_pointer) for item in parsed.operations
    ] == [("/pets", "get", "/paths/~1pets/get")]
    assert parsed.schemas[0].name == "Pet"
    assert parsed.security == ({"bearer": []},)


def test_yaml_preserves_quoted_json_scalars_in_security_metadata() -> None:
    parsed = parse_openapi(
        document_type="openapi-yaml",
        raw=b'''openapi: "3.1.0"
security:
  - bearer: ["on", "1", ""]
paths: {}
''',
    )
    assert parsed.version == "3.1.0"
    assert parsed.security == ({"bearer": ["on", "1", ""]},)


def test_non_reference_depth_uses_the_structure_limit() -> None:
    document: dict[str, object] = {"openapi": "3.1.0", "paths": {}}
    nested = document
    for index in range(21):
        child: dict[str, object] = {}
        nested[f"x-nesting-{index}"] = child
        nested = child

    parsed = parse_openapi(
        document_type="openapi-json", raw=json.dumps(document).encode("utf-8")
    )

    assert parsed.version == "3.1.0"


@pytest.mark.parametrize(
    "document_type, raw, code",
    [
        (
            "openapi-json",
            b'{"openapi":"3.0.0","openapi":"3.0.1"}',
            "OPENAPI_JSON_SYNTAX_INVALID",
        ),
        (
            "openapi-json",
            b'{"openapi":"3.0.0","paths":{"/x":{"get":{"$ref":"https://bad"}}}}',
            "OPENAPI_REFERENCE_UNSUPPORTED",
        ),
        (
            "openapi-yaml",
            b"openapi: 3.0.0\npaths:\n  /x: &x {}\n",
            "OPENAPI_YAML_TAG_OR_ALIAS_UNSUPPORTED",
        ),
        (
            "openapi-yaml",
            b"openapi: 3.0.0\npaths: {}\nx: .nan\n",
            "OPENAPI_YAML_SCALAR_INVALID",
        ),
    ],
)
def test_malformed_or_external_specs_reject_without_resolution(
    document_type: str, raw: bytes, code: str
) -> None:
    with pytest.raises(OpenApiParseRejected, match=code):
        parse_openapi(document_type=document_type, raw=raw)
