"""Durable terminal results for restricted execution jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import isfinite
import re
from typing import Protocol
from uuid import UUID, uuid4
import os

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    ExecutionJobRecord,
    ExecutionJobState,
    ExecutionResultOutcome,
    ExecutionResultRecord,
)


_REDACTED_VALUE = "[REDACTED]"
_SENSITIVE_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "secret",
        "set-cookie",
        "token",
    }
)


class ExecutionResultUnavailable(RuntimeError):
    """Raised when durable execution-result state cannot be safely accessed."""


class ExecutionResultRejected(ValueError):
    """Raised when terminal evidence cannot safely complete one running job."""


@dataclass(frozen=True)
class ExecutionResultPayload:
    """Already-redacted executor output eligible for durable storage only."""

    outcome: ExecutionResultOutcome
    failure_code: str | None
    assertion_results_json: str
    request_evidence_json: str | None
    response_evidence_json: str | None
    transport_send_count: int


@dataclass(frozen=True)
class StoredExecutionResult:
    """One immutable, redacted result durably bound to one execution job."""

    id: UUID
    execution_job_id: UUID
    outcome: ExecutionResultOutcome
    failure_code: str | None
    assertion_results_json: str
    request_evidence_json: str | None
    response_evidence_json: str | None
    transport_send_count: int
    recorded_at: datetime


@dataclass(frozen=True)
class _ValidatedExecutionResultPayload:
    """Canonical internal representation used for comparison and persistence."""

    outcome: ExecutionResultOutcome
    failure_code: str | None
    assertion_results_json: str
    request_evidence_json: str | None
    response_evidence_json: str | None
    transport_send_count: int


class ExecutionResultRepository(Protocol):
    """Atomic terminal-state and result-evidence boundary for a claimed job."""

    def record(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        payload: ExecutionResultPayload,
    ) -> StoredExecutionResult: ...

    def get(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> StoredExecutionResult | None: ...


def utc_now() -> datetime:
    """Return a timezone-aware timestamp for terminal result persistence."""

    return datetime.now(timezone.utc)


class SqlAlchemyExecutionResultRepository:
    """Persist one terminal result while atomically completing its running job."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
    ) -> SqlAlchemyExecutionResultRepository:
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def record(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        payload: ExecutionResultPayload,
    ) -> StoredExecutionResult:
        validated = _validate_payload(payload)
        now = _utc_datetime(self._clock())

        try:
            with self._session_factory.begin() as session:
                job_record = session.execute(
                    select(ExecutionJobRecord)
                    .where(
                        ExecutionJobRecord.id == job_id,
                        ExecutionJobRecord.project_id == project_id,
                    )
                    .with_for_update()
                ).scalar_one_or_none()

                if job_record is None:
                    raise ExecutionResultRejected(
                        "Execution job does not belong to the supplied project"
                    )

                existing_record = session.execute(
                    select(ExecutionResultRecord).where(
                        ExecutionResultRecord.execution_job_id == job_id
                    )
                ).scalar_one_or_none()

                if existing_record is not None:
                    existing = _stored_result_from_record(existing_record)
                    if _matches_payload(existing, validated):
                        return existing
                    raise ExecutionResultRejected(
                        "Execution job already has different terminal evidence"
                    )

                if (
                    job_record.state != ExecutionJobState.RUNNING.value
                    or job_record.started_at is None
                ):
                    raise ExecutionResultRejected(
                        "Only a claimed running execution job can be completed"
                    )

                _complete_job(
                    job_record=job_record,
                    outcome=validated.outcome,
                    completed_at=now,
                )

                result_record = ExecutionResultRecord(
                    id=self._id_factory(),
                    execution_job_id=job_id,
                    outcome=validated.outcome.value,
                    failure_code=validated.failure_code,
                    assertion_results=json.loads(validated.assertion_results_json),
                    request_evidence=(
                        json.loads(validated.request_evidence_json)
                        if validated.request_evidence_json is not None
                        else None
                    ),
                    response_evidence=(
                        json.loads(validated.response_evidence_json)
                        if validated.response_evidence_json is not None
                        else None
                    ),
                    transport_send_count=validated.transport_send_count,
                    recorded_at=now,
                )
                session.add(result_record)
                session.flush()

                return _stored_result_from_record(result_record)
        except SQLAlchemyError as error:
            raise ExecutionResultUnavailable from error

    def get(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> StoredExecutionResult | None:
        try:
            with self._session_factory() as session:
                record = session.execute(
                    select(ExecutionResultRecord)
                    .join(
                        ExecutionJobRecord,
                        ExecutionResultRecord.execution_job_id == ExecutionJobRecord.id,
                    )
                    .where(
                        ExecutionJobRecord.id == job_id,
                        ExecutionJobRecord.project_id == project_id,
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise ExecutionResultUnavailable from error

        return _stored_result_from_record(record) if record is not None else None


class UnavailableExecutionResultRepository:
    """Fail closed until durable terminal-result storage is configured."""

    def record(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        payload: ExecutionResultPayload,
    ) -> StoredExecutionResult:
        del project_id, job_id, payload
        raise ExecutionResultUnavailable

    def get(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> StoredExecutionResult | None:
        del project_id, job_id
        raise ExecutionResultUnavailable


def execution_result_repository_from_environment() -> ExecutionResultRepository:
    """Build durable terminal-result storage only with an explicit database URL."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableExecutionResultRepository()
    return SqlAlchemyExecutionResultRepository.from_database_url(database_url)


def _validate_payload(
    payload: ExecutionResultPayload,
) -> _ValidatedExecutionResultPayload:
    if not isinstance(payload, ExecutionResultPayload):
        raise ExecutionResultRejected("Execution result payload is malformed")

    if (
        not isinstance(payload.transport_send_count, int)
        or isinstance(payload.transport_send_count, bool)
        or payload.transport_send_count not in (0, 1)
    ):
        raise ExecutionResultRejected(
            "Restricted execution may record zero or one transport send"
        )

    failure_code = _validated_failure_code(
        outcome=payload.outcome,
        failure_code=payload.failure_code,
    )
    assertion_results_json = _canonical_json(
        payload.assertion_results_json,
        require_object=False,
    )
    if not _is_json_array(assertion_results_json):
        raise ExecutionResultRejected("Assertion results must be a JSON array")

    request_evidence_json = _validated_evidence_json(
        payload.request_evidence_json,
        label="Request evidence",
    )
    response_evidence_json = _validated_evidence_json(
        payload.response_evidence_json,
        label="Response evidence",
    )

    return _ValidatedExecutionResultPayload(
        outcome=payload.outcome,
        failure_code=failure_code,
        assertion_results_json=assertion_results_json,
        request_evidence_json=request_evidence_json,
        response_evidence_json=response_evidence_json,
        transport_send_count=payload.transport_send_count,
    )


def _validated_failure_code(
    *,
    outcome: ExecutionResultOutcome,
    failure_code: str | None,
) -> str | None:
    if outcome is ExecutionResultOutcome.SUCCEEDED:
        if failure_code is not None:
            raise ExecutionResultRejected(
                "A successful execution result cannot have a failure code"
            )
        return None

    if (
        not isinstance(failure_code, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", failure_code) is None
    ):
        raise ExecutionResultRejected(
            "A failed or cancelled execution result requires a safe failure code"
        )
    return failure_code


def _validated_evidence_json(
    value: str | None,
    *,
    label: str,
) -> str | None:
    if value is None:
        return None

    canonical = _canonical_json(value, require_object=True)
    _require_redacted_sensitive_values(json.loads(canonical))
    return canonical


def _canonical_json(
    value: str,
    *,
    require_object: bool,
) -> str:
    if not isinstance(value, str):
        raise ExecutionResultRejected("Execution result JSON is malformed")

    try:
        parsed: object = json.loads(value)
        _validate_json_value(parsed)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ExecutionResultRejected("Execution result JSON is malformed") from None

    if require_object and not isinstance(parsed, dict):
        raise ExecutionResultRejected("Execution evidence must be a JSON object")

    return json.dumps(
        parsed,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _is_json_array(value: str) -> bool:
    parsed: object = json.loads(value)
    return isinstance(parsed, list)


def _validate_json_value(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if isfinite(value):
            return
        raise ValueError("JSON floating-point value is not finite")
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object key is not text")
            _validate_json_value(item)
        return
    raise ValueError("JSON contains an unsupported value")


def _require_redacted_sensitive_values(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ExecutionResultRejected("Execution evidence has a non-text key")
            if _is_sensitive_name(key) and item != _REDACTED_VALUE:
                raise ExecutionResultRejected(
                    "Sensitive execution evidence must be redacted"
                )
            _require_redacted_sensitive_values(item)
        return

    if isinstance(value, list):
        if (
            len(value) == 2
            and isinstance(value[0], str)
            and _is_sensitive_name(value[0])
            and value[1] != _REDACTED_VALUE
        ):
            raise ExecutionResultRejected(
                "Sensitive execution evidence must be redacted"
            )
        for item in value:
            _require_redacted_sensitive_values(item)


def _is_sensitive_name(name: str) -> bool:
    normalized = name.lower().replace("_", "-")
    return any(sensitive in normalized for sensitive in _SENSITIVE_NAMES)


def _complete_job(
    *,
    job_record: ExecutionJobRecord,
    outcome: ExecutionResultOutcome,
    completed_at: datetime,
) -> None:
    if outcome is ExecutionResultOutcome.SUCCEEDED:
        job_record.state = ExecutionJobState.SUCCEEDED.value
        job_record.finished_at = completed_at
        return

    if outcome is ExecutionResultOutcome.FAILED:
        job_record.state = ExecutionJobState.FAILED.value
        job_record.finished_at = completed_at
        return

    job_record.state = ExecutionJobState.CANCELLED.value
    job_record.finished_at = None
    job_record.cancel_requested_at = job_record.cancel_requested_at or completed_at
    job_record.cancelled_at = completed_at


def _stored_result_from_record(
    record: ExecutionResultRecord,
) -> StoredExecutionResult:
    return StoredExecutionResult(
        id=record.id,
        execution_job_id=record.execution_job_id,
        outcome=ExecutionResultOutcome(record.outcome),
        failure_code=record.failure_code,
        assertion_results_json=_database_json(record.assertion_results),
        request_evidence_json=(
            _database_json(record.request_evidence)
            if record.request_evidence is not None
            else None
        ),
        response_evidence_json=(
            _database_json(record.response_evidence)
            if record.response_evidence is not None
            else None
        ),
        transport_send_count=record.transport_send_count,
        recorded_at=_utc_datetime(record.recorded_at),
    )


def _database_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _matches_payload(
    existing: StoredExecutionResult,
    payload: _ValidatedExecutionResultPayload,
) -> bool:
    return (
        existing.outcome is payload.outcome
        and existing.failure_code == payload.failure_code
        and existing.assertion_results_json == payload.assertion_results_json
        and existing.request_evidence_json == payload.request_evidence_json
        and existing.response_evidence_json == payload.response_evidence_json
        and existing.transport_send_count == payload.transport_send_count
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
