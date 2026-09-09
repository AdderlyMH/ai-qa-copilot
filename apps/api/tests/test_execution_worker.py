from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
from typing import cast
from uuid import UUID

import pytest

from ai_qa_copilot_api.documents import ExecutionJobState, ExecutionResultOutcome
from ai_qa_copilot_api.execution_approvals import ExecutionApproval
from ai_qa_copilot_api.execution_jobs import ClaimedExecutionJob, ExecutionJob
from ai_qa_copilot_api.execution_results import (
    ExecutionResultPayload,
    ExecutionResultUnavailable,
    StoredExecutionResult,
)
from ai_qa_copilot_api.execution_worker import (
    ExecutionWorkerInvariantError,
    RestrictedExecutionWorker,
)
from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    HttpMethod,
)
from ai_qa_copilot_api.restricted_execution import (
    AssertionResult,
    ExecutionFailureCode,
    ExecutionOutcome,
    ExecutionResult,
    RedactedRequestEvidence,
    RedactedResponseEvidence,
)


NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000951")
APPROVAL_ID = UUID("00000000-0000-0000-0000-000000000952")
JOB_ID = UUID("00000000-0000-0000-0000-000000000953")
RESULT_ID = UUID("00000000-0000-0000-0000-000000000954")


@dataclass
class FakeJobClaimer:
    claimed: ClaimedExecutionJob | None
    calls: int = 0

    def claim_next(self) -> ClaimedExecutionJob | None:
        self.calls += 1
        return self.claimed


@dataclass
class FakeExecutor:
    result: ExecutionResult | None = None
    error: Exception | None = None
    calls: int = 0

    def execute(self, claimed: ClaimedExecutionJob) -> ExecutionResult:
        assert claimed.job.id == JOB_ID
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@dataclass
class FakeResultRecorder:
    error: Exception | None = None
    calls: int = 0
    payloads: list[ExecutionResultPayload] = field(default_factory=list)

    def record(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        payload: ExecutionResultPayload,
    ) -> StoredExecutionResult:
        assert project_id == PROJECT_ID
        assert job_id == JOB_ID
        self.calls += 1
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error

        return StoredExecutionResult(
            id=RESULT_ID,
            execution_job_id=job_id,
            outcome=payload.outcome,
            failure_code=payload.failure_code,
            assertion_results_json=payload.assertion_results_json,
            request_evidence_json=payload.request_evidence_json,
            response_evidence_json=payload.response_evidence_json,
            transport_send_count=payload.transport_send_count,
            recorded_at=NOW,
        )


def claimed_job() -> ClaimedExecutionJob:
    job = ExecutionJob(
        id=JOB_ID,
        project_id=PROJECT_ID,
        execution_approval_id=APPROVAL_ID,
        plan_id=UUID("00000000-0000-0000-0000-000000000955"),
        plan_hash="a" * 64,
        state=ExecutionJobState.RUNNING,
        created_at=NOW,
        started_at=NOW,
        finished_at=None,
        cancel_requested_at=None,
        cancelled_at=None,
    )
    return ClaimedExecutionJob(
        job=job,
        approval=cast(ExecutionApproval, object()),
    )


def execution_result(
    *,
    outcome: ExecutionOutcome = ExecutionOutcome.SUCCEEDED,
    error_code: ExecutionFailureCode | None = None,
) -> ExecutionResult:
    if outcome is not ExecutionOutcome.SUCCEEDED and error_code is None:
        error_code = ExecutionFailureCode.ASSERTIONS_FAILED

    return ExecutionResult(
        job_id=JOB_ID,
        outcome=outcome,
        assertion_results=(
            AssertionResult(
                target=AssertionTarget.STATUS_CODE,
                selector=None,
                operator=AssertionOperator.EQUALS,
                passed=outcome is ExecutionOutcome.SUCCEEDED,
            ),
        ),
        request_evidence=RedactedRequestEvidence(
            method=HttpMethod.POST,
            url="https://ai-qa-sandbox.onrender.com/api/orders?source=worker",
            headers=(("Content-Type", "application/json"),),
            json_body={"product_id": "demo", "quantity": 2},
        ),
        response_evidence=RedactedResponseEvidence(
            status_code=201,
            headers=(("Content-Type", "application/json"),),
            json_body={"order_id": "ORDER-1001", "status": "created"},
            body_bytes=46,
            body_sha256="a" * 64,
            elapsed_ms=20,
        ),
        error_code=error_code,
        error_message=None,
        transport_send_count=1,
    )


def worker(
    *,
    jobs: FakeJobClaimer,
    executor: FakeExecutor,
    results: FakeResultRecorder,
) -> RestrictedExecutionWorker:
    return RestrictedExecutionWorker(
        jobs=jobs,
        executor=executor,
        results=results,
    )


def test_worker_is_idle_when_the_queue_has_no_claimable_job() -> None:
    jobs = FakeJobClaimer(claimed=None)
    executor = FakeExecutor()
    results = FakeResultRecorder()

    run = worker(jobs=jobs, executor=executor, results=results).run_once()

    assert run.claimed_job_id is None
    assert run.execution_result is None
    assert run.stored_result is None
    assert jobs.calls == 1
    assert executor.calls == 0
    assert results.calls == 0


