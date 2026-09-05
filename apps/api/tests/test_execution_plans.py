from dataclasses import replace
from uuid import UUID
from collections.abc import Callable

import pytest

from ai_qa_copilot_api.execution_plans import (
    DEFAULT_EXECUTION_LIMITS,
    ExecutionPlanV1,
    ExecutionLimitsV1,
    ExecutionPlanRejected,
    build_execution_plan,
    review_execution_plan,
    validate_execution_plan,
)
from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    GeneratedAssertionV1,
    GeneratedTestCaseV1,
    GeneratedTestKind,
    HttpMethod,
    RequestTemplateV1,
)


def _test_case(
    *,
    title: str = "Create a synthetic order",
    status_code: int = 201,
    json_body: dict[str, object] | None = None,
) -> GeneratedTestCaseV1:
    return GeneratedTestCaseV1(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        title=title,
        kind=GeneratedTestKind.POSITIVE,
        source_finding_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        citation_ids=(UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),),
        request=RequestTemplateV1(
            method=HttpMethod.POST,
            path="/orders",
            query=(),
            headers=(),
            json_body=json_body,
        ),
        assertions=(
            GeneratedAssertionV1(
                target=AssertionTarget.STATUS_CODE,
                selector=None,
                operator=AssertionOperator.EQUALS,
                expected_value=status_code,
            ),
        ),
    )


def _plan(
    *,
    test_case: GeneratedTestCaseV1 | None = None,
    limits: ExecutionLimitsV1 = DEFAULT_EXECUTION_LIMITS,
) -> ExecutionPlanV1:
    return build_execution_plan(
        generated_test_case=test_case or _test_case(),
        target_id="synthetic-order-api",
        limits=limits,
    )


def test_build_execution_plan_is_deterministic() -> None:
    first = _plan()
    second = _plan()

    assert first == second
    assert first.id == second.id
    assert first.plan_hash == second.plan_hash
    assert len(first.plan_hash) == 64


def test_plan_hash_is_stable_when_json_object_key_order_changes() -> None:
    first = _plan(
        test_case=_test_case(
            json_body={
                "customer": {"name": "Ada", "priority": 1},
                "quantity": 2,
            }
        )
    )
    second = _plan(
        test_case=_test_case(
            json_body={
                "quantity": 2,
                "customer": {"priority": 1, "name": "Ada"},
            }
        )
    )

    assert first.plan_hash == second.plan_hash
    assert first.id == second.id


def test_display_only_title_change_does_not_change_plan_hash() -> None:
    first = _plan(test_case=_test_case(title="Create order"))
    second = _plan(test_case=_test_case(title="Order creation happy path"))

    assert first.test_case_payload != second.test_case_payload
    assert first.plan_hash == second.plan_hash
    assert first.id == second.id


def test_material_assertion_change_changes_plan_hash() -> None:
    first = _plan(test_case=_test_case(status_code=201))
    second = _plan(test_case=_test_case(status_code=200))

    assert first.plan_hash != second.plan_hash
    assert first.id != second.id


def test_material_request_change_changes_plan_hash() -> None:
    first = _plan(test_case=_test_case(json_body={"quantity": 1}))
    second = _plan(test_case=_test_case(json_body={"quantity": 2}))

    assert first.plan_hash != second.plan_hash
    assert first.id != second.id


def test_material_limit_change_changes_plan_hash() -> None:
    first = _plan()
    second = _plan(
        limits=ExecutionLimitsV1(
            request_timeout_ms=5_000,
            max_request_body_bytes=64_000,
            max_response_bytes=256_000,
            max_assertions=20,
        )
    )

    assert first.plan_hash != second.plan_hash
    assert first.id != second.id


def test_plan_retains_deterministic_upper_bound_estimate() -> None:
    plan = _plan(test_case=_test_case(json_body={"quantity": 2}))

    assert plan.estimate.request_count == 1
    assert plan.estimate.assertion_count == 1
    assert plan.estimate.request_body_bytes == len(b'{"quantity":2}')
    assert plan.estimate.maximum_response_bytes == 256_000
    assert plan.estimate.maximum_duration_ms == 10_000


def test_unknown_target_is_rejected() -> None:
    with pytest.raises(ExecutionPlanRejected):
        build_execution_plan(
            generated_test_case=_test_case(),
            target_id="https://untrusted.example/orders",
        )


@pytest.mark.parametrize(
    "limits",
    [
        ExecutionLimitsV1(
            request_timeout_ms=0,
            max_request_body_bytes=64_000,
            max_response_bytes=256_000,
            max_assertions=20,
        ),
        ExecutionLimitsV1(
            request_timeout_ms=10_000,
            max_request_body_bytes=0,
            max_response_bytes=256_000,
            max_assertions=20,
        ),
        ExecutionLimitsV1(
            request_timeout_ms=10_000,
            max_request_body_bytes=64_000,
            max_response_bytes=0,
            max_assertions=20,
        ),
        ExecutionLimitsV1(
            request_timeout_ms=10_000,
            max_request_body_bytes=64_000,
            max_response_bytes=256_000,
            max_assertions=0,
        ),
    ],
)
def test_invalid_limits_are_rejected(limits: ExecutionLimitsV1) -> None:
    with pytest.raises(ExecutionPlanRejected):
        _plan(limits=limits)


def test_request_body_larger_than_limit_is_rejected() -> None:
    with pytest.raises(ExecutionPlanRejected):
        _plan(
            test_case=_test_case(json_body={"payload": "x" * 100}),
            limits=ExecutionLimitsV1(
                request_timeout_ms=10_000,
                max_request_body_bytes=20,
                max_response_bytes=256_000,
                max_assertions=20,
            ),
        )


def test_assertion_count_larger_than_limit_is_rejected() -> None:
    test_case = replace(
        _test_case(),
        assertions=(
            GeneratedAssertionV1(
                target=AssertionTarget.STATUS_CODE,
                selector=None,
                operator=AssertionOperator.EQUALS,
                expected_value=201,
            ),
            GeneratedAssertionV1(
                target=AssertionTarget.RESPONSE_TIME_MS,
                selector=None,
                operator=AssertionOperator.LESS_THAN_OR_EQUAL,
                expected_value=500,
            ),
        ),
    )

    with pytest.raises(ExecutionPlanRejected):
        _plan(
            test_case=test_case,
            limits=ExecutionLimitsV1(
                request_timeout_ms=10_000,
                max_request_body_bytes=64_000,
                max_response_bytes=256_000,
                max_assertions=1,
            ),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda plan: replace(plan, plan_hash="0" * 64),
        lambda plan: replace(plan, target_base_url="https://other.example"),
        lambda plan: replace(
            plan,
            estimate=replace(plan.estimate, maximum_duration_ms=1),
        ),
        lambda plan: replace(
            plan,
            limits=replace(plan.limits, max_response_bytes=1),
        ),
    ],
)
def test_tampered_material_plan_data_is_rejected(
    mutation: Callable[[ExecutionPlanV1], ExecutionPlanV1],
) -> None:
    with pytest.raises(ExecutionPlanRejected):
        validate_execution_plan(mutation(_plan()))


def test_review_returns_read_only_plan_information() -> None:
    plan = _plan()
    review = review_execution_plan(plan)

    assert review.plan_id == plan.id
    assert review.plan_hash == plan.plan_hash
    assert review.target_id.value == "synthetic-order-api"
    assert review.method == "POST"
    assert review.path == "/orders"
    assert review.citation_ids == (UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),)
    assert review.limits == plan.limits
    assert review.estimate == plan.estimate
