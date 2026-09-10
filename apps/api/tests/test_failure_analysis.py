from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ai_qa_copilot_api.execution_evidence import ExecutionEvidenceView
from ai_qa_copilot_api.failure_analysis import (
    EvidenceSufficiency,
    ExecutionFailureAnalysisRejected,
    analyze_execution_failure,
)
from ai_qa_copilot_api.restricted_execution import ExecutionFailureCode


RESULT_ID = UUID("ebc8b7d6-0a3f-46b5-85f5-649683424ad6")
JOB_ID = UUID("8c5497a3-19f7-45bc-9e64-72c0ed45a45a")


def evidence(
    *,
    outcome: str = "failed",
    failure_code: str | None = ExecutionFailureCode.TRANSPORT_TIMEOUT.value,
    assertion_results: tuple[dict[str, object], ...] = (),
    response_status_code: int | None = None,
    response_elapsed_ms: int | None = None,
    transport_send_count: int = 1,
) -> ExecutionEvidenceView:
    response_evidence: dict[str, object] | None = None
    if response_status_code is not None or response_elapsed_ms is not None:
        response_evidence = {}
        if response_status_code is not None:
            response_evidence["status_code"] = response_status_code
        if response_elapsed_ms is not None:
            response_evidence["elapsed_ms"] = response_elapsed_ms

    return ExecutionEvidenceView(
        id=RESULT_ID,
        execution_job_id=JOB_ID,
        outcome=outcome,
        failure_code=failure_code,
        assertion_results=assertion_results,
        request_evidence={
            "method": "POST",
            "url": "https://ai-qa-sandbox.onrender.com/api/orders",
        },
        response_evidence=response_evidence,
        response_status_code=response_status_code,
        response_elapsed_ms=response_elapsed_ms,
        transport_send_count=transport_send_count,
        recorded_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )


def test_transport_failure_is_observed_but_never_asserted_as_root_cause() -> None:
    analysis = analyze_execution_failure(evidence())

    assert analysis.execution_job_id == JOB_ID
    assert analysis.failure_code is ExecutionFailureCode.TRANSPORT_TIMEOUT
    assert analysis.evidence_sufficiency is (
        EvidenceSufficiency.INSUFFICIENT_FOR_ROOT_CAUSE
    )
    assert analysis.root_cause is None
    assert [item.code for item in analysis.observations] == [
        "terminal_outcome",
        "recorded_failure_code",
        "transport_send_count",
    ]
    assert analysis.hypotheses[0].code == "transport_path_or_target_unavailable"
    assert analysis.alternatives[0].code == "transient_execution_environment_failure"
    assert analysis.next_checks[0].code == "inspect_target_and_transport_telemetry"


def test_assertion_failure_records_only_safe_deterministic_observations() -> None:
    analysis = analyze_execution_failure(
        evidence(
            failure_code=ExecutionFailureCode.ASSERTIONS_FAILED.value,
            assertion_results=(
                {
                    "target": "status_code",
                    "operator": "equals",
                    "passed": False,
                    "token": "[REDACTED]",
                },
            ),
            response_status_code=500,
            response_elapsed_ms=41,
        )
    )

    assert analysis.root_cause is None
    assert analysis.hypotheses[0].code == (
        "target_response_did_not_match_approved_expectations"
    )
    assert analysis.alternatives[0].code == "approved_expectations_may_be_stale"
    assert analysis.next_checks[0].code == (
        "compare_redacted_response_to_approved_plan"
    )
    assert [item.code for item in analysis.observations] == [
        "terminal_outcome",
        "recorded_failure_code",
        "transport_send_count",
        "response_status_code",
        "response_elapsed_ms",
        "failed_assertion_count",
    ]
    assert analysis.observations[-1].statement == (
        "1 deterministic assertion(s) were recorded as failed."
    )


def test_cancelled_execution_has_no_product_defect_claim() -> None:
    analysis = analyze_execution_failure(
        evidence(
            outcome="cancelled",
            failure_code=ExecutionFailureCode.CANCELLED.value,
            transport_send_count=0,
        )
    )

    assert analysis.root_cause is None
    assert analysis.hypotheses[0].code == "cancellation_requested_before_completion"
    assert analysis.alternatives[0].code == "operator_or_workflow_interruption"
    assert analysis.next_checks[0].code == "review_cancellation_audit_context"


@pytest.mark.parametrize(
    ("outcome", "failure_code"),
    [
        ("succeeded", None),
        ("failed", None),
        ("failed", "unknown_failure"),
    ],
)
def test_failure_analysis_rejects_results_without_a_supported_failure_basis(
    outcome: str,
    failure_code: str | None,
) -> None:
    with pytest.raises(ExecutionFailureAnalysisRejected):
        analyze_execution_failure(
            evidence(
                outcome=outcome,
                failure_code=failure_code,
            )
        )