def test_worker_executes_and_records_one_claimed_job_once() -> None:
    jobs = FakeJobClaimer(claimed=claimed_job())
    executor = FakeExecutor(result=execution_result())
    results = FakeResultRecorder()

    run = worker(jobs=jobs, executor=executor, results=results).run_once()

    assert run.claimed_job_id == JOB_ID
    assert run.execution_result is executor.result
    assert run.stored_result is not None
    assert run.stored_result.outcome is ExecutionResultOutcome.SUCCEEDED
    assert executor.calls == 1
    assert results.calls == 1

    payload = results.payloads[0]
    assert payload.outcome is ExecutionResultOutcome.SUCCEEDED
    assert payload.failure_code is None
    assert payload.transport_send_count == 1
    assert json.loads(payload.assertion_results_json) == [
        {
            "operator": "equals",
            "passed": True,
            "selector": None,
            "target": "status_code",
        }
    ]
    assert json.loads(payload.request_evidence_json or "{}") == {
        "headers": [["Content-Type", "application/json"]],
        "json_body": {"product_id": "demo", "quantity": 2},
        "method": "POST",
        "url": "https://ai-qa-sandbox.onrender.com/api/orders?source=worker",
    }


@pytest.mark.parametrize(
    ("outcome", "error_code", "expected"),
    [
        (
            ExecutionOutcome.FAILED,
            ExecutionFailureCode.ASSERTIONS_FAILED,
            ExecutionResultOutcome.FAILED,
        ),
        (
            ExecutionOutcome.CANCELLED,
            ExecutionFailureCode.CANCELLED,
            ExecutionResultOutcome.CANCELLED,
        ),
    ],
)
def test_worker_preserves_failed_and_cancelled_terminal_outcomes(
    outcome: ExecutionOutcome,
    error_code: ExecutionFailureCode,
    expected: ExecutionResultOutcome,
) -> None:
    jobs = FakeJobClaimer(claimed=claimed_job())
    executor = FakeExecutor(
        result=execution_result(
            outcome=outcome,
            error_code=error_code,
        )
    )
    results = FakeResultRecorder()

    worker(jobs=jobs, executor=executor, results=results).run_once()

    payload = results.payloads[0]
    assert payload.outcome is expected
    assert payload.failure_code == error_code.value


def test_worker_redacts_sensitive_evidence_again_before_persistence() -> None:
    unsafe_result = replace(
        execution_result(),
        request_evidence=RedactedRequestEvidence(
            method=HttpMethod.POST,
            url=("https://ai-qa-sandbox.onrender.com/api/orders?token=request-secret"),
            headers=(("Authorization", "request-secret"),),
            json_body={"token": "request-secret"},
        ),
        response_evidence=RedactedResponseEvidence(
            status_code=201,
            headers=(("Set-Cookie", "response-secret"),),
            json_body={"nested": {"password": "response-secret"}},
            body_bytes=20,
            body_sha256="b" * 64,
            elapsed_ms=20,
        ),
    )
    jobs = FakeJobClaimer(claimed=claimed_job())
    executor = FakeExecutor(result=unsafe_result)
    results = FakeResultRecorder()

    worker(jobs=jobs, executor=executor, results=results).run_once()

    request = results.payloads[0].request_evidence_json or ""
    response = results.payloads[0].response_evidence_json or ""
    stored_evidence = f"{request}{response}"

    assert "request-secret" not in stored_evidence
    assert "response-secret" not in stored_evidence
    assert "[REDACTED]" in stored_evidence


def test_worker_refuses_a_result_for_a_different_job_without_recording() -> None:
    mismatched = replace(
        execution_result(),
        job_id=UUID("00000000-0000-0000-0000-000000000956"),
    )
    jobs = FakeJobClaimer(claimed=claimed_job())
    executor = FakeExecutor(result=mismatched)
    results = FakeResultRecorder()

    with pytest.raises(ExecutionWorkerInvariantError):
        worker(jobs=jobs, executor=executor, results=results).run_once()

    assert executor.calls == 1
    assert results.calls == 0


def test_worker_does_not_retry_when_the_executor_raises() -> None:
    jobs = FakeJobClaimer(claimed=claimed_job())
    executor = FakeExecutor(error=RuntimeError("unexpected executor failure"))
    results = FakeResultRecorder()

    with pytest.raises(RuntimeError, match="unexpected executor failure"):
        worker(jobs=jobs, executor=executor, results=results).run_once()

    assert executor.calls == 1
    assert results.calls == 0


def test_worker_does_not_retry_when_terminal_persistence_fails() -> None:
    jobs = FakeJobClaimer(claimed=claimed_job())
    executor = FakeExecutor(result=execution_result())
    results = FakeResultRecorder(error=ExecutionResultUnavailable())

    with pytest.raises(ExecutionResultUnavailable):
        worker(jobs=jobs, executor=executor, results=results).run_once()

    assert executor.calls == 1
    assert results.calls == 1
