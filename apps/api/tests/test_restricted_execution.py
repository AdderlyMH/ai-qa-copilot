from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
from uuid import UUID

import pytest

from ai_qa_copilot_api.execution_approvals import ExecutionApproval
from ai_qa_copilot_api.documents import ExecutionJobState
from ai_qa_copilot_api.execution_jobs import ClaimedExecutionJob, ExecutionJob
from ai_qa_copilot_api.execution_plans import (
    ExecutionLimitsV1,
    ExecutionPlanV1,
    build_execution_plan,
)
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
from ai_qa_copilot_api.restricted_execution import (
    ExecutionFailureCode,
    ExecutionOutcome,
    RestrictedExecutionExecutor,
    TransportResponse,
)


NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000901")
APPROVAL_ID = UUID("00000000-0000-0000-0000-000000000902")
JOB_ID = UUID("00000000-0000-0000-0000-000000000903")


@dataclass
class FakeResolver:
    answers: tuple[tuple[str, ...], ...]
    calls: int = 0

    def resolve(self, hostname: str) -> tuple[str, ...]:
        assert hostname == "ai-qa-sandbox.onrender.com"
        answer = self.answers[self.calls]
        self.calls += 1
        return answer


@dataclass
class FakeTransport:
    response: TransportResponse | None = None
    error: Exception | None = None
    sends: int = 0
    requests: list[
        tuple[
            HttpMethod,
            str,
            tuple[tuple[str, str], ...],
            bytes | None,
            int,
            int,
            bool,
            str,
        ]
    ] = field(default_factory=list)

    def send(
        self,
        *,
        method: HttpMethod,
        url: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes | None,
        timeout_ms: int,
        max_response_bytes: int,
        follow_redirects: bool,
        resolved_address: str,
    ) -> TransportResponse:
        self.sends += 1
        self.requests.append(
            (
                method,
                url,
                headers,
                body,
                timeout_ms,
                max_response_bytes,
                follow_redirects,
                resolved_address,
            )
        )
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@dataclass
class SequenceCancellationProbe:
    answers: tuple[bool, ...]
    calls: int = 0

    def is_cancel_requested(self, job_id: UUID) -> bool:
        assert job_id == JOB_ID
        answer = self.answers[self.calls] if self.calls < len(self.answers) else False
        self.calls += 1
        return answer


def response(
    *,
    status_code: int = 201,
    headers: tuple[tuple[str, str], ...] = (("Content-Type", "application/json"),),
    body: bytes = b'{"id":"order-1","state":"created"}',
    elapsed_ms: int = 25,
) -> TransportResponse:
    return TransportResponse(
        status_code=status_code,
        headers=headers,
        body=body,
        elapsed_ms=elapsed_ms,
    )


def plan(
    *,
    headers: tuple[RequestHeaderV1, ...] = (),
    query: tuple[RequestQueryParameterV1, ...] = (),
    assertions: tuple[GeneratedAssertionV1, ...] | None = None,
    limits: ExecutionLimitsV1 | None = None,
    json_body: dict[str, object] | None = None,
) -> ExecutionPlanV1:
    test_case = GeneratedTestCaseV1(
        id=UUID("00000000-0000-0000-0000-000000000904"),
        title="Create synthetic order",
        kind=GeneratedTestKind.POSITIVE,
        source_finding_id=UUID("00000000-0000-0000-0000-000000000905"),
        citation_ids=(UUID("00000000-0000-0000-0000-000000000906"),),
        request=RequestTemplateV1(
            method=HttpMethod.POST,
            path="/orders",
            query=query,
            headers=headers,
            json_body={"quantity": 2} if json_body is None else json_body,
        ),
        assertions=assertions
        or (
            GeneratedAssertionV1(
                target=AssertionTarget.STATUS_CODE,
                selector=None,
                operator=AssertionOperator.EQUALS,
                expected_value=201,
            ),
        ),
    )
    return build_execution_plan(
        generated_test_case=test_case,
        target_id="synthetic-order-api",
        limits=limits
        or ExecutionLimitsV1(
            request_timeout_ms=500,
            max_request_body_bytes=1_000,
            max_response_bytes=1_000,
            max_assertions=20,
        ),
    )


