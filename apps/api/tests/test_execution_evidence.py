from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import UUID

import pytest

from ai_qa_copilot_api.documents import ExecutionResultOutcome
from ai_qa_copilot_api.execution_evidence import (
    ExecutionEvidenceViewRejected,
    execution_evidence_view_from_result,
)
from ai_qa_copilot_api.execution_results import StoredExecutionResult


JOB_ID = UUID("00000000-0000-0000-0000-000000000981")
RESULT_ID = UUID("00000000-0000-0000-0000-000000000982")
CANARY = "exec-006-canary-secret"


def stored_result(
    *,
    assertion_results_json: str = "[]",
    request_evidence_json: str | None = None,
    response_evidence_json: str | None = None,
) -> StoredExecutionResult:
    return StoredExecutionResult(
        id=RESULT_ID,
        execution_job_id=JOB_ID,
        outcome=ExecutionResultOutcome.SUCCEEDED,
        failure_code=None,
        assertion_results_json=assertion_results_json,
        request_evidence_json=request_evidence_json,
        response_evidence_json=response_evidence_json,
        transport_send_count=1,
        recorded_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )


def test_evidence_view_re_redacts_canaries_before_display() -> None:
    result = stored_result(
        assertion_results_json=json.dumps(
            [
                {
                    "target": "status_code",
                    "operator": "equals",
                    "passed": True,
                    "token": CANARY,
                }
            ]
        ),
        request_evidence_json=json.dumps(
            {
                "method": "POST",
                "url": f"https://example.test/orders?token={CANARY}",
                "headers": [
                    ["X-Api-Token", CANARY],
                    ["Accept", "application/json"],
                ],
                "json_body": {
                    "password": CANARY,
                    "quantity": 2,
                },
            }
        ),
        response_evidence_json=json.dumps(
            {
                "status_code": 201,
                "elapsed_ms": 37,
                "headers": [
                    ["Set-Cookie", CANARY],
                    ["Content-Type", "application/json"],
                ],
                "json_body": {
                    "order_id": "ORDER-1001",
                    "nested": {
                        "secret": CANARY,
                    },
                },
            }
        ),
    )

    view = execution_evidence_view_from_result(result)
    rendered = repr(view)

    assert CANARY not in rendered
    assert view.assertion_results[0]["token"] == "[REDACTED]"
    assert view.request_evidence == {
        "headers": [
            ["X-Api-Token", "[REDACTED]"],
            ["Accept", "application/json"],
        ],
        "json_body": {
            "password": "[REDACTED]",
            "quantity": 2,
        },
        "method": "POST",
        "url": "https://example.test/orders?token=%5BREDACTED%5D",
    }
    assert view.response_evidence == {
        "elapsed_ms": 37,
        "headers": [
            ["Set-Cookie", "[REDACTED]"],
            ["Content-Type", "application/json"],
        ],
        "json_body": {
            "nested": {
                "secret": "[REDACTED]",
            },
            "order_id": "ORDER-1001",
        },
        "status_code": 201,
    }
    assert view.response_status_code == 201
    assert view.response_elapsed_ms == 37


def test_evidence_view_rejects_malformed_input_without_echoing_canary() -> None:
    result = stored_result(
        request_evidence_json=f"not-json-{CANARY}",
    )

    with pytest.raises(ExecutionEvidenceViewRejected) as error:
        execution_evidence_view_from_result(result)

    assert CANARY not in str(error.value)
