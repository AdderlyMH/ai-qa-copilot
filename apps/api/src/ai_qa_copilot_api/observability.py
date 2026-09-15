"""Safe structured workflow tracing for local and deployed adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
import json
import logging
from math import isfinite
from time import perf_counter
from typing import ParamSpec, Protocol, TypeVar, runtime_checkable
from uuid import UUID, uuid4


WORKFLOW_TRACE_LOGGER = "ai_qa_copilot_api.workflow_trace"
MAX_TRACE_NAME_LENGTH = 96
MAX_TRACE_ATTRIBUTE_KEY_LENGTH = 64
MAX_TRACE_ATTRIBUTE_VALUE_LENGTH = 256
FORBIDDEN_TRACE_ATTRIBUTE_KEY_FRAGMENTS = frozenset(
    {
        "authorization",
        "body",
        "cookie",
        "password",
        "prompt",
        "query",
        "response",
        "secret",
        "token",
    }
)

TraceAttributeValue = str | int | float | bool
P = ParamSpec("P")
T = TypeVar("T")


class WorkflowTraceRejected(ValueError):
    """Raised when a span attempts to retain unsafe or malformed metadata."""


@dataclass(frozen=True)
class WorkflowTraceSpan:
    """One immutable, secret-safe completed span."""

    trace_id: UUID
    span_id: UUID
    parent_span_id: UUID | None
    name: str
    started_at: datetime
    duration_ms: float
    outcome: str
    attributes: Mapping[str, TraceAttributeValue]

    def as_dict(self) -> dict[str, object]:
        return {
            "trace_id": str(self.trace_id),
            "span_id": str(self.span_id),
            "parent_span_id": (
                str(self.parent_span_id) if self.parent_span_id is not None else None
            ),
            "name": self.name,
            "started_at": self.started_at.astimezone(timezone.utc).isoformat(),
            "duration_ms": self.duration_ms,
            "outcome": self.outcome,
            "attributes": dict(self.attributes),
        }


@runtime_checkable
class WorkflowTraceSink(Protocol):
    """Destination for completed, schema-shaped workflow spans."""

    def record(self, span: WorkflowTraceSpan) -> None: ...


class StructuredLoggingTraceSink:
    """Emit one canonical JSON span without request, secret, or body content."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(WORKFLOW_TRACE_LOGGER)

    def record(self, span: WorkflowTraceSpan) -> None:
        self._logger.info(
            "workflow_trace=%s",
            json.dumps(span.as_dict(), sort_keys=True, separators=(",", ":")),
        )


@dataclass(frozen=True)
class _TraceContext:
    trace_id: UUID
    sink: WorkflowTraceSink
    parent_span_id: UUID | None


_TRACE_CONTEXT: ContextVar[_TraceContext | None] = ContextVar(
    "workflow_trace_context",
    default=None,
)


def current_trace_id() -> UUID | None:
    """Return the active workflow trace identifier, if any."""

    context = _TRACE_CONTEXT.get()
    return context.trace_id if context is not None else None


@contextmanager
def workflow_trace(
    *,
    trace_id: UUID | None = None,
    sink: WorkflowTraceSink | None = None,
    name: str = "workflow",
    attributes: Mapping[str, TraceAttributeValue] | None = None,
) -> Iterator[UUID]:
    """Start one root trace and return its server-generated identifier."""

    selected_trace_id = trace_id or uuid4()
    if selected_trace_id.int == 0:
        raise WorkflowTraceRejected("Workflow trace identifiers must be non-zero UUIDs")
    selected_sink = sink or StructuredLoggingTraceSink()
    token = _TRACE_CONTEXT.set(
        _TraceContext(
            trace_id=selected_trace_id,
            sink=selected_sink,
            parent_span_id=None,
        )
    )
    try:
        with workflow_span(name, attributes=attributes):
            yield selected_trace_id
    finally:
        _TRACE_CONTEXT.reset(token)


@contextmanager
def workflow_span(
    name: str,
    *,
    attributes: Mapping[str, TraceAttributeValue] | None = None,
) -> Iterator[None]:
    """Record one child span only when a workflow trace is active."""

    context = _TRACE_CONTEXT.get()
    if context is None:
        yield
        return

    safe_name = _validated_name(name)
    safe_attributes = _validated_attributes(attributes or {})
    span_id = uuid4()
    started_at = datetime.now(timezone.utc)
    started_at_monotonic = perf_counter()
    token = _TRACE_CONTEXT.set(
        _TraceContext(
            trace_id=context.trace_id,
            sink=context.sink,
            parent_span_id=span_id,
        )
    )
    outcome = "succeeded"
    try:
        yield
    except Exception:
        outcome = "failed"
        raise
    finally:
        _TRACE_CONTEXT.reset(token)
        context.sink.record(
            WorkflowTraceSpan(
                trace_id=context.trace_id,
                span_id=span_id,
                parent_span_id=context.parent_span_id,
                name=safe_name,
                started_at=started_at,
                duration_ms=round((perf_counter() - started_at_monotonic) * 1_000, 3),
                outcome=outcome,
                attributes=safe_attributes,
            )
        )


def traced(name: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Wrap a synchronous boundary in a span without changing its contract."""

    _validated_name(name)

    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            with workflow_span(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate


def _validated_name(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_TRACE_NAME_LENGTH
    ):
        raise WorkflowTraceRejected(
            "Workflow span names must be bounded canonical text"
        )
    return value


def _validated_attributes(
    attributes: Mapping[str, TraceAttributeValue],
) -> dict[str, TraceAttributeValue]:
    result: dict[str, TraceAttributeValue] = {}
    for key, value in attributes.items():
        if (
            not isinstance(key, str)
            or not key
            or key != key.strip()
            or len(key) > MAX_TRACE_ATTRIBUTE_KEY_LENGTH
        ):
            raise WorkflowTraceRejected("Workflow trace attribute keys must be bounded")
        if any(
            fragment in key.casefold()
            for fragment in FORBIDDEN_TRACE_ATTRIBUTE_KEY_FRAGMENTS
        ):
            raise WorkflowTraceRejected(
                "Workflow trace attribute keys must not name sensitive content"
            )
        if isinstance(value, str):
            if len(value) > MAX_TRACE_ATTRIBUTE_VALUE_LENGTH:
                raise WorkflowTraceRejected(
                    "Workflow trace string attribute values must be bounded"
                )
        elif not isinstance(value, (int, float, bool)):
            raise WorkflowTraceRejected(
                "Workflow trace attributes must be scalar safe metadata"
            )
        elif isinstance(value, float) and not isfinite(value):
            raise WorkflowTraceRejected(
                "Workflow trace numeric attribute values must be finite"
            )
        result[key] = value
    return result
