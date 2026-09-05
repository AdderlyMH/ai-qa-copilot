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
    RequestTemplateV1,
)
from ai_qa_copilot_api.traceability import (
    OperationTestTraceLinkV1,
    OperationTraceSourceV1,
    RequirementTestTraceLinkV1,
    RequirementTraceSourceV1,
    TraceabilityLinkState,
    TraceabilityMatricesV1,
    TraceabilityRejected,
    build_traceability_matrices,
    operation_id_for_test_case,
    refresh_traceability_staleness,
)


FIRST_TEST_ID = UUID("00000000-0000-0000-0000-000000000901")
SECOND_TEST_ID = UUID("00000000-0000-0000-0000-000000000902")

FIRST_FINDING_ID = UUID("00000000-0000-0000-0000-000000000911")
SECOND_FINDING_ID = UUID("00000000-0000-0000-0000-000000000912")

FIRST_CITATION_ID = UUID("00000000-0000-0000-0000-000000000921")


def generated_test(
    *,
    test_id: UUID = FIRST_TEST_ID,
    finding_id: UUID = FIRST_FINDING_ID,
    method: HttpMethod = HttpMethod.POST,
    path: str = "/orders",
) -> GeneratedTestCaseV1:
    return GeneratedTestCaseV1(
        id=test_id,
        title="Generated traceability test",
        kind=GeneratedTestKind.CONTRACT,
        source_finding_id=finding_id,
        citation_ids=(FIRST_CITATION_ID,),
        request=RequestTemplateV1(
            method=method,
            path=path,
            query=(),
            headers=(),
            json_body=None,
        ),
        assertions=(
            GeneratedAssertionV1(
                target=AssertionTarget.STATUS_CODE,
                selector=None,
                operator=AssertionOperator.EQUALS,
                expected_value=200,
            ),
        ),
    )


def requirement_sources() -> tuple[RequirementTraceSourceV1, ...]:
    return (
        RequirementTraceSourceV1(
            source_finding_id=FIRST_FINDING_ID,
            requirement_id="REQ-ORDERS-001",
            revision="requirements-v1",
        ),
        RequirementTraceSourceV1(
            source_finding_id=SECOND_FINDING_ID,
            requirement_id="REQ-ORDERS-002",
            revision="requirements-v1",
        ),
    )


def operation_sources() -> tuple[OperationTraceSourceV1, ...]:
    return (
        OperationTraceSourceV1(
            operation_id="POST /orders",
            revision="openapi-v1",
        ),
        OperationTraceSourceV1(
            operation_id="GET /orders/{order_id}",
            revision="openapi-v1",
        ),
    )


def test_operation_identifier_matches_the_openapi_fact_format() -> None:
    test_case = generated_test(method=HttpMethod.POST, path="/orders")

    assert operation_id_for_test_case(test_case) == "POST /orders"


def test_builds_current_requirement_and_operation_matrices() -> None:
    test_case = generated_test()

    matrices = build_traceability_matrices(
        requirement_sources=requirement_sources(),
        operation_sources=operation_sources(),
        test_cases=[test_case],
    )

    assert matrices.requirement_test_links == (
        RequirementTestTraceLinkV1(
            source_finding_id=FIRST_FINDING_ID,
            requirement_id="REQ-ORDERS-001",
            source_revision="requirements-v1",
            test_case_id=FIRST_TEST_ID,
            state=TraceabilityLinkState.CURRENT,
        ),
    )
    assert matrices.operation_test_links == (
        OperationTestTraceLinkV1(
            operation_id="POST /orders",
            source_revision="openapi-v1",
            test_case_id=FIRST_TEST_ID,
            state=TraceabilityLinkState.CURRENT,
        ),
    )
    assert test_case.source_finding_id == FIRST_FINDING_ID
    assert test_case.request.path == "/orders"


def test_building_matrices_is_deterministic_regardless_of_input_order() -> None:
    first = generated_test(
        test_id=FIRST_TEST_ID,
        finding_id=FIRST_FINDING_ID,
        method=HttpMethod.POST,
        path="/orders",
    )
    second = generated_test(
        test_id=SECOND_TEST_ID,
        finding_id=SECOND_FINDING_ID,
        method=HttpMethod.GET,
        path="/orders/{order_id}",
    )

    forward = build_traceability_matrices(
        requirement_sources=requirement_sources(),
        operation_sources=operation_sources(),
        test_cases=[first, second],
    )
    reverse = build_traceability_matrices(
        requirement_sources=tuple(reversed(requirement_sources())),
        operation_sources=tuple(reversed(operation_sources())),
        test_cases=[second, first],
    )

    assert forward == reverse
    assert [link.requirement_id for link in forward.requirement_test_links] == [
        "REQ-ORDERS-001",
        "REQ-ORDERS-002",
    ]
    assert [link.operation_id for link in forward.operation_test_links] == [
        "GET /orders/{order_id}",
        "POST /orders",
    ]


def test_unmapped_sources_do_not_create_fabricated_links() -> None:
    test_case = generated_test(
        finding_id=FIRST_FINDING_ID,
        method=HttpMethod.POST,
        path="/orders",
    )

    matrices = build_traceability_matrices(
        requirement_sources=(),
        operation_sources=(),
        test_cases=[test_case],
    )

    assert matrices == TraceabilityMatricesV1(
        requirement_test_links=(),
        operation_test_links=(),
    )


