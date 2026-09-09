"""Durable, one-time approvals bound to immutable execution plans."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
import json
import os
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.auth import (
    CognitoOwnerPrincipal,
    LocalDevelopmentOwnerPrincipal,
    OwnerPrincipal,
)
from ai_qa_copilot_api.documents import ExecutionApprovalRecord
from ai_qa_copilot_api.execution_plans import (
    ExecutionEstimateV1,
    ExecutionLimitsV1,
    ExecutionPlanRejected,
    ExecutionPlanV1,
    validate_execution_plan,
)
from ai_qa_copilot_api.target_registry import TargetId


EXECUTION_APPROVAL_TTL = timedelta(minutes=10)
MAX_EXECUTION_APPROVAL_COMMENT_LENGTH = 1_000
LOCAL_DEVELOPMENT_APPROVER_ID = "local-development-owner"


class ExecutionApprovalUnavailable(RuntimeError):
    """Raised when durable approval state cannot be safely read or written."""


class ExecutionApprovalRejected(ValueError):
    """Raised when an approval request violates the immutable-plan contract."""


class ExecutionApprovalConflict(ValueError):
    """Raised when an immutable plan already has a durable approval."""


@dataclass(frozen=True)
class ExecutionApproval:
    """One server-derived, expiring, one-time approval."""

    id: UUID
    project_id: UUID
    plan: ExecutionPlanV1
    approver_id: str
    approver_authentication_source: str
    comment: str | None
    approved_at: datetime
    expires_at: datetime
    consumed_at: datetime | None


class ExecutionApprovalRepository(Protocol):
    """Durable boundary for approval creation and atomic one-time consumption."""

    def create(
        self,
        *,
        project_id: UUID,
        plan: ExecutionPlanV1,
        approver_id: str,
        approver_authentication_source: str,
        comment: str | None,
    ) -> ExecutionApproval: ...

    def get(
        self,
        *,
        project_id: UUID,
        approval_id: UUID,
    ) -> ExecutionApproval | None: ...

    def consume(
        self,
        *,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
    ) -> ExecutionApproval | None: ...


class UnavailableExecutionApprovalRepository:
    """Fail closed until durable approval storage is explicitly configured."""

    def create(
        self,
        *,
        project_id: UUID,
        plan: ExecutionPlanV1,
        approver_id: str,
        approver_authentication_source: str,
        comment: str | None,
    ) -> ExecutionApproval:
        del project_id, plan, approver_id, approver_authentication_source, comment
        raise ExecutionApprovalUnavailable

    def get(
        self,
        *,
        project_id: UUID,
        approval_id: UUID,
    ) -> ExecutionApproval | None:
        del project_id, approval_id
        raise ExecutionApprovalUnavailable

    def consume(
        self,
        *,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
    ) -> ExecutionApproval | None:
        del project_id, plan_id, plan_hash
        raise ExecutionApprovalUnavailable


class SqlAlchemyExecutionApprovalRepository:
    """Persist approvals and atomically consume each valid approval at most once."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
    ) -> SqlAlchemyExecutionApprovalRepository:
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def create(
        self,
        *,
        project_id: UUID,
        plan: ExecutionPlanV1,
        approver_id: str,
        approver_authentication_source: str,
        comment: str | None,
    ) -> ExecutionApproval:
        approved_at = _utc_datetime(self._clock())
        record = ExecutionApprovalRecord(
            id=self._id_factory(),
            project_id=project_id,
            plan_id=plan.id,
            plan_hash=plan.plan_hash,
            plan_snapshot=_plan_snapshot(plan),
            approver_id=approver_id,
            approver_authentication_source=approver_authentication_source,
            comment=comment,
            approved_at=approved_at,
            expires_at=approved_at + EXECUTION_APPROVAL_TTL,
            consumed_at=None,
        )

        try:
            with self._session_factory.begin() as session:
                session.add(record)
        except IntegrityError as error:
            raise ExecutionApprovalConflict(
                "An approval already exists for this immutable plan"
            ) from error
        except SQLAlchemyError as error:
            raise ExecutionApprovalUnavailable from error

        return _approval_from_record(record)

    def get(
        self,
        *,
        project_id: UUID,
        approval_id: UUID,
    ) -> ExecutionApproval | None:
        """Return one immutable approval only within its owning project."""

        try:
            with self._session_factory() as session:
                record = session.execute(
                    select(ExecutionApprovalRecord).where(
                        ExecutionApprovalRecord.id == approval_id,
                        ExecutionApprovalRecord.project_id == project_id,
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise ExecutionApprovalUnavailable from error

        return _approval_from_record(record) if record is not None else None

    def consume(
        self,
        *,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
    ) -> ExecutionApproval | None:
        consumed_at = _utc_datetime(self._clock())

        try:
            with self._session_factory.begin() as session:
                record = session.execute(
                    select(ExecutionApprovalRecord).where(
                        ExecutionApprovalRecord.project_id == project_id,
                        ExecutionApprovalRecord.plan_id == plan_id,
                        ExecutionApprovalRecord.plan_hash == plan_hash,
                    )
                ).scalar_one_or_none()

                if record is None:
                    return None

                approval = _approval_from_record(record)
                if (
                    approval.consumed_at is not None
                    or approval.expires_at <= consumed_at
                ):
                    return None

                claimed_id = session.execute(
                    update(ExecutionApprovalRecord)
                    .where(
                        ExecutionApprovalRecord.id == approval.id,
                        ExecutionApprovalRecord.consumed_at.is_(None),
                        ExecutionApprovalRecord.expires_at > consumed_at,
                    )
                    .values(consumed_at=consumed_at)
                    .returning(ExecutionApprovalRecord.id)
                    .execution_options(synchronize_session=False)
                ).scalar_one_or_none()

                if claimed_id is None:
                    return None
        except SQLAlchemyError as error:
            raise ExecutionApprovalUnavailable from error

        return replace(approval, consumed_at=consumed_at)


class ExecutionApprovalService:
    """Bind a trusted owner decision to one rebuilt canonical execution plan."""

    def __init__(self, repository: ExecutionApprovalRepository) -> None:
        self._repository = repository

    def approve(
        self,
        *,
        project_id: UUID,
        plan: ExecutionPlanV1,
        expected_plan_hash: str,
        approver: OwnerPrincipal,
        comment: str | None,
    ) -> ExecutionApproval:
        try:
            validated_plan = validate_execution_plan(plan)
        except ExecutionPlanRejected as error:
            raise ExecutionApprovalRejected(str(error)) from None

        if (
            not isinstance(expected_plan_hash, str)
            or len(expected_plan_hash) != 64
            or not compare_digest(expected_plan_hash, validated_plan.plan_hash)
        ):
            raise ExecutionApprovalRejected(
                "Expected plan hash does not match the rebuilt immutable plan"
            )

        approver_id, approver_source = approver_provenance(approver)
        return self._repository.create(
            project_id=project_id,
            plan=validated_plan,
            approver_id=approver_id,
            approver_authentication_source=approver_source,
            comment=validate_comment(comment),
        )

    def get(
        self,
        *,
        project_id: UUID,
        approval_id: UUID,
    ) -> ExecutionApproval | None:
        """Read an approval only for the project that owns it."""

        return self._repository.get(
            project_id=project_id,
            approval_id=approval_id,
        )

    def consume(
        self,
        *,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
    ) -> ExecutionApproval | None:
        """Internal future-worker claim only; no HTTP route may expose this."""

        return self._repository.consume(
            project_id=project_id,
            plan_id=plan_id,
            plan_hash=plan_hash,
        )


def execution_approval_repository_from_environment() -> ExecutionApprovalRepository:
    """Build durable approval persistence only with an explicit database URL."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableExecutionApprovalRepository()
    return SqlAlchemyExecutionApprovalRepository.from_database_url(database_url)


def approver_provenance(approver: OwnerPrincipal) -> tuple[str, str]:
    """Persist only identity resolved by the server-side authentication boundary."""

    if isinstance(approver, CognitoOwnerPrincipal):
        return (
            f"{approver.issuer}|{approver.subject}",
            approver.authentication_source,
        )
    if isinstance(approver, LocalDevelopmentOwnerPrincipal):
        return (
            LOCAL_DEVELOPMENT_APPROVER_ID,
            approver.authentication_source,
        )
    raise ExecutionApprovalRejected("Unsupported approver principal")


def validate_comment(comment: str | None) -> str | None:
    """Accept only an optional, bounded approval comment."""

    if comment is None:
        return None
    normalized = comment.strip()
    if not normalized or len(normalized) > MAX_EXECUTION_APPROVAL_COMMENT_LENGTH:
        raise ExecutionApprovalRejected(
            "Approval comment must be bounded, non-empty text"
        )
    return normalized


def _plan_snapshot(plan: ExecutionPlanV1) -> str:
    return json.dumps(
        {
            "schema_version": plan.schema_version,
            "id": str(plan.id),
            "target_id": plan.target_id.value,
            "target_base_url": plan.target_base_url,
            "target_schema_version": plan.target_schema_version,
            "test_case_id": str(plan.test_case_id),
            "test_case_payload": plan.test_case_payload,
            "limits": plan.limits.as_payload(),
            "estimate": plan.estimate.as_payload(),
            "plan_hash": plan.plan_hash,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _approval_from_record(record: ExecutionApprovalRecord) -> ExecutionApproval:
    try:
        plan = _plan_from_snapshot(record.plan_snapshot)
        if record.plan_id != plan.id or record.plan_hash != plan.plan_hash:
            raise ExecutionApprovalRejected(
                "Approval record does not match its immutable plan snapshot"
            )

        approved_at = _utc_datetime(record.approved_at)
        expires_at = _utc_datetime(record.expires_at)
        consumed_at = (
            _utc_datetime(record.consumed_at)
            if record.consumed_at is not None
            else None
        )
        if (
            not record.approver_id.strip()
            or expires_at <= approved_at
            or (consumed_at is not None and consumed_at < approved_at)
        ):
            raise ExecutionApprovalRejected("Approval record violates its contract")
    except (ExecutionApprovalRejected, ExecutionPlanRejected, ValueError) as error:
        raise ExecutionApprovalUnavailable from error

    return ExecutionApproval(
        id=record.id,
        project_id=record.project_id,
        plan=plan,
        approver_id=record.approver_id,
        approver_authentication_source=record.approver_authentication_source,
        comment=record.comment,
        approved_at=approved_at,
        expires_at=expires_at,
        consumed_at=consumed_at,
    )


def _plan_from_snapshot(snapshot: str) -> ExecutionPlanV1:
    try:
        decoded = cast(object, json.loads(snapshot))
        payload = _mapping(decoded, "Execution approval plan snapshot")
        plan = ExecutionPlanV1(
            schema_version=_string(payload, "schema_version"),
            id=UUID(_string(payload, "id")),
            target_id=TargetId(_string(payload, "target_id")),
            target_base_url=_string(payload, "target_base_url"),
            target_schema_version=_string(payload, "target_schema_version"),
            test_case_id=UUID(_string(payload, "test_case_id")),
            test_case_payload=_string(payload, "test_case_payload"),
            limits=_limits(_mapping(payload.get("limits"), "Execution plan limits")),
            estimate=_estimate(
                _mapping(payload.get("estimate"), "Execution plan estimate")
            ),
            plan_hash=_string(payload, "plan_hash"),
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise ExecutionApprovalRejected(
            "Approval plan snapshot is malformed"
        ) from error

    return validate_execution_plan(plan)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _integer(payload: Mapping[str, object], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _limits(payload: Mapping[str, object]) -> ExecutionLimitsV1:
    return ExecutionLimitsV1(
        request_timeout_ms=_integer(payload, "request_timeout_ms"),
        max_request_body_bytes=_integer(payload, "max_request_body_bytes"),
        max_response_bytes=_integer(payload, "max_response_bytes"),
        max_assertions=_integer(payload, "max_assertions"),
    )


def _estimate(payload: Mapping[str, object]) -> ExecutionEstimateV1:
    return ExecutionEstimateV1(
        request_count=_integer(payload, "request_count"),
        request_body_bytes=_integer(payload, "request_body_bytes"),
        assertion_count=_integer(payload, "assertion_count"),
        maximum_response_bytes=_integer(payload, "maximum_response_bytes"),
        maximum_duration_ms=_integer(payload, "maximum_duration_ms"),
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
