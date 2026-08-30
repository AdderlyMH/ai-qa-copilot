"""Fail-closed, no-I/O OpenAPI 3.0/3.1 JSON and YAML parser."""

from __future__ import annotations

import json
from dataclasses import dataclass
import yaml

MAX_DEPTH = 40
MAX_NODES = 25_000
MAX_MEMBERS = 10_000
MAX_SCALAR_LENGTH = 64 * 1024
MAX_REFERENCES = 500
MAX_REFERENCE_DEPTH = 20
MAX_OPERATIONS = 500
MAX_COMPONENTS = 5_000
_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


class OpenApiParseRejected(ValueError):
    """Terminal safe parser rejection; callers must not retry or continue work."""


@dataclass(frozen=True)
class OpenApiOperation:
    path: str
    method: str
    json_pointer: str
    security: tuple[object, ...]


@dataclass(frozen=True)
class OpenApiSchema:
    name: str
    json_pointer: str


@dataclass(frozen=True)
class ParsedOpenApi:
    version: str
    operations: tuple[OpenApiOperation, ...]
    schemas: tuple[OpenApiSchema, ...]
    security: tuple[object, ...]


def parse_openapi(*, document_type: str, raw: bytes) -> ParsedOpenApi:
    """Parse an inert OpenAPI document without resolving any external data."""
    if document_type not in {"openapi-json", "openapi-yaml"}:
        raise OpenApiParseRejected("OPENAPI_DOCUMENT_TYPE_UNSUPPORTED")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise OpenApiParseRejected("OPENAPI_TEXT_ENCODING_INVALID") from error
    value = _load_json(text) if document_type == "openapi-json" else _load_yaml(text)
    _validate_value(value, depth=0, state={"nodes": 0, "references": 0})
    if not isinstance(value, dict):
        raise OpenApiParseRejected("OPENAPI_ROOT_OBJECT_REQUIRED")
    version = value.get("openapi")
    if not isinstance(version, str) or not (
        version.startswith("3.0.") or version.startswith("3.1.")
    ):
        raise OpenApiParseRejected("OPENAPI_VERSION_UNSUPPORTED")
    _validate_references(value)
    paths = value.get("paths", {})
    if not isinstance(paths, dict):
        raise OpenApiParseRejected("OPENAPI_PATHS_OBJECT_REQUIRED")
    operations: list[OpenApiOperation] = []
    for path, path_item in paths.items():
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or not isinstance(path_item, dict)
        ):
            raise OpenApiParseRejected("OPENAPI_PATH_ITEM_INVALID")
        for method, operation in path_item.items():
            if method.lower() not in _METHODS:
                continue
            if not isinstance(operation, dict):
                raise OpenApiParseRejected("OPENAPI_OPERATION_INVALID")
            operations.append(
                OpenApiOperation(
                    path,
                    method.lower(),
                    f"/paths/{_escape(path)}/{method}",
                    _security(operation.get("security", value.get("security", ()))),
                )
            )
    if len(operations) > MAX_OPERATIONS:
        raise OpenApiParseRejected("OPENAPI_OPERATION_LIMIT")
    components = value.get("components", {})
    if not isinstance(components, dict):
        raise OpenApiParseRejected("OPENAPI_COMPONENTS_OBJECT_REQUIRED")
    schemas = components.get("schemas", {})
    if not isinstance(schemas, dict):
        raise OpenApiParseRejected("OPENAPI_SCHEMAS_OBJECT_REQUIRED")
    if len(schemas) > MAX_COMPONENTS:
        raise OpenApiParseRejected("OPENAPI_COMPONENT_LIMIT")
    parsed_schemas = tuple(
        OpenApiSchema(name, f"/components/schemas/{_escape(name)}")
        for name in schemas
        if isinstance(name, str)
    )
    return ParsedOpenApi(
        version, tuple(operations), parsed_schemas, _security(value.get("security", ()))
    )


def _load_json(text: str) -> object:
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, OpenApiParseRejected) as error:
        raise OpenApiParseRejected("OPENAPI_JSON_SYNTAX_INVALID") from error


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise OpenApiParseRejected("OPENAPI_DUPLICATE_KEY")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise OpenApiParseRejected(f"OPENAPI_JSON_CONSTANT_INVALID:{value}")


