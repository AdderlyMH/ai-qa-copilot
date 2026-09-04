"""Strict, data-only contract for generated API test proposals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import math
import re
from typing import Final, cast
from uuid import UUID


GENERATED_TEST_CASE_SCHEMA_VERSION: Final = "generated-test-case/v1"
MAX_GENERATED_TEST_TEXT_LENGTH: Final = 4_000
MAX_REQUEST_PATH_LENGTH: Final = 1_000
MAX_REQUEST_ITEMS: Final = 20
MAX_ASSERTIONS: Final = 20
MAX_JSON_DEPTH: Final = 8
MAX_JSON_ITEMS: Final = 100

_CASE_FIELDS: Final = frozenset(
    {
        "schema_version",
        "id",
        "title",
        "kind",
        "source_finding_id",
        "citation_ids",
        "request",
        "assertions",
    }
)
_REQUEST_FIELDS: Final = frozenset(
    {
        "method",
        "path",
        "query",
        "headers",
        "json_body",
    }
)
_PARAMETER_FIELDS: Final = frozenset({"name", "value"})
_ASSERTION_FIELDS: Final = frozenset(
    {
        "target",
        "selector",
        "operator",
        "expected_value",
    }
)

_HEADER_NAME_PATTERN: Final = re.compile(r"^[A-Za-z0-9-]+$")
_JSON_POINTER_PATTERN: Final = re.compile(r"^/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])+)*$")
_FORBIDDEN_HEADER_NAMES: Final = frozenset(
    {
        "authorization",
        "cookie",
        "host",
        "proxy-authorization",
        "set-cookie",
    }
)

type ExpectedValue = str | int | float | bool | None


class GeneratedTestCaseValidationError(ValueError):
    """Raised when an untrusted generated-test payload violates this contract."""


class GeneratedTestKind(StrEnum):
    """Closed taxonomy for future grounded test proposals."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    AUTHORIZATION = "authorization"
    CONTRACT = "contract"
    STATE = "state"


