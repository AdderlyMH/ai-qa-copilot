"""Deterministic, bounded OpenAPI contract facts and fact-level differences."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ai_qa_copilot_api.openapi_parser import (
    _escape,
    _parse_openapi_root,
    parse_openapi,
)


OPENAPI_FACT_SCHEMA_VERSION: Final = "openapi-facts/v1"
MAX_OPENAPI_FACTS: Final = 50_000
_METHODS: Final = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
_LIMIT_FIELDS: Final = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minProperties",
    "maxProperties",
)


class OpenApiFactKind(StrEnum):
    OPERATION = "operation"
    PARAMETER = "parameter"
    SCHEMA = "schema"
    RESPONSE = "response"
    SECURITY = "security"
    ENUM = "enum"
    LIMIT = "limit"


class OpenApiFactDifferenceKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class OpenApiFactExtractionRejected(ValueError):
    """Raised when validated input would exceed this deterministic fact boundary."""


@dataclass(frozen=True)
class OpenApiFact:
    """One source-addressable, inert contract observation."""

    kind: OpenApiFactKind
    identifier: str
    json_pointer: str
    attributes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class OpenApiFactsV1:
    """A stable, parser-safe fact projection with no inferred contract claims."""

    schema_version: str
    openapi_version: str
    facts: tuple[OpenApiFact, ...]


@dataclass(frozen=True)
class OpenApiFactDifference:
    """An added, removed, or changed fact between two deterministic projections."""

    kind: OpenApiFactDifferenceKind
    fact_kind: OpenApiFactKind
    identifier: str
    before: OpenApiFact | None
    after: OpenApiFact | None


def extract_openapi_facts(*, document_type: str, raw: bytes) -> OpenApiFactsV1:
    """Extract bounded facts only after the existing fail-closed parser accepts input."""
    parsed = parse_openapi(document_type=document_type, raw=raw)
    _, root = _parse_openapi_root(document_type=document_type, raw=raw)
    facts: list[OpenApiFact] = []

    _extract_security_requirements(
        facts, "global", "/security", root.get("security"), inherited=False
    )
    components = _mapping(root.get("components"))
    _extract_security_schemes(facts, _mapping(components.get("securitySchemes")))
    _extract_component_schemas(facts, _mapping(components.get("schemas")))
    _extract_operations(facts, root, parsed.security)

    ordered = tuple(sorted(facts, key=lambda fact: (fact.kind.value, fact.identifier)))
    return OpenApiFactsV1(OPENAPI_FACT_SCHEMA_VERSION, parsed.version, ordered)


def diff_openapi_facts(
    before: OpenApiFactsV1, after: OpenApiFactsV1
) -> tuple[OpenApiFactDifference, ...]:
    """Return a stable, value-preserving diff without classifying risk or intent."""
    if (
        before.schema_version != OPENAPI_FACT_SCHEMA_VERSION
        or after.schema_version != OPENAPI_FACT_SCHEMA_VERSION
    ):
        raise ValueError("OpenAPI facts must use the supported schema version")
    before_index = _index_facts(before.facts)
    after_index = _index_facts(after.facts)
    differences: list[OpenApiFactDifference] = []
    for key in sorted(set(before_index) | set(after_index)):
        left, right = before_index.get(key), after_index.get(key)
        if left is None:
            assert right is not None
            differences.append(
                OpenApiFactDifference(
                    OpenApiFactDifferenceKind.ADDED,
                    right.kind,
                    right.identifier,
                    None,
                    right,
                )
            )
        elif right is None:
            differences.append(
                OpenApiFactDifference(
                    OpenApiFactDifferenceKind.REMOVED,
                    left.kind,
                    left.identifier,
                    left,
                    None,
                )
            )
        elif left != right:
            differences.append(
                OpenApiFactDifference(
                    OpenApiFactDifferenceKind.CHANGED,
                    left.kind,
                    left.identifier,
                    left,
                    right,
                )
            )
    return tuple(differences)


def _extract_operations(
    facts: list[OpenApiFact],
    root: Mapping[str, object],
    inherited_security: tuple[object, ...],
) -> None:
    paths = _mapping(root.get("paths"))
    for path in sorted(paths):
        path_item = _mapping(paths[path])
        path_pointer = f"/paths/{_escape(path)}"
        _extract_parameters(
            facts, f"path:{path}", path_pointer, path_item.get("parameters")
        )
        for method in sorted(key for key in path_item if key.lower() in _METHODS):
            operation = _mapping(path_item[method])
            operation_key = f"{method.upper()} {path}"
            operation_pointer = f"{path_pointer}/{_escape(method)}"
            _append(
                facts,
                OpenApiFactKind.OPERATION,
                operation_key,
                operation_pointer,
                _attributes(operation, ("operationId", "deprecated")),
            )
            _extract_parameters(
                facts, operation_key, operation_pointer, operation.get("parameters")
            )
            _extract_responses(
                facts, operation_key, operation_pointer, operation.get("responses")
            )
            security = operation.get("security", inherited_security)
            _extract_security_requirements(
                facts,
                operation_key,
                f"{operation_pointer}/security",
                security,
                inherited="security" not in operation,
            )


def _extract_parameters(
    facts: list[OpenApiFact], scope: str, pointer: str, value: object
) -> None:
    if not isinstance(value, list):
        return
    for index, item in enumerate(value):
        parameter = _mapping(item)
        item_pointer = f"{pointer}/parameters/{index}"
        name = parameter.get("name")
        location = parameter.get("in")
        identifier = (
            f"{scope}::{location}:{name}"
            if isinstance(name, str) and isinstance(location, str)
            else f"{scope}::parameter[{index}]"
        )
        _append(
            facts,
            OpenApiFactKind.PARAMETER,
            identifier,
            item_pointer,
            _attributes(parameter, ("name", "in", "required", "$ref")),
        )
        schema = _mapping(parameter.get("schema"))
        if schema:
            _extract_schema(
                facts, f"parameter:{identifier}", f"{item_pointer}/schema", schema
            )


def _extract_responses(
    facts: list[OpenApiFact], operation_key: str, pointer: str, value: object
) -> None:
    responses = _mapping(value)
    for status in sorted(responses):
        response = _mapping(responses[status])
        response_pointer = f"{pointer}/responses/{_escape(status)}"
        identifier = f"{operation_key}::{status}"
        content = _mapping(response.get("content"))
        response_attributes = _attributes(response, ("$ref",))
        if content:
            response_attributes += (("media_types", _canonical(sorted(content))),)
        _append(
            facts,
            OpenApiFactKind.RESPONSE,
            identifier,
            response_pointer,
            response_attributes,
        )
        for media_type in sorted(content):
            media = _mapping(content[media_type])
            schema = _mapping(media.get("schema"))
            if schema:
                _extract_schema(
                    facts,
                    f"response:{identifier}:{media_type}",
                    f"{response_pointer}/content/{_escape(media_type)}/schema",
                    schema,
                )


def _extract_component_schemas(
    facts: list[OpenApiFact], schemas: Mapping[str, object]
) -> None:
    for name in sorted(schemas):
        schema = _mapping(schemas[name])
        if schema:
            _extract_schema(
                facts,
                f"component:{name}",
                f"/components/schemas/{_escape(name)}",
                schema,
            )


def _extract_schema(
    facts: list[OpenApiFact],
    identifier: str,
    pointer: str,
    schema: Mapping[str, object],
) -> None:
    _append(
        facts,
        OpenApiFactKind.SCHEMA,
        identifier,
        pointer,
        _attributes(schema, ("type", "format", "nullable", "$ref")),
    )
    if "enum" in schema:
        _append(
            facts,
            OpenApiFactKind.ENUM,
            f"{identifier}::enum",
            pointer,
            (("values", _canonical(schema["enum"])),),
        )
    for limit in _LIMIT_FIELDS:
        if limit in schema:
            _append(
                facts,
                OpenApiFactKind.LIMIT,
                f"{identifier}::{limit}",
                pointer,
                (("value", _canonical(schema[limit])),),
            )
    properties = _mapping(schema.get("properties"))
    for name in sorted(properties):
        nested = _mapping(properties[name])
        if nested:
            _extract_schema(
                facts,
                f"{identifier}.{name}",
                f"{pointer}/properties/{_escape(name)}",
                nested,
            )
    items = _mapping(schema.get("items"))
    if items:
        _extract_schema(facts, f"{identifier}[]", f"{pointer}/items", items)


def _extract_security_schemes(
    facts: list[OpenApiFact], schemes: Mapping[str, object]
) -> None:
    for name in sorted(schemes):
        scheme = _mapping(schemes[name])
        _append(
            facts,
            OpenApiFactKind.SECURITY,
            f"scheme:{name}",
            f"/components/securitySchemes/{_escape(name)}",
            _attributes(
                scheme, ("type", "scheme", "bearerFormat", "openIdConnectUrl", "$ref")
            ),
        )


def _extract_security_requirements(
    facts: list[OpenApiFact],
    scope: str,
    pointer: str,
    value: object,
    *,
    inherited: bool,
) -> None:
    if not isinstance(value, list):
        return
    _append(
        facts,
        OpenApiFactKind.SECURITY,
        f"requirement:{scope}",
        pointer,
        (("requirements", _canonical(value)), ("inherited", _canonical(inherited))),
    )


def _attributes(
    value: Mapping[str, object], fields: Sequence[str]
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (field, _canonical(value[field])) for field in fields if field in value
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _append(
    facts: list[OpenApiFact],
    kind: OpenApiFactKind,
    identifier: str,
    pointer: str,
    attributes: tuple[tuple[str, str], ...],
) -> None:
    if len(facts) >= MAX_OPENAPI_FACTS:
        raise OpenApiFactExtractionRejected("OPENAPI_FACT_LIMIT")
    facts.append(OpenApiFact(kind, identifier, pointer, attributes))


def _index_facts(
    facts: Sequence[OpenApiFact],
) -> dict[tuple[OpenApiFactKind, str], OpenApiFact]:
    index = {(fact.kind, fact.identifier): fact for fact in facts}
    if len(index) != len(facts):
        raise ValueError("OpenAPI facts must have unique kind and identifier pairs")
    return index