def _load_yaml(text: str) -> object:
    if "---" in text or "..." in text or "%" in text:
        raise OpenApiParseRejected("OPENAPI_YAML_DIRECTIVE_OR_MULTIDOCUMENT")
    try:
        prohibited = (
            yaml.tokens.AnchorToken,
            yaml.tokens.AliasToken,
            yaml.tokens.TagToken,
            yaml.tokens.DirectiveToken,
        )
        if any(
            isinstance(token, prohibited)
            for token in yaml.scan(text, Loader=yaml.SafeLoader)
        ):
            raise OpenApiParseRejected("OPENAPI_YAML_TAG_OR_ALIAS_UNSUPPORTED")
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise OpenApiParseRejected("OPENAPI_YAML_SYNTAX_INVALID") from error
    if node is None:
        raise OpenApiParseRejected("OPENAPI_YAML_EMPTY")
    return _yaml_node_to_json(node)


def _yaml_node_to_json(node: yaml.Node) -> object:
    if getattr(node, "anchor", None) is not None or node.tag not in {
        "tag:yaml.org,2002:map",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:null",
    }:
        raise OpenApiParseRejected("OPENAPI_YAML_TAG_OR_ALIAS_UNSUPPORTED")
    if isinstance(node, yaml.MappingNode):
        value: dict[str, object] = {}
        for key_node, value_node in node.value:
            key = _yaml_node_to_json(key_node)
            if not isinstance(key, str) or key in value or key == "<<":
                raise OpenApiParseRejected("OPENAPI_YAML_KEY_OR_MERGE_INVALID")
            value[key] = _yaml_node_to_json(value_node)
        return value
    if isinstance(node, yaml.SequenceNode):
        return [_yaml_node_to_json(item) for item in node.value]
    if isinstance(node, yaml.ScalarNode):
        try:
            return yaml.safe_load(node.value)
        except yaml.YAMLError as error:
            raise OpenApiParseRejected("OPENAPI_YAML_SCALAR_INVALID") from error
    raise OpenApiParseRejected("OPENAPI_YAML_NODE_UNSUPPORTED")


def _validate_value(value: object, *, depth: int, state: dict[str, int]) -> None:
    state["nodes"] += 1
    if depth > MAX_DEPTH or state["nodes"] > MAX_NODES:
        raise OpenApiParseRejected("OPENAPI_STRUCTURE_LIMIT")
    if isinstance(value, dict):
        if len(value) > MAX_MEMBERS:
            raise OpenApiParseRejected("OPENAPI_COLLECTION_LIMIT")
        for key, item in value.items():
            _validate_value(key, depth=depth + 1, state=state)
            _validate_value(item, depth=depth + 1, state=state)
    elif isinstance(value, list):
        if len(value) > MAX_MEMBERS:
            raise OpenApiParseRejected("OPENAPI_COLLECTION_LIMIT")
        for item in value:
            _validate_value(item, depth=depth + 1, state=state)
    elif isinstance(value, str) and len(value) > MAX_SCALAR_LENGTH:
        raise OpenApiParseRejected("OPENAPI_SCALAR_LIMIT")


def _validate_references(value: object) -> None:
    refs: list[str] = []

    def visit(item: object, depth: int = 0) -> None:
        if depth > MAX_REFERENCE_DEPTH:
            raise OpenApiParseRejected("OPENAPI_REFERENCE_DEPTH_LIMIT")
        if isinstance(item, dict):
            for key, child in item.items():
                if key == "$dynamicRef":
                    raise OpenApiParseRejected("OPENAPI_DYNAMIC_REFERENCE_UNSUPPORTED")
                if key == "$ref":
                    if (
                        not isinstance(child, str)
                        or not child.startswith("#/")
                        or "%" in child
                    ):
                        raise OpenApiParseRejected("OPENAPI_REFERENCE_UNSUPPORTED")
                    refs.append(child)
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)

    visit(value)
    if len(refs) > MAX_REFERENCES:
        raise OpenApiParseRejected("OPENAPI_REFERENCE_LIMIT")


def _security(value: object) -> tuple[object, ...]:
    return tuple(value) if isinstance(value, list) else ()


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
