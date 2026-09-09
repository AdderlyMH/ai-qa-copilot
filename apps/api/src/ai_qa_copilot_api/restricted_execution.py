"""Deterministic restricted execution over an already claimed durable job.

This module deliberately depends on injected DNS and transport adapters.  It does
not create a resolver, HTTP client, worker loop, or API route.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
from typing import Final, Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID

from ai_qa_copilot_api.execution_approvals import ExecutionApproval
from ai_qa_copilot_api.documents import ExecutionJobState
from ai_qa_copilot_api.execution_jobs import ClaimedExecutionJob, ExecutionJob
from ai_qa_copilot_api.execution_plans import (
    ExecutionPlanRejected,
    ExecutionPlanV1,
    validate_execution_plan,
)
from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    GeneratedAssertionV1,
    HttpMethod,
)
from ai_qa_copilot_api.target_registry import (
    AddressResolver,
    DEFAULT_TARGET_REGISTRY,
    TargetRegistry,
    TargetValidationError,
    validate_registered_target,
)


_FORBIDDEN_REQUEST_HEADERS: Final = frozenset(
    {
        "authorization",
        "cookie",
        "host",
        "proxy-authorization",
        "set-cookie",
        "x-forwarded-for",
    }
)
_SENSITIVE_NAMES: Final = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "secret",
        "set-cookie",
        "token",
    }
)
_REDACTED_VALUE: Final = "[REDACTED]"
_MISSING: Final = object()


class ExecutionOutcome(StrEnum):
    """Terminal outcome emitted by one restricted execution attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionFailureCode(StrEnum):
    """Safe, stable reasons why a restricted execution did not succeed."""

    INVALID_CLAIM = "invalid_claim"
    APPROVAL_MISMATCH = "approval_mismatch"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_NOT_CONSUMED = "approval_not_consumed"
    PLAN_INVALID = "plan_invalid"
    PLAN_LIMIT_EXCEEDED = "plan_limit_exceeded"
    CANCELLED = "cancelled"
    TARGET_DENIED = "target_denied"
    FORBIDDEN_HEADER = "forbidden_header"
    TRANSPORT_TIMEOUT = "transport_timeout"
    TRANSPORT_ERROR = "transport_error"
    RESPONSE_TOO_LARGE = "response_too_large"
    REDIRECT_RESPONSE = "redirect_response"
    ASSERTIONS_FAILED = "assertions_failed"


class ExecutionTransport(Protocol):
    """The sole outbound seam; implementations are intentionally injected."""

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
        """Send exactly one bounded request through one validated address."""


class CancellationProbe(Protocol):
    """Read the durable cancellation state without making a transport request."""

    def is_cancel_requested(self, job_id: UUID) -> bool:
        """Return whether the job must stop before another side effect."""


@dataclass(frozen=True)
class TransportResponse:
    """Bounded raw response returned by an injected transport adapter."""

    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    elapsed_ms: int


@dataclass(frozen=True)
class AssertionResult:
    """One redaction-safe result from the allowlisted assertion evaluator."""

    target: AssertionTarget
    selector: str | None
    operator: AssertionOperator
    passed: bool


@dataclass(frozen=True)
class RedactedRequestEvidence:
    """Evidence about the sent request with known sensitive fields removed."""

    method: HttpMethod
    url: str
    headers: tuple[tuple[str, str], ...]
    json_body: object | None


@dataclass(frozen=True)
class RedactedResponseEvidence:
    """Evidence about a response without retaining arbitrary raw body text."""

    status_code: int
    headers: tuple[tuple[str, str], ...]
    json_body: object | None
    body_bytes: int
    body_sha256: str
    elapsed_ms: int


@dataclass(frozen=True)
class ExecutionResult:
    """Complete safe result for exactly one claimed job execution attempt."""

    job_id: UUID | None
    outcome: ExecutionOutcome
    assertion_results: tuple[AssertionResult, ...]
    request_evidence: RedactedRequestEvidence | None
    response_evidence: RedactedResponseEvidence | None
    error_code: ExecutionFailureCode | None
    error_message: str | None
    transport_send_count: int


class NeverCancelled:
    """Default probe used by tests until durable cancellation is wired."""

    def is_cancel_requested(self, job_id: UUID) -> bool:
        del job_id
        return False


def utc_now() -> datetime:
    """Return a timezone-aware time used for approval-expiry validation."""

    return datetime.now(timezone.utc)


