from __future__ import annotations

from uuid import UUID

import pytest

from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    GeneratedAssertionV1,
    GeneratedTestCaseV1,
    GeneratedTestKind,
    HttpMethod,
    RequestHeaderV1,
    RequestQueryParameterV1,
    RequestTemplateV1,
)
from ai_qa_copilot_api.test_normalization import (
    DuplicateCandidateGroupV1,
    TestNormalizationError as NormalizationError,
    group_duplicate_candidates,
    normalize_generated_test_case,
)


FIRST_TEST_ID = UUID("00000000-0000-0000-0000-000000000801")
SECOND_TEST_ID = UUID("00000000-0000-0000-0000-000000000802")
THIRD_TEST_ID = UUID("00000000-0000-0000-0000-000000000803")
FOURTH_TEST_ID = UUID("00000000-0000-0000-0000-000000000804")

FIRST_FINDING_ID = UUID("00000000-0000-0000-0000-000000000811")
SECOND_FINDING_ID = UUID("00000000-0000-0000-0000-000000000812")

FIRST_CITATION_ID = UUID("00000000-0000-0000-0000-000000000821")
SECOND_CITATION_ID = UUID("00000000-0000-0000-0000-000000000822")


def status_assertion(
    expected_status: int = 201,
) -> GeneratedAssertionV1:
    return GeneratedAssertionV1(
        target=AssertionTarget.STATUS_CODE,
        selector=None,
        operator=AssertionOperator.EQUALS,
        expected_value=expected_status,
    )


def response_header_assertion() -> GeneratedAssertionV1:
    return GeneratedAssertionV1(
        target=AssertionTarget.RESPONSE_HEADER,
        selector="Content-Type",
        operator=AssertionOperator.EXISTS,
        expected_value=None,
    )


def generated_test(
    *,
    test_id: UUID = FIRST_TEST_ID,
    title: str = "Create order returns HTTP 201",
    kind: GeneratedTestKind = GeneratedTestKind.POSITIVE,
    source_finding_id: UUID = FIRST_FINDING_ID,
    citation_ids: tuple[UUID, ...] = (FIRST_CITATION_ID,),
    path: str = "/orders",
    query: tuple[RequestQueryParameterV1, ...] = (),
    headers: tuple[RequestHeaderV1, ...] = (),
    json_body: dict[str, object] | None = None,
    assertions: tuple[GeneratedAssertionV1, ...] | None = None,
) -> GeneratedTestCaseV1:
    return GeneratedTestCaseV1(
        id=test_id,
        title=title,
        kind=kind,
        source_finding_id=source_finding_id,
        citation_ids=citation_ids,
        request=RequestTemplateV1(
            method=HttpMethod.POST,
            path=path,
            query=query,
            headers=headers,
            json_body={"quantity": 1} if json_body is None else json_body,
        ),
        assertions=(status_assertion(),) if assertions is None else assertions,
    )


def test_normalization_is_stable_and_does_not_change_the_input() -> None:
    test_case = generated_test(
        title="  CREATE   order returns HTTP 201  ",
        json_body={"quantity": 1, "priority": True},
    )

    normalized = normalize_generated_test_case(test_case)

    assert normalized.test_case_id == FIRST_TEST_ID
    assert normalized.normalized_title == "create order returns http 201"
    assert len(normalized.semantic_fingerprint) == 64
    assert test_case.title == "  CREATE   order returns HTTP 201  "
    assert test_case.request.json_body == {"quantity": 1, "priority": True}


def test_duplicate_candidates_ignore_title_and_provenance() -> None:
    first = generated_test(
        test_id=FIRST_TEST_ID,
        title="Create an order",
        source_finding_id=FIRST_FINDING_ID,
        citation_ids=(FIRST_CITATION_ID,),
    )
    second = generated_test(
        test_id=SECOND_TEST_ID,
        title="Order creation succeeds",
        source_finding_id=SECOND_FINDING_ID,
        citation_ids=(SECOND_CITATION_ID,),
    )

    groups = group_duplicate_candidates([first, second])

    assert len(groups) == 1
    assert groups[0].test_case_ids == (FIRST_TEST_ID, SECOND_TEST_ID)
    assert first.source_finding_id == FIRST_FINDING_ID
    assert second.source_finding_id == SECOND_FINDING_ID
    assert first.citation_ids == (FIRST_CITATION_ID,)
    assert second.citation_ids == (SECOND_CITATION_ID,)