def test_requirement_revision_marks_only_affected_link_stale() -> None:
    first = generated_test(
        test_id=FIRST_TEST_ID,
        finding_id=FIRST_FINDING_ID,
        method=HttpMethod.POST,
        path="/orders",
    )
    second = generated_test(
        test_id=SECOND_TEST_ID,
        finding_id=SECOND_FINDING_ID,
        method=HttpMethod.GET,
        path="/orders/{order_id}",
    )
    matrices = build_traceability_matrices(
        requirement_sources=requirement_sources(),
        operation_sources=operation_sources(),
        test_cases=[first, second],
    )

    refreshed = refresh_traceability_staleness(
        matrices=matrices,
        requirement_sources=(
            RequirementTraceSourceV1(
                source_finding_id=FIRST_FINDING_ID,
                requirement_id="REQ-ORDERS-001",
                revision="requirements-v2",
            ),
            requirement_sources()[1],
        ),
        operation_sources=operation_sources(),
    )

    assert [link.state for link in refreshed.requirement_test_links] == [
        TraceabilityLinkState.STALE,
        TraceabilityLinkState.CURRENT,
    ]
    assert all(
        link.state is TraceabilityLinkState.CURRENT
        for link in refreshed.operation_test_links
    )
    assert refreshed.requirement_test_links[0].source_revision == "requirements-v1"


def test_operation_revision_marks_only_affected_link_stale() -> None:
    first = generated_test(
        test_id=FIRST_TEST_ID,
        finding_id=FIRST_FINDING_ID,
        method=HttpMethod.POST,
        path="/orders",
    )
    second = generated_test(
        test_id=SECOND_TEST_ID,
        finding_id=SECOND_FINDING_ID,
        method=HttpMethod.GET,
        path="/orders/{order_id}",
    )
    matrices = build_traceability_matrices(
        requirement_sources=requirement_sources(),
        operation_sources=operation_sources(),
        test_cases=[first, second],
    )

    refreshed = refresh_traceability_staleness(
        matrices=matrices,
        requirement_sources=requirement_sources(),
        operation_sources=(
            OperationTraceSourceV1(
                operation_id="POST /orders",
                revision="openapi-v2",
            ),
            operation_sources()[1],
        ),
    )

    assert [link.state for link in refreshed.operation_test_links] == [
        TraceabilityLinkState.CURRENT,
        TraceabilityLinkState.STALE,
    ]
    assert all(
        link.state is TraceabilityLinkState.CURRENT
        for link in refreshed.requirement_test_links
    )
    assert refreshed.operation_test_links[1].source_revision == "openapi-v1"


def test_missing_source_marks_existing_link_stale_without_removing_it() -> None:
    matrices = build_traceability_matrices(
        requirement_sources=requirement_sources(),
        operation_sources=operation_sources(),
        test_cases=[generated_test()],
    )

    refreshed = refresh_traceability_staleness(
        matrices=matrices,
        requirement_sources=(),
        operation_sources=(),
    )

    assert len(refreshed.requirement_test_links) == 1
    assert len(refreshed.operation_test_links) == 1
    assert refreshed.requirement_test_links[0].state is TraceabilityLinkState.STALE
    assert refreshed.operation_test_links[0].state is TraceabilityLinkState.STALE


def test_matching_current_revisions_keep_links_current() -> None:
    matrices = build_traceability_matrices(
        requirement_sources=requirement_sources(),
        operation_sources=operation_sources(),
        test_cases=[generated_test()],
    )

    refreshed = refresh_traceability_staleness(
        matrices=matrices,
        requirement_sources=requirement_sources(),
        operation_sources=operation_sources(),
    )

    assert refreshed == matrices


def test_duplicate_requirement_source_finding_ids_are_rejected() -> None:
    duplicate_sources = (
        RequirementTraceSourceV1(
            source_finding_id=FIRST_FINDING_ID,
            requirement_id="REQ-ORDERS-001",
            revision="requirements-v1",
        ),
        RequirementTraceSourceV1(
            source_finding_id=FIRST_FINDING_ID,
            requirement_id="REQ-ORDERS-002",
            revision="requirements-v1",
        ),
    )

    with pytest.raises(TraceabilityRejected, match="finding IDs must be unique"):
        build_traceability_matrices(
            requirement_sources=duplicate_sources,
            operation_sources=(),
            test_cases=[],
        )


def test_duplicate_operation_sources_and_test_ids_are_rejected() -> None:
    duplicate_operations = (
        OperationTraceSourceV1(
            operation_id="POST /orders",
            revision="openapi-v1",
        ),
        OperationTraceSourceV1(
            operation_id="POST /orders",
            revision="openapi-v2",
        ),
    )

    with pytest.raises(
        TraceabilityRejected, match="Operation identifiers must be unique"
    ):
        build_traceability_matrices(
            requirement_sources=(),
            operation_sources=duplicate_operations,
            test_cases=[],
        )

    with pytest.raises(TraceabilityRejected, match="test case IDs must be unique"):
        build_traceability_matrices(
            requirement_sources=(),
            operation_sources=(),
            test_cases=[
                generated_test(test_id=FIRST_TEST_ID),
                generated_test(test_id=FIRST_TEST_ID, path="/orders/{order_id}"),
            ],
        )


def test_duplicate_matrix_links_are_rejected_during_staleness_refresh() -> None:
    link = RequirementTestTraceLinkV1(
        source_finding_id=FIRST_FINDING_ID,
        requirement_id="REQ-ORDERS-001",
        source_revision="requirements-v1",
        test_case_id=FIRST_TEST_ID,
        state=TraceabilityLinkState.CURRENT,
    )
    matrices = TraceabilityMatricesV1(
        requirement_test_links=(link, link),
        operation_test_links=(),
    )

    with pytest.raises(TraceabilityRejected, match="links must be unique"):
        refresh_traceability_staleness(
            matrices=matrices,
            requirement_sources=requirement_sources(),
            operation_sources=operation_sources(),
        )
