from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.engine import Engine

from ai_qa_copilot_api.auth import (
    CognitoOwnerPrincipal,
    LocalDevelopmentOwnerPrincipal,
)
from ai_qa_copilot_api.execution_approvals import (
    EXECUTION_APPROVAL_TTL,
    ExecutionApprovalConflict,
    ExecutionApprovalRejected,
    ExecutionApprovalService,
    ExecutionApprovalUnavailable,
    SqlAlchemyExecutionApprovalRepository,
    UnavailableExecutionApprovalRepository,
)
from ai_qa_copilot_api.execution_plans import (
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
    RequestTemplateV1,
)
from ai_qa_copilot_api.projects import Base
from ai_qa_copilot_api.documents import (
    ExecutionJobState,
    ExecutionResultOutcome,
)
from ai_qa_copilot_api.execution_results import (
    ExecutionResultPayload,
    ExecutionResultRejected,
    SqlAlchemyExecutionResultRepository,
)
from ai_qa_copilot_api.execution_jobs import SqlAlchemyExecutionJobQueue


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000801")


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def plan(*, quantity: int = 2) -> ExecutionPlanV1:
    test_case = GeneratedTestCaseV1(
        id=UUID("00000000-0000-0000-0000-000000000802"),
        title="Create a synthetic order",
        kind=GeneratedTestKind.POSITIVE,
        source_finding_id=UUID("00000000-0000-0000-0000-000000000803"),
        citation_ids=(UUID("00000000-0000-0000-0000-000000000804"),),
        request=RequestTemplateV1(
            method=HttpMethod.POST,
            path="/orders",
            query=(),
            headers=(),
            json_body={"quantity": quantity},
        ),
        assertions=(
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
    )


def repository(
    tmp_path: Path,
    clock: MutableClock,
) -> tuple[SqlAlchemyExecutionApprovalRepository, Engine]:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'execution-approvals.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    return SqlAlchemyExecutionApprovalRepository(sessions, clock=clock), engine


def service(
    tmp_path: Path,
    clock: MutableClock,
) -> tuple[
    ExecutionApprovalService,
    SqlAlchemyExecutionApprovalRepository,
    Engine,
]:
    approval_repository, engine = repository(tmp_path, clock)
    return (
        ExecutionApprovalService(approval_repository),
        approval_repository,
        engine,
    )


def job_queue(
    engine: Engine,
    clock: MutableClock,
) -> SqlAlchemyExecutionJobQueue:
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    return SqlAlchemyExecutionJobQueue(sessions, clock=clock)


def result_repository(
    engine: Engine,
    clock: MutableClock,
) -> SqlAlchemyExecutionResultRepository:
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    return SqlAlchemyExecutionResultRepository(sessions, clock=clock)


def test_missing_approval_cannot_be_claimed(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    _, approval_repository, engine = service(tmp_path, clock)
    immutable_plan = plan()

    try:
        assert (
            approval_repository.consume(
                project_id=PROJECT_ID,
                plan_id=immutable_plan.id,
                plan_hash=immutable_plan.plan_hash,
            )
            is None
        )
    finally:
        engine.dispose()


def test_expired_approval_cannot_be_claimed(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, approval_repository, engine = service(tmp_path, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )

        clock.current = approval.expires_at

        assert (
            approval_repository.consume(
                project_id=PROJECT_ID,
                plan_id=immutable_plan.id,
                plan_hash=immutable_plan.plan_hash,
            )
            is None
        )
    finally:
        engine.dispose()


def test_altered_plan_or_hash_is_rejected_before_persistence(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, approval_repository, engine = service(tmp_path, clock)
    immutable_plan = plan()

    try:
        with pytest.raises(
            ExecutionApprovalRejected,
            match="Expected plan hash does not match",
        ):
            approval_service.approve(
                project_id=PROJECT_ID,
                plan=immutable_plan,
                expected_plan_hash="0" * 64,
                approver=LocalDevelopmentOwnerPrincipal(),
                comment=None,
            )

        with pytest.raises(ExecutionApprovalRejected):
            approval_service.approve(
                project_id=PROJECT_ID,
                plan=replace(immutable_plan, plan_hash="f" * 64),
                expected_plan_hash=immutable_plan.plan_hash,
                approver=LocalDevelopmentOwnerPrincipal(),
                comment=None,
            )

        assert (
            approval_repository.consume(
                project_id=PROJECT_ID,
                plan_id=immutable_plan.id,
                plan_hash=immutable_plan.plan_hash,
            )
            is None
        )
    finally:
        engine.dispose()


def test_approval_is_consumed_once_and_replay_fails(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, approval_repository, engine = service(tmp_path, clock)
    immutable_plan = plan()

    try:
        approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment="Approved for a future restricted worker.",
        )

        first = approval_repository.consume(
            project_id=PROJECT_ID,
            plan_id=immutable_plan.id,
            plan_hash=immutable_plan.plan_hash,
        )
        replay = approval_repository.consume(
            project_id=PROJECT_ID,
            plan_id=immutable_plan.id,
            plan_hash=immutable_plan.plan_hash,
        )

        assert first is not None
        assert first.consumed_at == clock.current
        assert replay is None
    finally:
        engine.dispose()


def test_concurrent_claims_produce_exactly_one_success(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, approval_repository, engine = service(tmp_path, clock)
    immutable_plan = plan()
    gate = Barrier(2)

    try:
        approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )

        def claim() -> object:
            gate.wait()
            return approval_repository.consume(
                project_id=PROJECT_ID,
                plan_id=immutable_plan.id,
                plan_hash=immutable_plan.plan_hash,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: claim(), range(2)))

        assert sum(result is not None for result in results) == 1
    finally:
        engine.dispose()


def test_duplicate_concurrent_approvals_create_at_most_one_record(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    immutable_plan = plan()
    gate = Barrier(2)

    try:

        def approve() -> object:
            gate.wait()
            try:
                return approval_service.approve(
                    project_id=PROJECT_ID,
                    plan=immutable_plan,
                    expected_plan_hash=immutable_plan.plan_hash,
                    approver=LocalDevelopmentOwnerPrincipal(),
                    comment=None,
                )
            except ExecutionApprovalConflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: approve(), range(2)))

        assert sum(result is not None for result in results) == 1
    finally:
        engine.dispose()


def test_cognito_approver_identity_is_derived_from_the_server_principal(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=CognitoOwnerPrincipal(
                issuer="https://cognito-idp.example.com/example",
                subject="owner-subject",
            ),
            comment=None,
        )

        assert (
            approval.approver_id
            == "https://cognito-idp.example.com/example|owner-subject"
        )
        assert approval.approver_authentication_source == "cognito"
    finally:
        engine.dispose()


def test_unavailable_persistence_fails_closed() -> None:
    immutable_plan = plan()
    approval_service = ExecutionApprovalService(
        UnavailableExecutionApprovalRepository()
    )

    with pytest.raises(ExecutionApprovalUnavailable):
        approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )

    with pytest.raises(ExecutionApprovalUnavailable):
        approval_service.consume(
            project_id=PROJECT_ID,
            plan_id=immutable_plan.id,
            plan_hash=immutable_plan.plan_hash,
        )

    with pytest.raises(ExecutionApprovalUnavailable):
        approval_service.get(
            project_id=PROJECT_ID,
            approval_id=UUID("00000000-0000-0000-0000-000000000998"),
        )


def test_approval_expiry_is_server_derived(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )

        assert approval.approved_at == clock.current
        assert approval.expires_at == clock.current + timedelta(minutes=10)
        assert approval.expires_at - approval.approved_at == EXECUTION_APPROVAL_TTL
        assert approval.consumed_at is None
    finally:
        engine.dispose()


def test_execution_job_is_idempotently_bound_to_one_unconsumed_approval(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    queue = job_queue(engine, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )

        created = queue.enqueue(approval=approval)
        repeated = queue.enqueue(approval=approval)

        assert repeated == created
        assert created.project_id == PROJECT_ID
        assert created.execution_approval_id == approval.id
        assert created.plan_id == immutable_plan.id
        assert created.plan_hash == immutable_plan.plan_hash
        assert created.state is ExecutionJobState.QUEUED
        assert created.started_at is None
        assert created.finished_at is None
        assert created.cancelled_at is None
    finally:
        engine.dispose()


def test_execution_job_claim_consumes_the_matching_approval_atomically(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    queue = job_queue(engine, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)

        claimed = queue.claim_next()

        assert claimed is not None
        assert claimed.job.id == queued.id
        assert claimed.job.state is ExecutionJobState.RUNNING
        assert claimed.job.started_at == clock.current
        assert claimed.approval.id == approval.id
        assert claimed.approval.consumed_at == clock.current
        assert queue.claim_next() is None
    finally:
        engine.dispose()


def test_expired_execution_job_fails_before_any_future_transport(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    queue = job_queue(engine, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)
        clock.current = approval.expires_at

        assert queue.claim_next() is None

        failed = queue.get(project_id=PROJECT_ID, job_id=queued.id)
        assert failed is not None
        assert failed.state is ExecutionJobState.FAILED
        assert failed.started_at == clock.current
        assert failed.finished_at == clock.current
    finally:
        engine.dispose()


def test_queued_execution_job_can_be_cancelled_without_consuming_approval(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    queue = job_queue(engine, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)

        cancelled = queue.cancel(project_id=PROJECT_ID, job_id=queued.id)

        assert cancelled is not None
        assert cancelled.state is ExecutionJobState.CANCELLED
        assert cancelled.cancel_requested_at == clock.current
        assert cancelled.cancelled_at == clock.current
        assert queue.claim_next() is None
    finally:
        engine.dispose()


def execution_result_payload(
    *,
    outcome: ExecutionResultOutcome,
    failure_code: str | None,
    transport_send_count: int = 1,
    request_evidence_json: str | None = (
        '{"headers":[],"method":"POST","url":"https://example.test/api/orders"}'
    ),
    response_evidence_json: str | None = (
        '{"body_bytes":24,"headers":[],"status_code":201}'
    ),
) -> ExecutionResultPayload:
    return ExecutionResultPayload(
        outcome=outcome,
        failure_code=failure_code,
        assertion_results_json='[{"passed":true,"target":"status_code"}]',
        request_evidence_json=request_evidence_json,
        response_evidence_json=response_evidence_json,
        transport_send_count=transport_send_count,
    )


def test_execution_result_atomically_finishes_claimed_job_and_is_idempotent(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    queue = job_queue(engine, clock)
    results = result_repository(engine, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)
        claimed = queue.claim_next()
        assert claimed is not None

        payload = execution_result_payload(
            outcome=ExecutionResultOutcome.SUCCEEDED,
            failure_code=None,
        )
        stored = results.record(
            project_id=PROJECT_ID,
            job_id=claimed.job.id,
            payload=payload,
        )
        repeated = results.record(
            project_id=PROJECT_ID,
            job_id=claimed.job.id,
            payload=payload,
        )

        assert repeated == stored
        assert stored.execution_job_id == queued.id
        assert stored.outcome is ExecutionResultOutcome.SUCCEEDED
        assert stored.failure_code is None
        assert stored.recorded_at == clock.current

        finished = queue.get(project_id=PROJECT_ID, job_id=queued.id)
        assert finished is not None
        assert finished.state is ExecutionJobState.SUCCEEDED
        assert finished.finished_at == clock.current
        assert finished.cancelled_at is None
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("outcome", "failure_code", "expected_state"),
    [
        (
            ExecutionResultOutcome.FAILED,
            "assertions_failed",
            ExecutionJobState.FAILED,
        ),
        (
            ExecutionResultOutcome.CANCELLED,
            "cancelled",
            ExecutionJobState.CANCELLED,
        ),
    ],
)
def test_execution_result_records_each_non_success_terminal_state(
    tmp_path: Path,
    outcome: ExecutionResultOutcome,
    failure_code: str,
    expected_state: ExecutionJobState,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    queue = job_queue(engine, clock)
    results = result_repository(engine, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)
        claimed = queue.claim_next()
        assert claimed is not None

        stored = results.record(
            project_id=PROJECT_ID,
            job_id=claimed.job.id,
            payload=execution_result_payload(
                outcome=outcome,
                failure_code=failure_code,
                transport_send_count=0,
            ),
        )

        assert stored.outcome is outcome
        assert stored.failure_code == failure_code

        finished = queue.get(project_id=PROJECT_ID, job_id=queued.id)
        assert finished is not None
        assert finished.state is expected_state

        if outcome is ExecutionResultOutcome.CANCELLED:
            assert finished.finished_at is None
            assert finished.cancel_requested_at == clock.current
            assert finished.cancelled_at == clock.current
        else:
            assert finished.finished_at == clock.current
            assert finished.cancelled_at is None
    finally:
        engine.dispose()


def test_execution_result_rejects_conflicting_or_unredacted_evidence(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    queue = job_queue(engine, clock)
    results = result_repository(engine, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )
        queued = queue.enqueue(approval=approval)
        claimed = queue.claim_next()
        assert claimed is not None

        with pytest.raises(ExecutionResultRejected):
            results.record(
                project_id=PROJECT_ID,
                job_id=claimed.job.id,
                payload=execution_result_payload(
                    outcome=ExecutionResultOutcome.FAILED,
                    failure_code="transport_error",
                    request_evidence_json=(
                        '{"headers":[["Authorization","Bearer secret-value"]]}'
                    ),
                ),
            )

        running = queue.get(project_id=PROJECT_ID, job_id=queued.id)
        assert running is not None
        assert running.state is ExecutionJobState.RUNNING

        results.record(
            project_id=PROJECT_ID,
            job_id=claimed.job.id,
            payload=execution_result_payload(
                outcome=ExecutionResultOutcome.FAILED,
                failure_code="assertions_failed",
            ),
        )

        with pytest.raises(ExecutionResultRejected):
            results.record(
                project_id=PROJECT_ID,
                job_id=claimed.job.id,
                payload=execution_result_payload(
                    outcome=ExecutionResultOutcome.SUCCEEDED,
                    failure_code=None,
                ),
            )
    finally:
        engine.dispose()


def test_approval_lookup_is_project_scoped_and_preserves_immutable_snapshot(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 9, 7, tzinfo=timezone.utc))
    approval_service, _, engine = service(tmp_path, clock)
    immutable_plan = plan()

    try:
        approval = approval_service.approve(
            project_id=PROJECT_ID,
            plan=immutable_plan,
            expected_plan_hash=immutable_plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment=None,
        )

        assert (
            approval_service.get(
                project_id=PROJECT_ID,
                approval_id=approval.id,
            )
            == approval
        )
        assert (
            approval_service.get(
                project_id=UUID("00000000-0000-0000-0000-000000000999"),
                approval_id=approval.id,
            )
            is None
        )
    finally:
        engine.dispose()