class RestrictedExecutionExecutor:
    """Execute one already claimed plan through deterministic fail-closed checks."""

    def __init__(
        self,
        *,
        resolver: AddressResolver,
        transport: ExecutionTransport,
        cancellation_probe: CancellationProbe | None = None,
        registry: TargetRegistry = DEFAULT_TARGET_REGISTRY,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._cancellation_probe = cancellation_probe or NeverCancelled()
        self._registry = registry
        self._clock = clock

    def execute(self, claimed: ClaimedExecutionJob) -> ExecutionResult:
        """Execute at most one request from one atomically claimed durable job."""

        if not isinstance(claimed, ClaimedExecutionJob):
            return _failed(None, ExecutionFailureCode.INVALID_CLAIM)

        job = claimed.job
        approval = claimed.approval
        if not isinstance(job, ExecutionJob) or not isinstance(
            approval, ExecutionApproval
        ):
            return _failed(None, ExecutionFailureCode.INVALID_CLAIM)
        now = _utc_datetime(self._clock())
        failure = _validate_claim(
            job_id=job.id, approval=approval, claimed=claimed, now=now
        )
        if failure is not None:
            return _failed(job.id, failure)

        try:
            plan = validate_execution_plan(approval.plan, registry=self._registry)
        except ExecutionPlanRejected:
            return _failed(job.id, ExecutionFailureCode.PLAN_INVALID)

        if not _job_matches_plan(claimed=claimed, plan=plan):
            return _failed(job.id, ExecutionFailureCode.APPROVAL_MISMATCH)

        request = plan.test_case.request
        if not _plan_limits_match(plan):
            return _failed(job.id, ExecutionFailureCode.PLAN_LIMIT_EXCEEDED)
        try:
            body = _canonical_body(request.json_body)
            headers = _validated_headers(request.headers)
        except ValueError as error:
            code = (
                ExecutionFailureCode.FORBIDDEN_HEADER
                if str(error) == "forbidden_header"
                else ExecutionFailureCode.PLAN_INVALID
            )
            return _failed(job.id, code)

        if body is not None and len(body) > plan.limits.max_request_body_bytes:
            return _failed(job.id, ExecutionFailureCode.PLAN_LIMIT_EXCEEDED)

        request_evidence = RedactedRequestEvidence(
            method=request.method,
            url=_redact_url(_request_url(plan=plan)),
            headers=_redact_headers(headers),
            json_body=_redact_json(request.json_body),
        )
        if self._cancellation_probe.is_cancel_requested(job.id):
            return _cancelled(job.id, request_evidence)

        try:
            target = validate_registered_target(
                plan.target_id.value,
                resolver=self._resolver,
                registry=self._registry,
            )
        except TargetValidationError:
            return _failed(
                job.id,
                ExecutionFailureCode.TARGET_DENIED,
                request_evidence=request_evidence,
            )

        if target.id is not plan.target_id or target.origin != plan.target_base_url:
            return _failed(
                job.id,
                ExecutionFailureCode.TARGET_DENIED,
                request_evidence=request_evidence,
            )

        if self._cancellation_probe.is_cancel_requested(job.id):
            return _cancelled(job.id, request_evidence)

        url = _request_url(plan=plan)
        try:
            response = self._transport.send(
                method=request.method,
                url=url,
                headers=headers,
                body=body,
                timeout_ms=plan.limits.request_timeout_ms,
                max_response_bytes=plan.limits.max_response_bytes,
                follow_redirects=False,
                resolved_address=target.resolved_addresses[0],
            )
        except TimeoutError:
            return _failed(
                job.id,
                ExecutionFailureCode.TRANSPORT_TIMEOUT,
                request_evidence=request_evidence,
                transport_send_count=1,
            )
        except Exception:
            return _failed(
                job.id,
                ExecutionFailureCode.TRANSPORT_ERROR,
                request_evidence=request_evidence,
                transport_send_count=1,
            )

        if not _valid_transport_response(response):
            return _failed(
                job.id,
                ExecutionFailureCode.TRANSPORT_ERROR,
                request_evidence=request_evidence,
                transport_send_count=1,
            )
        if len(response.body) > plan.limits.max_response_bytes:
            return _failed(
                job.id,
                ExecutionFailureCode.RESPONSE_TOO_LARGE,
                request_evidence=request_evidence,
                response_evidence=_response_evidence(response, include_json=False),
                transport_send_count=1,
            )

        response_evidence = _response_evidence(response)
        if 300 <= response.status_code < 400:
            return _failed(
                job.id,
                ExecutionFailureCode.REDIRECT_RESPONSE,
                request_evidence=request_evidence,
                response_evidence=response_evidence,
                transport_send_count=1,
            )

        assertions = _evaluate_assertions(plan=plan, response=response)
        if self._cancellation_probe.is_cancel_requested(job.id):
            return _cancelled(
                job.id,
                request_evidence,
                response_evidence,
                assertions,
                transport_send_count=1,
            )
        if not all(assertion.passed for assertion in assertions):
            return _failed(
                job.id,
                ExecutionFailureCode.ASSERTIONS_FAILED,
                request_evidence=request_evidence,
                response_evidence=response_evidence,
                assertion_results=assertions,
                transport_send_count=1,
            )
        return ExecutionResult(
            job_id=job.id,
            outcome=ExecutionOutcome.SUCCEEDED,
            assertion_results=assertions,
            request_evidence=request_evidence,
            response_evidence=response_evidence,
            error_code=None,
            error_message=None,
            transport_send_count=1,
        )


def _validate_claim(
    *,
    job_id: UUID,
    approval: ExecutionApproval,
    claimed: ClaimedExecutionJob,
    now: datetime,
) -> ExecutionFailureCode | None:
    job = claimed.job
    if (
        job.id != job_id
        or job.state is not ExecutionJobState.RUNNING
        or job.started_at is None
        or job.execution_approval_id != approval.id
    ):
        return ExecutionFailureCode.APPROVAL_MISMATCH
    if job.project_id != approval.project_id:
        return ExecutionFailureCode.APPROVAL_MISMATCH
    if approval.consumed_at is None:
        return ExecutionFailureCode.APPROVAL_NOT_CONSUMED
    if approval.expires_at <= now:
        return ExecutionFailureCode.APPROVAL_EXPIRED
    return None


def _job_matches_plan(*, claimed: ClaimedExecutionJob, plan: ExecutionPlanV1) -> bool:
    job = claimed.job
    return (
        job.plan_id == plan.id
        and job.plan_hash == plan.plan_hash
        and plan.id == claimed.approval.plan.id
        and plan.plan_hash == claimed.approval.plan.plan_hash
    )


def _plan_limits_match(plan: ExecutionPlanV1) -> bool:
    request = plan.test_case.request
    body = _canonical_body(request.json_body)
    return (
        plan.estimate.request_count == 1
        and plan.estimate.assertion_count == len(plan.test_case.assertions)
        and plan.estimate.assertion_count <= plan.limits.max_assertions
        and plan.estimate.maximum_response_bytes == plan.limits.max_response_bytes
        and plan.estimate.maximum_duration_ms == plan.limits.request_timeout_ms
        and plan.estimate.request_body_bytes == (0 if body is None else len(body))
    )


def _canonical_body(value: dict[str, object] | None) -> bytes | None:
    if value is None:
        return None
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _validated_headers(
    headers: tuple[object, ...],
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    for header in headers:
        name = getattr(header, "name", None)
        value = getattr(header, "value", None)
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("malformed_header")
        if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
            raise ValueError("malformed_header")
        if name.lower() in _FORBIDDEN_REQUEST_HEADERS:
            raise ValueError("forbidden_header")
        normalized.append((name, value))
    return tuple(normalized)


def _request_url(*, plan: ExecutionPlanV1) -> str:
    request = plan.test_case.request
    query = urlencode(
        tuple((parameter.name, parameter.value) for parameter in request.query)
    )
    return f"{plan.target_base_url}{request.path}" + (f"?{query}" if query else "")


def _evaluate_assertions(
    *,
    plan: ExecutionPlanV1,
    response: TransportResponse,
) -> tuple[AssertionResult, ...]:
    json_body = _parse_json_object_or_array(response.body)
    headers = _response_headers(response.headers)
    return tuple(
        AssertionResult(
            target=assertion.target,
            selector=assertion.selector,
            operator=assertion.operator,
            passed=_evaluate_assertion(
                assertion=assertion,
                response=response,
                headers=headers,
                json_body=json_body,
            ),
        )
        for assertion in plan.test_case.assertions
    )


def _evaluate_assertion(
    *,
    assertion: GeneratedAssertionV1,
    response: TransportResponse,
    headers: Mapping[str, tuple[str, ...]],
    json_body: object,
) -> bool:
    if assertion.target is AssertionTarget.STATUS_CODE:
        return response.status_code == assertion.expected_value
    if assertion.target is AssertionTarget.RESPONSE_TIME_MS:
        expected = assertion.expected_value
        return (
            isinstance(expected, int)
            and not isinstance(expected, bool)
            and expected > 0
            and response.elapsed_ms <= expected
        )
    if assertion.target is AssertionTarget.RESPONSE_HEADER:
        value = headers.get((assertion.selector or "").lower(), _MISSING)
        return _apply_operator(value, assertion.operator, assertion.expected_value)
    if assertion.target is AssertionTarget.JSON_BODY:
        value = _json_pointer(json_body, assertion.selector or "")
        return _apply_operator(value, assertion.operator, assertion.expected_value)
    return False


def _apply_operator(
    value: object,
    operator: AssertionOperator,
    expected: object,
) -> bool:
    if operator is AssertionOperator.EXISTS:
        return value is not _MISSING
    if value is _MISSING:
        return False
    if operator is AssertionOperator.EQUALS:
        if isinstance(value, tuple):
            return expected in value
        return value == expected
    if operator is AssertionOperator.CONTAINS:
        if isinstance(value, str):
            return isinstance(expected, str) and expected in value
        if isinstance(value, (tuple, list)):
            return expected in value
        if isinstance(value, Mapping):
            return isinstance(expected, str) and expected in value
        return False
    if operator is AssertionOperator.LESS_THAN_OR_EQUAL:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and isinstance(expected, int)
            and not isinstance(expected, bool)
            and value <= expected
        )
    return False


def _response_headers(
    headers: tuple[tuple[str, str], ...],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for name, value in headers:
        result.setdefault(name.lower(), []).append(value)
    return {name: tuple(values) for name, values in result.items()}


def _parse_json_object_or_array(body: bytes) -> object:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _MISSING
    return value if isinstance(value, (dict, list)) else _MISSING


def _json_pointer(document: object, pointer: str) -> object:
    if document is _MISSING or not pointer.startswith("/"):
        return _MISSING
    current = document
    for escaped_token in pointer.removeprefix("/").split("/"):
        token = escaped_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            current = current.get(token, _MISSING)
        elif (
            isinstance(current, list)
            and token.isdecimal()
            and (token == "0" or not token.startswith("0"))
        ):
            index = int(token)
            current = current[index] if index < len(current) else _MISSING
        else:
            return _MISSING
        if current is _MISSING:
            return _MISSING
    return current


def _response_evidence(
    response: TransportResponse,
    *,
    include_json: bool = True,
) -> RedactedResponseEvidence:
    return RedactedResponseEvidence(
        status_code=response.status_code,
        headers=_redact_headers(response.headers),
        json_body=(
            _redact_json(_parse_json_object_or_array(response.body))
            if include_json
            else None
        ),
        body_bytes=len(response.body),
        body_sha256=sha256(response.body).hexdigest(),
        elapsed_ms=response.elapsed_ms,
    )


def _valid_transport_response(response: object) -> bool:
    if (
        not isinstance(response, TransportResponse)
        or not isinstance(response.status_code, int)
        or isinstance(response.status_code, bool)
        or not 100 <= response.status_code <= 599
        or not isinstance(response.body, bytes)
        or not isinstance(response.elapsed_ms, int)
        or isinstance(response.elapsed_ms, bool)
        or response.elapsed_ms < 0
        or not isinstance(response.headers, tuple)
    ):
        return False
    return all(
        isinstance(header, tuple)
        and len(header) == 2
        and isinstance(header[0], str)
        and isinstance(header[1], str)
        for header in response.headers
    )


def _redact_headers(
    headers: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, _REDACTED_VALUE if _is_sensitive_name(name) else value)
        for name, value in headers
    )


def _redact_json(value: object) -> object | None:
    if value is _MISSING:
        return None
    if isinstance(value, Mapping):
        return {
            str(key): (
                _REDACTED_VALUE if _is_sensitive_name(str(key)) else _redact_json(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    return value


def _is_sensitive_name(name: str) -> bool:
    normalized = name.lower().replace("_", "-")
    return any(sensitive in normalized for sensitive in _SENSITIVE_NAMES)


def _redact_url(url: str) -> str:
    parsed = urlsplit(url)
    pairs = []
    for item in parsed.query.split("&"):
        name, separator, value = item.partition("=")
        pairs.append(
            f"{name}{separator}{_REDACTED_VALUE if _is_sensitive_name(name) else value}"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "&".join(pairs), ""))


def _failed(
    job_id: UUID | None,
    code: ExecutionFailureCode,
    *,
    request_evidence: RedactedRequestEvidence | None = None,
    response_evidence: RedactedResponseEvidence | None = None,
    assertion_results: tuple[AssertionResult, ...] = (),
    transport_send_count: int = 0,
) -> ExecutionResult:
    return ExecutionResult(
        job_id=job_id,
        outcome=ExecutionOutcome.FAILED,
        assertion_results=assertion_results,
        request_evidence=request_evidence,
        response_evidence=response_evidence,
        error_code=code,
        error_message="Restricted execution was denied or did not complete safely.",
        transport_send_count=transport_send_count,
    )


def _cancelled(
    job_id: UUID,
    request_evidence: RedactedRequestEvidence,
    response_evidence: RedactedResponseEvidence | None = None,
    assertion_results: tuple[AssertionResult, ...] = (),
    *,
    transport_send_count: int = 0,
) -> ExecutionResult:
    return ExecutionResult(
        job_id=job_id,
        outcome=ExecutionOutcome.CANCELLED,
        assertion_results=assertion_results,
        request_evidence=request_evidence,
        response_evidence=response_evidence,
        error_code=ExecutionFailureCode.CANCELLED,
        error_message="Restricted execution was cancelled.",
        transport_send_count=transport_send_count,
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