def claimed(
    *,
    immutable_plan: ExecutionPlanV1 | None = None,
    approval: ExecutionApproval | None = None,
    job: ExecutionJob | None = None,
) -> ClaimedExecutionJob:
    immutable_plan = immutable_plan or plan()
    approval = approval or ExecutionApproval(
        id=APPROVAL_ID,
        project_id=PROJECT_ID,
        plan=immutable_plan,
        approver_id="local-development-owner",
        approver_authentication_source="local_bypass",
        comment=None,
        approved_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        consumed_at=NOW,
    )
    job = job or ExecutionJob(
        id=JOB_ID,
        project_id=PROJECT_ID,
        execution_approval_id=approval.id,
        plan_id=immutable_plan.id,
        plan_hash=immutable_plan.plan_hash,
        state=ExecutionJobState.RUNNING,
        created_at=NOW,
        started_at=NOW,
        finished_at=None,
        cancel_requested_at=None,
        cancelled_at=None,
    )
    return ClaimedExecutionJob(job=job, approval=approval)


def executor(
    *,
    resolver: FakeResolver,
    transport: FakeTransport,
    cancellation: SequenceCancellationProbe | None = None,
    current: datetime = NOW,
) -> RestrictedExecutionExecutor:
    return RestrictedExecutionExecutor(
        resolver=resolver,
        transport=transport,
        cancellation_probe=cancellation,
        clock=lambda: current,
    )


def test_valid_claim_sends_one_exact_bounded_request_with_redirects_disabled() -> None:
    immutable_plan = plan(
        query=(RequestQueryParameterV1(name="source", value="qa"),),
    )
    transport = FakeTransport(response=response())

    result = executor(
        resolver=FakeResolver((("8.8.8.8",), ("8.8.8.8",))),
        transport=transport,
    ).execute(claimed(immutable_plan=immutable_plan))

    assert result.outcome is ExecutionOutcome.SUCCEEDED
    assert result.transport_send_count == 1
    assert transport.sends == 1
    assert transport.requests == [
        (
            HttpMethod.POST,
            "https://ai-qa-sandbox.onrender.com/orders?source=qa",
            (),
            b'{"quantity":2}',
            500,
            1_000,
            False,
            "8.8.8.8",
        )
    ]


@pytest.mark.parametrize(
    ("answers", "calls"),
    [
        ((("127.0.0.1",),), 1),
        ((("8.8.8.8",), ("169.254.169.254",)), 2),
    ],
)
def test_private_dns_answers_and_rebinding_never_reach_transport(
    answers: tuple[tuple[str, ...], ...],
    calls: int,
) -> None:
    resolver = FakeResolver(answers)
    transport = FakeTransport(response=response())

    result = executor(resolver=resolver, transport=transport).execute(claimed())

    assert result.outcome is ExecutionOutcome.FAILED
    assert result.error_code is ExecutionFailureCode.TARGET_DENIED
    assert resolver.calls == calls
    assert transport.sends == 0


@pytest.mark.parametrize(
    "claim,current",
    [
        (lambda value: claimed(approval=replace(value, expires_at=NOW)), NOW),
        (
            lambda value: claimed(
                approval=replace(value, plan=replace(value.plan, plan_hash="0" * 64))
            ),
            NOW,
        ),
        (lambda value: claimed(approval=replace(value, consumed_at=None)), NOW),
    ],
)
def test_expired_mutated_or_replayed_approval_never_reaches_transport(
    claim: Callable[[ExecutionApproval], ClaimedExecutionJob],
    current: datetime,
) -> None:
    initial = claimed().approval
    transport = FakeTransport(response=response())

    result = executor(
        resolver=FakeResolver((("8.8.8.8",), ("8.8.8.8",))),
        transport=transport,
        current=current,
    ).execute(claim(initial))

    assert result.outcome is ExecutionOutcome.FAILED
    assert transport.sends == 0


def test_cancellation_before_send_makes_no_transport_request() -> None:
    transport = FakeTransport(response=response())
    cancellation = SequenceCancellationProbe((False, True))

    result = executor(
        resolver=FakeResolver((("8.8.8.8",), ("8.8.8.8",))),
        transport=transport,
        cancellation=cancellation,
    ).execute(claimed())

    assert result.outcome is ExecutionOutcome.CANCELLED
    assert result.error_code is ExecutionFailureCode.CANCELLED
    assert transport.sends == 0
    assert cancellation.calls == 2