class HttpMethod(StrEnum):
    """Closed HTTP-method set for a data-only request template."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class AssertionTarget(StrEnum):
    """Closed response targets available to deterministic assertions."""

    STATUS_CODE = "status_code"
    RESPONSE_HEADER = "response_header"
    JSON_BODY = "json_body"
    RESPONSE_TIME_MS = "response_time_ms"


class AssertionOperator(StrEnum):
    """Closed deterministic operator set; no scripts or expressions exist."""

    EQUALS = "equals"
    EXISTS = "exists"
    CONTAINS = "contains"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"


@dataclass(frozen=True)
class RequestQueryParameterV1:
    """One bounded, data-only query parameter."""

    name: str
    value: str


@dataclass(frozen=True)
class RequestHeaderV1:
    """One bounded non-secret request header."""

    name: str
    value: str


@dataclass(frozen=True)
class RequestTemplateV1:
    """A typed request shape with no URL target, script, or execution behavior."""

    method: HttpMethod
    path: str
    query: tuple[RequestQueryParameterV1, ...]
    headers: tuple[RequestHeaderV1, ...]
    json_body: dict[str, object] | None

    def as_payload(self) -> dict[str, object]:
        """Render the canonical request-template payload."""

        return {
            "method": self.method.value,
            "path": self.path,
            "query": [
                {"name": parameter.name, "value": parameter.value}
                for parameter in self.query
            ],
            "headers": [
                {"name": header.name, "value": header.value} for header in self.headers
            ],
            "json_body": self.json_body,
        }


@dataclass(frozen=True)
class GeneratedAssertionV1:
    """One typed deterministic assertion; never an executable expression."""

    target: AssertionTarget
    selector: str | None
    operator: AssertionOperator
    expected_value: ExpectedValue

    def as_payload(self) -> dict[str, object]:
        """Render the canonical assertion payload."""

        return {
            "target": self.target.value,
            "selector": self.selector,
            "operator": self.operator.value,
            "expected_value": self.expected_value,
        }


@dataclass(frozen=True)
class GeneratedTestCaseV1:
    """One immutable, evidence-linked proposal that cannot carry a script."""

    id: UUID
    title: str
    kind: GeneratedTestKind
    source_finding_id: UUID
    citation_ids: tuple[UUID, ...]
    request: RequestTemplateV1
    assertions: tuple[GeneratedAssertionV1, ...]

    def as_payload(self) -> dict[str, object]:
        """Render the canonical strict-schema payload."""

        return {
            "schema_version": GENERATED_TEST_CASE_SCHEMA_VERSION,
            "id": str(self.id),
            "title": self.title,
            "kind": self.kind.value,
            "source_finding_id": str(self.source_finding_id),
            "citation_ids": [str(citation_id) for citation_id in self.citation_ids],
            "request": self.request.as_payload(),
            "assertions": [assertion.as_payload() for assertion in self.assertions],
        }


def validate_generated_test_case(
    payload: Mapping[str, object],
) -> GeneratedTestCaseV1:
    """Validate one untrusted payload into a strict data-only test proposal."""

    _require_exact_fields(payload, _CASE_FIELDS, "Generated test case")
    if payload["schema_version"] != GENERATED_TEST_CASE_SCHEMA_VERSION:
        raise GeneratedTestCaseValidationError(
            "Unsupported generated-test-case schema version"
        )

    test_case = GeneratedTestCaseV1(
        id=_uuid(payload["id"], "Generated test case id"),
        title=_text(payload["title"], "Generated test case title"),
        kind=_enum(GeneratedTestKind, payload["kind"], "Generated test case kind"),
        source_finding_id=_uuid(
            payload["source_finding_id"],
            "Generated test case source finding id",
        ),
        citation_ids=_citation_ids(payload["citation_ids"]),
        request=_request_template(payload["request"]),
        assertions=_assertions(payload["assertions"]),
    )
    return test_case


def validate_generated_test_cases(
    payloads: Sequence[Mapping[str, object]],
) -> tuple[GeneratedTestCaseV1, ...]:
    """Validate a non-empty, duplicate-free group of generated test proposals."""

    if not payloads:
        raise GeneratedTestCaseValidationError(
            "At least one generated test case is required"
        )

    test_cases = tuple(validate_generated_test_case(payload) for payload in payloads)
    if len({test_case.id for test_case in test_cases}) != len(test_cases):
        raise GeneratedTestCaseValidationError("Generated test case IDs must be unique")
    return test_cases


def _request_template(value: object) -> RequestTemplateV1:
    request = _mapping(value, "Request template")
    _require_exact_fields(request, _REQUEST_FIELDS, "Request template")

    return RequestTemplateV1(
        method=_enum(HttpMethod, request["method"], "Request method"),
        path=_request_path(request["path"]),
        query=_query_parameters(request["query"]),
        headers=_request_headers(request["headers"]),
        json_body=_json_body(request["json_body"]),
    )


def _query_parameters(value: object) -> tuple[RequestQueryParameterV1, ...]:
    items = _list(value, "Request query")
    if len(items) > MAX_REQUEST_ITEMS:
        raise GeneratedTestCaseValidationError("Request query has too many items")

    parameters: list[RequestQueryParameterV1] = []
    for item in items:
        parameter = _mapping(item, "Request query item")
        _require_exact_fields(parameter, _PARAMETER_FIELDS, "Request query item")
        parameters.append(
            RequestQueryParameterV1(
                name=_parameter_name(parameter["name"], "Request query name"),
                value=_text(parameter["value"], "Request query value"),
            )
        )

    if len({parameter.name for parameter in parameters}) != len(parameters):
        raise GeneratedTestCaseValidationError("Request query names must not repeat")
    return tuple(parameters)


def _request_headers(value: object) -> tuple[RequestHeaderV1, ...]:
    items = _list(value, "Request headers")
    if len(items) > MAX_REQUEST_ITEMS:
        raise GeneratedTestCaseValidationError("Request headers have too many items")

    headers: list[RequestHeaderV1] = []
    for item in items:
        header = _mapping(item, "Request header")
        _require_exact_fields(header, _PARAMETER_FIELDS, "Request header")
        name = _header_name(header["name"])
        headers.append(
            RequestHeaderV1(
                name=name,
                value=_text(header["value"], "Request header value"),
            )
        )

    normalized_names = {header.name.lower() for header in headers}
    if len(normalized_names) != len(headers):
        raise GeneratedTestCaseValidationError("Request header names must not repeat")
    return tuple(headers)


def _json_body(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    body = _mapping(value, "Request JSON body")
    if len(body) > MAX_JSON_ITEMS:
        raise GeneratedTestCaseValidationError("Request JSON body has too many items")
    return {_json_key(key): _json_value(item, depth=0) for key, item in body.items()}


def _json_value(value: object, *, depth: int) -> object:
    if depth > MAX_JSON_DEPTH:
        raise GeneratedTestCaseValidationError("Request JSON body is too deeply nested")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > MAX_GENERATED_TEST_TEXT_LENGTH:
            raise GeneratedTestCaseValidationError("Request JSON text is too long")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GeneratedTestCaseValidationError(
                "Request JSON numbers must be finite"
            )
        return value
    if isinstance(value, list):
        if len(value) > MAX_JSON_ITEMS:
            raise GeneratedTestCaseValidationError(
                "Request JSON array has too many items"
            )
        return [_json_value(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        if len(mapping) > MAX_JSON_ITEMS:
            raise GeneratedTestCaseValidationError(
                "Request JSON object has too many items"
            )
        return {
            _json_key(key): _json_value(item, depth=depth + 1)
            for key, item in mapping.items()
        }
    raise GeneratedTestCaseValidationError("Request JSON body must contain JSON data")


def _assertions(value: object) -> tuple[GeneratedAssertionV1, ...]:
    items = _list(value, "Generated test assertions")
    if not items:
        raise GeneratedTestCaseValidationError(
            "Generated test cases require at least one assertion"
        )
    if len(items) > MAX_ASSERTIONS:
        raise GeneratedTestCaseValidationError(
            "Generated test cases have too many assertions"
        )

    assertions: list[GeneratedAssertionV1] = []
    for item in items:
        assertion_payload = _mapping(item, "Generated assertion")
        _require_exact_fields(
            assertion_payload,
            _ASSERTION_FIELDS,
            "Generated assertion",
        )
        assertion = GeneratedAssertionV1(
            target=_enum(
                AssertionTarget,
                assertion_payload["target"],
                "Assertion target",
            ),
            selector=_optional_selector(assertion_payload["selector"]),
            operator=_enum(
                AssertionOperator,
                assertion_payload["operator"],
                "Assertion operator",
            ),
            expected_value=_expected_value(assertion_payload["expected_value"]),
        )
        _validate_assertion_contract(assertion)
        assertions.append(assertion)

    if len(set(assertions)) != len(assertions):
        raise GeneratedTestCaseValidationError("Generated assertions must not repeat")
    return tuple(assertions)


def _validate_assertion_contract(assertion: GeneratedAssertionV1) -> None:
    if assertion.target is AssertionTarget.STATUS_CODE:
        if (
            assertion.selector is not None
            or assertion.operator is not AssertionOperator.EQUALS
            or not _is_status_code(assertion.expected_value)
        ):
            raise GeneratedTestCaseValidationError(
                "Status-code assertions require equals and an HTTP status code"
            )
        return

    if assertion.target is AssertionTarget.RESPONSE_HEADER:
        if (
            assertion.selector is None
            or not _HEADER_NAME_PATTERN.fullmatch(assertion.selector)
            or assertion.operator
            not in {AssertionOperator.EQUALS, AssertionOperator.EXISTS}
        ):
            raise GeneratedTestCaseValidationError(
                "Response-header assertions require a header-name selector"
            )
        if assertion.operator is AssertionOperator.EXISTS:
            if assertion.expected_value is not None:
                raise GeneratedTestCaseValidationError(
                    "Exists assertions must not include an expected value"
                )
        elif not isinstance(assertion.expected_value, str):
            raise GeneratedTestCaseValidationError(
                "Header equals assertions require a text expected value"
            )
        return

    if assertion.target is AssertionTarget.JSON_BODY:
        if (
            assertion.selector is None
            or not _JSON_POINTER_PATTERN.fullmatch(assertion.selector)
            or assertion.operator
            not in {
                AssertionOperator.EQUALS,
                AssertionOperator.EXISTS,
                AssertionOperator.CONTAINS,
            }
        ):
            raise GeneratedTestCaseValidationError(
                "JSON-body assertions require a JSON-pointer selector"
            )
        if assertion.operator is AssertionOperator.EXISTS:
            if assertion.expected_value is not None:
                raise GeneratedTestCaseValidationError(
                    "Exists assertions must not include an expected value"
                )
        elif assertion.operator is AssertionOperator.CONTAINS and not isinstance(
            assertion.expected_value, str
        ):
            raise GeneratedTestCaseValidationError(
                "JSON-body contains assertions require a text expected value"
            )
        return

    if assertion.target is AssertionTarget.RESPONSE_TIME_MS:
        if (
            assertion.selector is not None
            or assertion.operator is not AssertionOperator.LESS_THAN_OR_EQUAL
            or not _is_positive_integer(assertion.expected_value)
        ):
            raise GeneratedTestCaseValidationError(
                "Response-time assertions require less_than_or_equal and "
                "a positive integer expected value"
            )
        return

    raise GeneratedTestCaseValidationError("Assertion target is not allowed")


def _citation_ids(value: object) -> tuple[UUID, ...]:
    items = _list(value, "Generated test case citation IDs")
    if not items:
        raise GeneratedTestCaseValidationError(
            "Generated test cases require at least one citation ID"
        )

    citation_ids = tuple(
        _uuid(item, "Generated test case citation id") for item in items
    )
    if len(set(citation_ids)) != len(citation_ids):
        raise GeneratedTestCaseValidationError(
            "Generated test case citation IDs must not repeat"
        )
    return citation_ids


def _request_path(value: object) -> str:
    path = _text(value, "Request path")
    if len(path) > MAX_REQUEST_PATH_LENGTH:
        raise GeneratedTestCaseValidationError("Request path is too long")
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or "://" in path
        or "?" in path
        or "#" in path
    ):
        raise GeneratedTestCaseValidationError(
            "Request path must be a relative path without a URL, query, or fragment"
        )
    return path


def _header_name(value: object) -> str:
    name = _text(value, "Request header name")
    if not _HEADER_NAME_PATTERN.fullmatch(name):
        raise GeneratedTestCaseValidationError("Request header name is not allowed")
    if name.lower() in _FORBIDDEN_HEADER_NAMES:
        raise GeneratedTestCaseValidationError(
            "Credential or routing headers are not allowed"
        )
    return name


def _parameter_name(value: object, label: str) -> str:
    name = _text(value, label)
    if len(name) > 256:
        raise GeneratedTestCaseValidationError(f"{label} is too long")
    return name


def _json_key(value: str) -> str:
    if not isinstance(value, str):
        raise GeneratedTestCaseValidationError("Request JSON keys must be text")
    return _text(value, "Request JSON key")


def _optional_selector(value: object) -> str | None:
    if value is None:
        return None
    return _text(value, "Assertion selector")


def _expected_value(value: object) -> ExpectedValue:
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > MAX_GENERATED_TEST_TEXT_LENGTH:
            raise GeneratedTestCaseValidationError(
                "Assertion expected value is too long"
            )
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GeneratedTestCaseValidationError(
                "Assertion expected numbers must be finite"
            )
        return value
    raise GeneratedTestCaseValidationError(
        "Assertion expected values must be scalar JSON values"
    )


def _is_status_code(value: ExpectedValue) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599
    )


def _is_positive_integer(value: ExpectedValue) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _require_exact_fields(
    payload: Mapping[str, object],
    expected_fields: frozenset[str],
    label: str,
) -> None:
    if set(payload) != expected_fields:
        raise GeneratedTestCaseValidationError(
            f"{label} fields must exactly match the versioned schema"
        )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GeneratedTestCaseValidationError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise GeneratedTestCaseValidationError(f"{label} must be a list")
    return value


def _uuid(value: object, label: str) -> UUID:
    if not isinstance(value, str):
        raise GeneratedTestCaseValidationError(f"{label} must be a UUID string")
    try:
        return UUID(value)
    except ValueError as error:
        raise GeneratedTestCaseValidationError(
            f"{label} must be a UUID string"
        ) from error


def _enum[T: StrEnum](enum_type: type[T], value: object, label: str) -> T:
    if not isinstance(value, str):
        raise GeneratedTestCaseValidationError(f"{label} is not allowed")
    try:
        return enum_type(value)
    except ValueError as error:
        raise GeneratedTestCaseValidationError(f"{label} is not allowed") from error


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise GeneratedTestCaseValidationError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_GENERATED_TEST_TEXT_LENGTH:
        raise GeneratedTestCaseValidationError(
            f"{label} must be bounded, non-empty text"
        )
    return normalized
