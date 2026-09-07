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