def test_equivalent_request_and_assertion_ordering_is_grouped() -> None:
    first = generated_test(
        test_id=FIRST_TEST_ID,
        query=(
            RequestQueryParameterV1(name="include", value="summary"),
            RequestQueryParameterV1(name="locale", value="en"),
        ),
        headers=(
            RequestHeaderV1(name="Accept", value="application/json"),
            RequestHeaderV1(name="X-Client", value="test-suite"),
        ),
        json_body={"quantity": 1, "priority": True},
        assertions=(status_assertion(), response_header_assertion()),
    )
    second = generated_test(
        test_id=SECOND_TEST_ID,
        query=(
            RequestQueryParameterV1(name="locale", value="en"),
            RequestQueryParameterV1(name="include", value="summary"),
        ),
        headers=(
            RequestHeaderV1(name="x-client", value="test-suite"),
            RequestHeaderV1(name="accept", value="application/json"),
        ),
        json_body={"priority": True, "quantity": 1},
        assertions=(
            GeneratedAssertionV1(
                target=AssertionTarget.RESPONSE_HEADER,
                selector="content-type",
                operator=AssertionOperator.EXISTS,
                expected_value=None,
            ),
            status_assertion(),
        ),
    )

    groups = group_duplicate_candidates([first, second])

    assert groups[0].test_case_ids == (FIRST_TEST_ID, SECOND_TEST_ID)


def test_different_test_kinds_are_not_grouped() -> None:
    positive = generated_test(
        test_id=FIRST_TEST_ID,
        kind=GeneratedTestKind.POSITIVE,
    )
    negative = generated_test(
        test_id=SECOND_TEST_ID,
        kind=GeneratedTestKind.NEGATIVE,
    )

    assert group_duplicate_candidates([positive, negative]) == ()


@pytest.mark.parametrize(
    ("second_path", "second_status"),
    [
        ("/orders/{order_id}", 201),
        ("/orders", 400),
    ],
)
def test_different_observable_behavior_is_not_grouped(
    second_path: str,
    second_status: int,
) -> None:
    first = generated_test(test_id=FIRST_TEST_ID)
    second = generated_test(
        test_id=SECOND_TEST_ID,
        path=second_path,
        assertions=(status_assertion(second_status),),
    )

    assert group_duplicate_candidates([first, second]) == ()


def test_json_body_differences_are_not_grouped() -> None:
    first = generated_test(
        test_id=FIRST_TEST_ID,
        json_body={"quantity": 1},
    )
    second = generated_test(
        test_id=SECOND_TEST_ID,
        json_body={"quantity": 2},
    )

    assert group_duplicate_candidates([first, second]) == ()


def test_grouping_is_deterministic_regardless_of_input_order() -> None:
    first_group_first = generated_test(test_id=FIRST_TEST_ID)
    first_group_second = generated_test(test_id=SECOND_TEST_ID)
    second_group_first = generated_test(
        test_id=THIRD_TEST_ID,
        kind=GeneratedTestKind.NEGATIVE,
        assertions=(status_assertion(400),),
    )
    second_group_second = generated_test(
        test_id=FOURTH_TEST_ID,
        kind=GeneratedTestKind.NEGATIVE,
        assertions=(status_assertion(400),),
    )

    forward = group_duplicate_candidates(
        [
            first_group_first,
            first_group_second,
            second_group_first,
            second_group_second,
        ]
    )
    reverse = group_duplicate_candidates(
        [
            second_group_second,
            second_group_first,
            first_group_second,
            first_group_first,
        ]
    )

    assert forward == reverse
    assert all(isinstance(group, DuplicateCandidateGroupV1) for group in forward)
    assert {group.test_case_ids for group in forward} == {
        (FIRST_TEST_ID, SECOND_TEST_ID),
        (THIRD_TEST_ID, FOURTH_TEST_ID),
    }


def test_unique_test_cases_produce_no_duplicate_groups() -> None:
    first = generated_test(test_id=FIRST_TEST_ID)
    second = generated_test(
        test_id=SECOND_TEST_ID,
        path="/orders/{order_id}",
    )

    assert group_duplicate_candidates([first, second]) == ()


def test_duplicate_input_ids_are_rejected() -> None:
    first = generated_test(test_id=FIRST_TEST_ID)
    second = generated_test(
        test_id=FIRST_TEST_ID,
        path="/orders/{order_id}",
    )

    with pytest.raises(NormalizationError, match="IDs must be unique"):
        group_duplicate_candidates([first, second])
