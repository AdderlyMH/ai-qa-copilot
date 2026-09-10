"""Read-only, redaction-safe display projections for execution evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from math import isfinite
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from ai_qa_copilot_api.execution_results import StoredExecutionResult


_REDACTED_VALUE: Final = "[REDACTED]"
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


class ExecutionEvidenceViewRejected(ValueError):
    """Raised when stored evidence cannot be safely projected for display."""


@dataclass(frozen=True)
class ExecutionEvidenceView:
    """Read-only, re-redacted evidence suitable for a future owner-only viewer."""

    id: UUID
    execution_job_id: UUID
    outcome: str
    failure_code: str | None
    assertion_results: tuple[dict[str, object], ...]
    request_evidence: dict[str, object] | None
    response_evidence: dict[str, object] | None
    response_status_code: int | None
    response_elapsed_ms: int | None
    transport_send_count: int
    recorded_at: datetime


def execution_evidence_view_from_result(
    result: StoredExecutionResult,
) -> ExecutionEvidenceView:
    """Re-parse and re-redact one durable result without exposing raw evidence."""

    if not isinstance(result, StoredExecutionResult):
        raise ExecutionEvidenceViewRejected("Execution result is malformed")

    assertion_results = _assertion_results(result.assertion_results_json)
    request_evidence = _evidence_object(
        result.request_evidence_json,
        label="request",
    )
    response_evidence = _evidence_object(
        result.response_evidence_json,
        label="response",
    )

    return ExecutionEvidenceView(
        id=result.id,
        execution_job_id=result.execution_job_id,
        outcome=result.outcome.value,
        failure_code=result.failure_code,
        assertion_results=assertion_results,
        request_evidence=request_evidence,
        response_evidence=response_evidence,
        response_status_code=_response_integer(
            response_evidence,
            key="status_code",
        ),
        response_elapsed_ms=_response_integer(
            response_evidence,
            key="elapsed_ms",
        ),
        transport_send_count=result.transport_send_count,
        recorded_at=result.recorded_at,
    )


def _assertion_results(value: str) -> tuple[dict[str, object], ...]:
    parsed = _json_value(value, label="assertion results")
    if not isinstance(parsed, list):
        raise ExecutionEvidenceViewRejected("Execution assertion results are malformed")

    assertions: list[dict[str, object]] = []
    for assertion in parsed:
        if not isinstance(assertion, Mapping):
            raise ExecutionEvidenceViewRejected(
                "Execution assertion results are malformed"
            )
        assertions.append(_redacted_mapping(assertion))
    return tuple(assertions)


def _evidence_object(
    value: str | None,
    *,
    label: str,
) -> dict[str, object] | None:
    if value is None:
        return None

    parsed = _json_value(value, label=f"{label} evidence")
    if not isinstance(parsed, Mapping):
        raise ExecutionEvidenceViewRejected(f"Execution {label} evidence is malformed")
    return _redacted_mapping(parsed)


def _json_value(value: str, *, label: str) -> object:
    if not isinstance(value, str):
        raise ExecutionEvidenceViewRejected(f"Execution {label} is malformed")

    try:
        parsed: object = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ExecutionEvidenceViewRejected(f"Execution {label} is malformed") from None

    _validate_json_value(parsed, label=label)
    return parsed


def _validate_json_value(value: object, *, label: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return

    if isinstance(value, float):
        if isfinite(value):
            return
        raise ExecutionEvidenceViewRejected(f"Execution {label} is malformed")

    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, label=label)
        return

    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ExecutionEvidenceViewRejected(f"Execution {label} is malformed")
            _validate_json_value(item, label=label)
        return

    raise ExecutionEvidenceViewRejected(f"Execution {label} is malformed")


def _redacted_mapping(value: Mapping[object, object]) -> dict[str, object]:
    rendered: dict[str, object] = {}

    for key, item in value.items():
        if not isinstance(key, str):
            raise ExecutionEvidenceViewRejected("Execution evidence is malformed")

        if _is_sensitive_name(key):
            rendered[key] = _REDACTED_VALUE
        elif key == "url" and isinstance(item, str):
            rendered[key] = _redact_url(item)
        else:
            rendered[key] = _redacted_value(item)

    return rendered


def _redacted_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _redacted_mapping(value)

    if isinstance(value, list):
        if (
            len(value) == 2
            and isinstance(value[0], str)
            and _is_sensitive_name(value[0])
        ):
            return [value[0], _REDACTED_VALUE]
        return [_redacted_value(item) for item in value]

    return value


def _response_integer(
    response_evidence: dict[str, object] | None,
    *,
    key: str,
) -> int | None:
    if response_evidence is None or key not in response_evidence:
        return None

    value = response_evidence[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExecutionEvidenceViewRejected("Execution response evidence is malformed")
    return value


def _is_sensitive_name(name: str) -> bool:
    normalized = name.lower().replace("_", "-")
    return any(sensitive in normalized for sensitive in _SENSITIVE_NAMES)


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return _REDACTED_VALUE

    if parsed.username is not None or parsed.password is not None:
        return _REDACTED_VALUE

    try:
        query = urlencode(
            [
                (
                    name,
                    _REDACTED_VALUE if _is_sensitive_name(name) else item,
                )
                for name, item in parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                    strict_parsing=False,
                )
            ],
            doseq=True,
        )
    except ValueError:
        return _REDACTED_VALUE

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            query,
            "",
        )
    )
