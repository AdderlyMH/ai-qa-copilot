from __future__ import annotations

from copy import deepcopy
from typing import cast
from uuid import UUID

import pytest

from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    GeneratedTestCaseValidationError,
    GeneratedTestKind,
    HttpMethod,
    validate_generated_test_case,
    validate_generated_test_cases,
)


TEST_ID = UUID("00000000-0000-0000-0000-000000000601")
SECOND_TEST_ID = UUID("00000000-0000-0000-0000-000000000602")
FINDING_ID = UUID("00000000-0000-0000-0000-000000000603")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000604")


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "generated-test-case/v1",
        "id": str(TEST_ID),
        "title": "Create order returns the expected response",
        "kind": "positive",
        "source_finding_id": str(FINDING_ID),
        "citation_ids": [str(CITATION_ID)],
        "request": {
            "method": "POST",
            "path": "/orders",
            "query": [{"name": "include", "value": "summary"}],
            "headers": [{"name": "Accept", "value": "application/json"}],
            "json_body": {"quantity": 1, "priority": True},
        },
        "assertions": [
            {
                "target": "status_code",
                "selector": None,
                "operator": "equals",
                "expected_value": 201,
            }
        ],
    }


def request_payload(payload: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], payload["request"])


def first_assertion(payload: dict[str, object]) -> dict[str, object]:
    assertions = cast(list[object], payload["assertions"])
    return cast(dict[str, object], assertions[0])


def test_valid_generated_test_case_is_typed_and_round_trips() -> None:
    payload = valid_payload()

    test_case = validate_generated_test_case(payload)

    assert test_case.id == TEST_ID
    assert test_case.kind is GeneratedTestKind.POSITIVE
    assert test_case.request.method is HttpMethod.POST
    assert test_case.assertions[0].target is AssertionTarget.STATUS_CODE
    assert test_case.assertions[0].operator is AssertionOperator.EQUALS
    assert validate_generated_test_case(test_case.as_payload()) == test_case


def test_all_supported_deterministic_assertion_shapes_validate() -> None:
    payload = valid_payload()
    payload["assertions"] = [
        {
            "target": "status_code",
            "selector": None,
            "operator": "equals",
            "expected_value": 201,
        },
        {
            "target": "response_header",
            "selector": "Content-Type",
            "operator": "equals",
            "expected_value": "application/json",
        },
        {
            "target": "response_header",
            "selector": "X-Request-ID",
            "operator": "exists",
            "expected_value": None,
        },
        {
            "target": "json_body",
            "selector": "/order/id",
            "operator": "equals",
            "expected_value": "order-123",
        },
        {
            "target": "json_body",
            "selector": "/order/status",
            "operator": "exists",
            "expected_value": None,
        },
        {
            "target": "json_body",
            "selector": "/message",
            "operator": "contains",
            "expected_value": "created",
        },
        {
            "target": "response_time_ms",
            "selector": None,
            "operator": "less_than_or_equal",
            "expected_value": 500,
        },
    ]

    test_case = validate_generated_test_case(payload)

    assert len(test_case.assertions) == 7


@pytest.mark.parametrize(
    "operator",
    [
        "matches_regex",
        "python",
        "run_script",
    ],
)
def test_unsupported_assertion_operators_are_rejected(operator: str) -> None:
    payload = valid_payload()
    first_assertion(payload)["operator"] = operator

    with pytest.raises(GeneratedTestCaseValidationError, match="operator"):
        validate_generated_test_case(payload)


def test_top_level_script_field_is_rejected() -> None:
    payload = valid_payload()
    payload["script"] = "print('not allowed')"

    with pytest.raises(GeneratedTestCaseValidationError, match="fields"):
        validate_generated_test_case(payload)


def test_request_script_or_command_field_is_rejected() -> None:
    payload = valid_payload()
    request_payload(payload)["pre_request_script"] = "delete_everything()"

    with pytest.raises(GeneratedTestCaseValidationError, match="fields"):
        validate_generated_test_case(payload)


def test_assertion_expression_or_callback_field_is_rejected() -> None:
    payload = valid_payload()
    first_assertion(payload)["expression"] = "response.status == 201"

    with pytest.raises(GeneratedTestCaseValidationError, match="fields"):
        validate_generated_test_case(payload)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "orders",
        "https://example.test/orders",
        "javascript:alert(1)",
        "//other-host/orders",
        "/orders?include=summary",
        "/orders#details",
    ],
)
def test_non_relative_or_non_canonical_request_paths_are_rejected(path: str) -> None:
    payload = valid_payload()
    request_payload(payload)["path"] = path

    with pytest.raises(GeneratedTestCaseValidationError, match="Request path"):
        validate_generated_test_case(payload)


def test_credential_or_routing_headers_are_rejected() -> None:
    payload = valid_payload()
    request_payload(payload)["headers"] = [
        {"name": "Authorization", "value": "Bearer secret"}
    ]

    with pytest.raises(GeneratedTestCaseValidationError, match="Credential"):
        validate_generated_test_case(payload)


@pytest.mark.parametrize(
    "assertion",
    [
        {
            "target": "status_code",
            "selector": None,
            "operator": "exists",
            "expected_value": None,
        },
        {
            "target": "response_header",
            "selector": "Content-Type",
            "operator": "exists",
            "expected_value": "application/json",
        },
        {
            "target": "json_body",
            "selector": None,
            "operator": "equals",
            "expected_value": "value",
        },
        {
            "target": "response_time_ms",
            "selector": None,
            "operator": "equals",
            "expected_value": 500,
        },
    ],
)
def test_invalid_assertion_target_operator_combinations_are_rejected(
    assertion: dict[str, object],
) -> None:
    payload = valid_payload()
    payload["assertions"] = [assertion]

    with pytest.raises(GeneratedTestCaseValidationError):
        validate_generated_test_case(payload)


def test_duplicate_citations_assertions_and_case_ids_are_rejected() -> None:
    duplicate_citations = valid_payload()
    duplicate_citations["citation_ids"] = [str(CITATION_ID), str(CITATION_ID)]

    duplicate_assertions = valid_payload()
    assertion = deepcopy(first_assertion(duplicate_assertions))
    duplicate_assertions["assertions"] = [assertion, deepcopy(assertion)]

    duplicate_case_id = valid_payload()
    duplicate_case_id["id"] = str(TEST_ID)

    with pytest.raises(GeneratedTestCaseValidationError, match="citation IDs"):
        validate_generated_test_case(duplicate_citations)

    with pytest.raises(GeneratedTestCaseValidationError, match="assertions"):
        validate_generated_test_case(duplicate_assertions)

    with pytest.raises(GeneratedTestCaseValidationError, match="IDs"):
        validate_generated_test_cases(
            [valid_payload(), duplicate_case_id],
        )


def test_generated_test_cases_require_at_least_one_case() -> None:
    with pytest.raises(GeneratedTestCaseValidationError, match="At least one"):
        validate_generated_test_cases([])
