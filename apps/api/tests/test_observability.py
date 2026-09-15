from __future__ import annotations

import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from collections.abc import Mapping
from typing import cast

from ai_qa_copilot_api.audit import AuthorizationAuditEvent, AuthorizationAuditSink
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.observability import (
    StructuredLoggingTraceSink,
    WorkflowTraceRejected,
    WorkflowTraceSpan,
    WorkflowTraceSink,
    current_trace_id,
    traced,
    workflow_span,
    workflow_trace,
    TraceAttributeValue,
)


TRACE_ID = UUID("00000000-0000-0000-0000-000000000901")


class RecordingTraceSink(WorkflowTraceSink):
    def __init__(self) -> None:
        self.spans: list[WorkflowTraceSpan] = []

    def record(self, span: WorkflowTraceSpan) -> None:
        self.spans.append(span)


class RecordingAuthorizationAuditSink(AuthorizationAuditSink):
    def __init__(self) -> None:
        self.events: list[AuthorizationAuditEvent] = []

    def record(self, event: AuthorizationAuditEvent) -> None:
        self.events.append(event)


def test_trace_records_parent_child_relationship_and_resets_context() -> None:
    sink = RecordingTraceSink()

    with workflow_trace(trace_id=TRACE_ID, sink=sink, name="api.request"):
        assert current_trace_id() == TRACE_ID
        with workflow_span("retrieval", attributes={"candidate_count": 3}):
            assert current_trace_id() == TRACE_ID

    assert current_trace_id() is None
    assert [span.name for span in sink.spans] == ["retrieval", "api.request"]
    retrieval, request = sink.spans
    assert retrieval.trace_id == TRACE_ID
    assert retrieval.parent_span_id == request.span_id
    assert retrieval.attributes == {"candidate_count": 3}
    assert request.parent_span_id is None
    assert all(span.outcome == "succeeded" for span in sink.spans)


def test_trace_marks_failure_without_retaining_exception_text() -> None:
    sink = RecordingTraceSink()

    with pytest.raises(RuntimeError, match="synthetic-secret"):
        with workflow_trace(trace_id=TRACE_ID, sink=sink):
            with workflow_span("execution"):
                raise RuntimeError("synthetic-secret")

    assert [span.outcome for span in sink.spans] == ["failed", "failed"]
    assert all(
        "synthetic-secret" not in json.dumps(span.as_dict()) for span in sink.spans
    )


@pytest.mark.parametrize(
    ("attributes", "expected_error"),
    [
        (
            {"candidate_count": {"nested": "value"}},
            "must be scalar safe metadata",
        ),
        (
            {"route": "x" * 257},
            "string attribute values must be bounded",
        ),
        (
            {"authorization": "credential-value"},
            "must not name sensitive content",
        ),
        (
            {"duration_ms": float("inf")},
            "numeric attribute values must be finite",
        ),
    ],
)
def test_trace_rejects_invalid_attributes(
    attributes: dict[str, object],
    expected_error: str,
) -> None:
    sink = RecordingTraceSink()

    # Intentionally bypass static typing to test runtime rejection.
    invalid_attributes = cast(Mapping[str, TraceAttributeValue], attributes)

    with pytest.raises(WorkflowTraceRejected, match=expected_error):
        with workflow_trace(
            trace_id=TRACE_ID,
            sink=sink,
            attributes=invalid_attributes,
        ):
            pytest.fail("Invalid trace attributes were accepted")

    assert sink.spans == []
    assert current_trace_id() is None


def test_traced_decorator_creates_a_child_span() -> None:
    sink = RecordingTraceSink()

    @traced("approval")
    def approve() -> str:
        return "approved"

    with workflow_trace(trace_id=TRACE_ID, sink=sink):
        assert approve() == "approved"

    assert [span.name for span in sink.spans] == ["approval", "workflow"]


def test_structured_logging_sink_emits_canonical_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = StructuredLoggingTraceSink()
    caplog.set_level(logging.INFO)

    with workflow_trace(trace_id=TRACE_ID, sink=sink, attributes={"route": "/health"}):
        pass

    payload = caplog.records[-1].message.removeprefix("workflow_trace=")
    parsed = json.loads(payload)
    assert parsed["trace_id"] == str(TRACE_ID)
    assert parsed["attributes"] == {"route": "/health"}


def test_api_request_emits_one_root_trace_and_server_owned_header() -> None:
    sink = RecordingTraceSink()
    app = create_app(
        AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=None,
        ),
        workflow_trace_sink=sink,
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert len(sink.spans) == 1
    span = sink.spans[0]
    assert span.name == "api.request"
    assert response.headers["X-Correlation-ID"] == str(span.trace_id)
    assert span.attributes == {"http.method": "GET", "http.path": "/health"}


def test_api_authorization_audit_reuses_the_request_trace_identifier() -> None:
    trace_sink = RecordingTraceSink()
    audit_sink = RecordingAuthorizationAuditSink()
    app = create_app(
        AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=True,
            cognito=None,
        ),
        authorization_audit_sink=audit_sink,
        workflow_trace_sink=trace_sink,
    )

    with TestClient(app) as client:
        response = client.get("/projects")

    assert response.status_code == 503
    assert len(audit_sink.events) == 1
    assert len(trace_sink.spans) == 1
    assert audit_sink.events[0].correlation_id == trace_sink.spans[0].trace_id
    assert response.headers["X-Correlation-ID"] == str(trace_sink.spans[0].trace_id)