@pytest.mark.parametrize(
    ("transport", "immutable_plan", "expected_code", "sends"),
    [
        (
            FakeTransport(response=response(body=b"x" * 1_001)),
            plan(),
            ExecutionFailureCode.RESPONSE_TOO_LARGE,
            1,
        ),
        (
            FakeTransport(response=response(status_code=302)),
            plan(),
            ExecutionFailureCode.REDIRECT_RESPONSE,
            1,
        ),
        (
            FakeTransport(error=TimeoutError()),
            plan(),
            ExecutionFailureCode.TRANSPORT_TIMEOUT,
            1,
        ),
        (
            FakeTransport(response=response(body=b"not-json")),
            plan(
                assertions=(
                    GeneratedAssertionV1(
                        target=AssertionTarget.JSON_BODY,
                        selector="/id",
                        operator=AssertionOperator.EQUALS,
                        expected_value="order-1",
                    ),
                )
            ),
            ExecutionFailureCode.ASSERTIONS_FAILED,
            1,
        ),
        (
            FakeTransport(response=response()),
            plan(headers=(RequestHeaderV1(name="X-Trace", value="safe"),)),
            ExecutionFailureCode.PLAN_INVALID,
            0,
        ),
    ],
)
def test_failures_are_fail_closed_and_never_retried(
    transport: FakeTransport,
    immutable_plan: ExecutionPlanV1,
    expected_code: ExecutionFailureCode,
    sends: int,
) -> None:
    claim = claimed(immutable_plan=immutable_plan)
    if sends == 0:
        claim = replace(
            claim,
            approval=replace(
                claim.approval,
                plan=replace(
                    claim.approval.plan,
                    test_case_payload=json.dumps(
                        {
                            **json.loads(claim.approval.plan.test_case_payload),
                            "request": {
                                **json.loads(claim.approval.plan.test_case_payload)[
                                    "request"
                                ],
                                "headers": [
                                    {"name": "Authorization", "value": "secret"}
                                ],
                            },
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                ),
            ),
        )

    result = executor(
        resolver=FakeResolver((("8.8.8.8",), ("8.8.8.8",))),
        transport=transport,
    ).execute(claim)

    assert result.outcome is ExecutionOutcome.FAILED
    assert result.error_code is expected_code
    assert result.transport_send_count == sends
    assert transport.sends == sends


def test_sensitive_header_json_and_query_values_are_redacted_from_evidence() -> None:
    immutable_plan = plan(
        headers=(RequestHeaderV1(name="X-Api-Token", value="request-token"),),
        query=(RequestQueryParameterV1(name="token", value="query-token"),),
        json_body={"password": "request-password", "quantity": 2},
    )
    transport = FakeTransport(
        response=response(
            headers=(("Authorization", "response-token"),),
            body=b'{"token":"response-token","id":"order-1"}',
        )
    )

    result = executor(
        resolver=FakeResolver((("8.8.8.8",), ("8.8.8.8",))),
        transport=transport,
    ).execute(claimed(immutable_plan=immutable_plan))

    rendered = repr(result)
    for secret in (
        "request-token",
        "query-token",
        "request-password",
        "response-token",
    ):
        assert secret not in rendered


def test_allowlisted_assertion_operators_are_evaluated_deterministically() -> None:
    immutable_plan = plan(
        assertions=(
            GeneratedAssertionV1(
                target=AssertionTarget.STATUS_CODE,
                selector=None,
                operator=AssertionOperator.EQUALS,
                expected_value=201,
            ),
            GeneratedAssertionV1(
                target=AssertionTarget.RESPONSE_HEADER,
                selector="X-Request-Id",
                operator=AssertionOperator.EXISTS,
                expected_value=None,
            ),
            GeneratedAssertionV1(
                target=AssertionTarget.JSON_BODY,
                selector="/state",
                operator=AssertionOperator.CONTAINS,
                expected_value="creat",
            ),
            GeneratedAssertionV1(
                target=AssertionTarget.RESPONSE_TIME_MS,
                selector=None,
                operator=AssertionOperator.LESS_THAN_OR_EQUAL,
                expected_value=25,
            ),
        )
    )
    transport = FakeTransport(
        response=response(headers=(("X-Request-Id", "request-1"),))
    )

    result = executor(
        resolver=FakeResolver((("8.8.8.8",), ("8.8.8.8",))),
        transport=transport,
    ).execute(claimed(immutable_plan=immutable_plan))

    assert result.outcome is ExecutionOutcome.SUCCEEDED
    assert [assertion.passed for assertion in result.assertion_results] == [
        True,
        True,
        True,
        True,
    ]
