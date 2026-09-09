"""One-shot orchestration for one already-claimed restricted execution job."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from math import isfinite
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from ai_qa_copilot_api.documents import ExecutionResultOutcome
from ai_qa_copilot_api.execution_jobs import ClaimedExecutionJob, ExecutionJob
from ai_qa_copilot_api.execution_results import (
    ExecutionResultPayload,
    StoredExecutionResult,
)
from ai_qa_copilot_api.restricted_execution import (
    AssertionResult,
    ExecutionOutcome,
    ExecutionResult,
    RedactedRequestEvidence,
    RedactedResponseEvidence,
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


class ExecutionWorkerInvariantError(RuntimeError):
    """Raised when a claimed job or executor result cannot be safely persisted."""


class ExecutionJobClaimer(Protocol):
    """The only queue capability required by the one-shot worker."""

    def claim_next(self) -> ClaimedExecutionJob | None: ...


class RestrictedExecutionRunner(Protocol):
    """Restricted executor boundary; implementations execute at most one request."""

    def execute(self, claimed: ClaimedExecutionJob) -> ExecutionResult: ...


class ExecutionResultRecorder(Protocol):
    """Durable terminal-result boundary for one already-running job."""

    def record(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        payload: ExecutionResultPayload,
    ) -> StoredExecutionResult: ...


@dataclass(frozen=True)
class ExecutionWorkerRun:
    """The observable outcome of one worker invocation."""

    claimed_job_id: UUID | None
    execution_result: ExecutionResult | None
    stored_result: StoredExecutionResult | None


class RestrictedExecutionWorker:
    """Claim, execute, and record no more than one durable execution job."""

    def __init__(
        self,
        *,
        jobs: ExecutionJobClaimer,
        executor: RestrictedExecutionRunner,
        results: ExecutionResultRecorder,
    ) -> None:
        self._jobs = jobs
        self._executor = executor
        self._results = results

    def run_once(self) -> ExecutionWorkerRun:
        """Process at most one claimed job; this method never retries."""

        claimed = self._jobs.claim_next()
        if claimed is None:
            return ExecutionWorkerRun(
                claimed_job_id=None,
                execution_result=None,
                stored_result=None,
            )

        if not isinstance(claimed, ClaimedExecutionJob) or not isinstance(
            claimed.job,
            ExecutionJob,
        ):
            raise ExecutionWorkerInvariantError(
                "The execution queue returned a malformed claimed job"
            )

        result = self._executor.execute(claimed)
        _require_result_for_claim(result=result, claimed=claimed)
        payload = execution_result_payload(result)

        stored = self._results.record(
            project_id=claimed.job.project_id,
            job_id=claimed.job.id,
            payload=payload,
        )
        return ExecutionWorkerRun(
            claimed_job_id=claimed.job.id,
            execution_result=result,
            stored_result=stored,
        )


def execution_result_payload(result: ExecutionResult) -> ExecutionResultPayload:
    """Convert executor-only redacted data into canonical durable evidence."""

    if not isinstance(result, ExecutionResult):
        raise ExecutionWorkerInvariantError("The executor returned a malformed result")

    outcome = _durable_outcome(result.outcome)
    failure_code = _failure_code(result=result, outcome=outcome)

    return ExecutionResultPayload(
        outcome=outcome,
        failure_code=failure_code,
        assertion_results_json=_canonical_json(
            [_assertion_payload(assertion) for assertion in result.assertion_results]
        ),
        request_evidence_json=_request_evidence_json(result.request_evidence),
        response_evidence_json=_response_evidence_json(result.response_evidence),
        transport_send_count=_transport_send_count(result.transport_send_count),
    )


def _require_result_for_claim(
    *,
    result: ExecutionResult,
    claimed: ClaimedExecutionJob,
) -> None:
    if not isinstance(result, ExecutionResult):
        raise ExecutionWorkerInvariantError("The executor returned a malformed result")
    if result.job_id != claimed.job.id:
        raise ExecutionWorkerInvariantError(
            "The executor result does not belong to the claimed job"
        )


def _durable_outcome(outcome: ExecutionOutcome) -> ExecutionResultOutcome:
    if not isinstance(outcome, ExecutionOutcome):
        raise ExecutionWorkerInvariantError(
            "The executor result has an invalid outcome"
        )
    return ExecutionResultOutcome(outcome.value)


def _failure_code(
    *,
    result: ExecutionResult,
    outcome: ExecutionResultOutcome,
) -> str | None:
    error_code = result.error_code
    if outcome is ExecutionResultOutcome.SUCCEEDED:
        if error_code is not None:
            raise ExecutionWorkerInvariantError(
                "A successful executor result cannot have a failure code"
            )
        return None

    if error_code is None:
        raise ExecutionWorkerInvariantError(
            "A failed or cancelled executor result requires a failure code"
        )
    return error_code.value


def _transport_send_count(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1):
        raise ExecutionWorkerInvariantError(
            "Restricted execution may report zero or one transport send"
        )
    return value


def _assertion_payload(assertion: AssertionResult) -> dict[str, object]:
    if not isinstance(assertion, AssertionResult):
        raise ExecutionWorkerInvariantError(
            "The executor result contains a malformed assertion"
        )
    return {
        "operator": assertion.operator.value,
        "passed": assertion.passed,
        "selector": assertion.selector,
        "target": assertion.target.value,
    }


def _request_evidence_json(
    evidence: RedactedRequestEvidence | None,
) -> str | None:
    if evidence is None:
        return None
    if not isinstance(evidence, RedactedRequestEvidence):
        raise ExecutionWorkerInvariantError(
            "The executor result contains malformed request evidence"
        )

    return _canonical_json(
        {
            "headers": _redacted_headers(evidence.headers),
            "json_body": _redact_json(evidence.json_body),
            "method": evidence.method.value,
            "url": _redact_url(evidence.url),
        }
    )


def _response_evidence_json(
    evidence: RedactedResponseEvidence | None,
) -> str | None:
    if evidence is None:
        return None
    if not isinstance(evidence, RedactedResponseEvidence):
        raise ExecutionWorkerInvariantError(
            "The executor result contains malformed response evidence"
        )

    return _canonical_json(
        {
            "body_bytes": evidence.body_bytes,
            "body_sha256": evidence.body_sha256,
            "elapsed_ms": evidence.elapsed_ms,
            "headers": _redacted_headers(evidence.headers),
            "json_body": _redact_json(evidence.json_body),
            "status_code": evidence.status_code,
        }
    )


def _redacted_headers(
    headers: tuple[tuple[str, str], ...],
) -> list[list[str]]:
    if not isinstance(headers, tuple):
        raise ExecutionWorkerInvariantError("Execution evidence headers are malformed")

    redacted: list[list[str]] = []
    for header in headers:
        if (
            not isinstance(header, tuple)
            or len(header) != 2
            or not isinstance(header[0], str)
            or not isinstance(header[1], str)
        ):
            raise ExecutionWorkerInvariantError(
                "Execution evidence headers are malformed"
            )
        name, value = header
        redacted.append([name, _REDACTED_VALUE if _is_sensitive_name(name) else value])
    return redacted


def _redact_json(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if isfinite(value):
            return value
        raise ExecutionWorkerInvariantError(
            "Execution evidence contains a non-finite number"
        )
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ExecutionWorkerInvariantError(
                    "Execution evidence contains a non-text JSON key"
                )
            redacted[key] = (
                _REDACTED_VALUE if _is_sensitive_name(key) else _redact_json(item)
            )
        return redacted
    raise ExecutionWorkerInvariantError(
        "Execution evidence contains an unsupported JSON value"
    )


def _redact_url(url: str) -> str:
    if not isinstance(url, str):
        raise ExecutionWorkerInvariantError(
            "Execution request evidence URL is malformed"
        )

    try:
        parsed = urlsplit(url)
    except ValueError as error:
        raise ExecutionWorkerInvariantError(
            "Execution request evidence URL is malformed"
        ) from error

    query_parts: list[str] = []
    for item in parsed.query.split("&"):
        name, separator, value = item.partition("=")
        query_parts.append(
            f"{name}{separator}{_REDACTED_VALUE if _is_sensitive_name(name) else value}"
        )

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "&".join(query_parts),
            "",
        )
    )


def _is_sensitive_name(name: str) -> bool:
    normalized = name.lower().replace("_", "-")
    return any(sensitive in normalized for sensitive in _SENSITIVE_NAMES)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ExecutionWorkerInvariantError(
            "Execution evidence cannot be represented as JSON"
        ) from error
