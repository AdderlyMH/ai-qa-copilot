from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.audit import AUTHORIZATION_AUDIT_LOGGER
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.documents import (
    ExecutionResultOutcome,
    ExecutionResultRecord,
)
from ai_qa_copilot_api.execution_approvals import (
    ExecutionApproval,
    SqlAlchemyExecutionApprovalRepository,
)
from ai_qa_copilot_api.execution_jobs import (
    SqlAlchemyExecutionJobQueue,
    UnavailableExecutionJobQueue,
)
from ai_qa_copilot_api.execution_plans import (
    ExecutionPlanV1,
    build_execution_plan,
)
from ai_qa_copilot_api.execution_results import (
    ExecutionResultPayload,
    SqlAlchemyExecutionResultRepository,
)
from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    GeneratedAssertionV1,
    GeneratedTestCaseV1,
    GeneratedTestKind,
    HttpMethod,
    RequestTemplateV1,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import Base, Project


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000971")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000972")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000973")

EXECUTION_JOBS_PATH = f"/projects/{PROJECT_ID}/execution-jobs"


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


class FakeProjectRepository:
    def __init__(self) -> None:
        self.project = Project(
            id=PROJECT_ID,
            name="Execution job API project",
            description=None,
            created_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
            archived_at=None,
        )

    def create(self, *, name: str, description: str | None) -> Project:
        del name, description
        raise AssertionError("Execution-job API tests do not create projects")

    def list_active(self) -> list[Project]:
        return [self.project]

    def get(self, project_id: UUID) -> Project | None:
        return self.project if project_id == PROJECT_ID else None

    def archive(self, project_id: UUID) -> Project | None:
        del project_id
        raise AssertionError("Execution-job API tests do not archive projects")


def client(
    tmp_path: Path,
    *,
    unavailable_jobs: bool = False,
) -> tuple[
    TestClient,
    SqlAlchemyExecutionApprovalRepository,
    SqlAlchemyExecutionJobQueue | None,
    Engine,
]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'execution-jobs.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)

    approvals = SqlAlchemyExecutionApprovalRepository(sessions)
    jobs = None if unavailable_jobs else SqlAlchemyExecutionJobQueue(sessions)
    app = create_app(
        local_bypass_settings(),
        project_repository=FakeProjectRepository(),
        execution_approval_repository=approvals,
        execution_job_queue=(
            UnavailableExecutionJobQueue() if unavailable_jobs else jobs
        ),
        execution_result_repository=SqlAlchemyExecutionResultRepository(sessions),
    )
    return TestClient(app), approvals, jobs, engine


def immutable_plan() -> ExecutionPlanV1:
    test_case = GeneratedTestCaseV1(
        id=UUID("00000000-0000-0000-0000-000000000974"),
        title="Create one sandbox order",
        kind=GeneratedTestKind.POSITIVE,
        source_finding_id=UUID("00000000-0000-0000-0000-000000000975"),
        citation_ids=(CITATION_ID,),
        request=RequestTemplateV1(
            method=HttpMethod.POST,
            path="/api/orders",
            query=(),
            headers=(),
            json_body={"product_id": "demo", "quantity": 2},
        ),
        assertions=(
            GeneratedAssertionV1(
                target=AssertionTarget.STATUS_CODE,
                selector=None,
                operator=AssertionOperator.EQUALS,
                expected_value=201,
            ),
        ),
    )
    return build_execution_plan(
        generated_test_case=test_case,
        target_id="synthetic-order-api",
    )


def seed_approval(
    approvals: SqlAlchemyExecutionApprovalRepository,
) -> ExecutionApproval:
    plan = immutable_plan()
    return approvals.create(
        project_id=PROJECT_ID,
        plan=plan,
        approver_id="local-development-owner",
        approver_authentication_source="local_bypass",
        comment=None,
    )


def test_owner_can_queue_read_and_cancel_an_approved_execution_job(
    tmp_path: Path,
) -> None:
    api_client, approvals, _, engine = client(tmp_path)
    approval = seed_approval(approvals)
    queue_path = (
        f"/projects/{PROJECT_ID}/execution-approvals/{approval.id}/execution-jobs"
    )

    try:
        with api_client as http:
            created = http.post(queue_path)
            assert created.status_code == 201
            created_body = created.json()
            job_id = UUID(created_body["id"])

            read = http.get(f"{EXECUTION_JOBS_PATH}/{job_id}")
            cancelled = http.delete(f"{EXECUTION_JOBS_PATH}/{job_id}")

        assert created_body["project_id"] == str(PROJECT_ID)
        assert created_body["execution_approval_id"] == str(approval.id)
        assert created_body["plan_id"] == str(approval.plan.id)
        assert created_body["plan_hash"] == approval.plan.plan_hash
        assert created_body["state"] == "queued"
        assert created_body["result"] is None

        assert read.status_code == 200
        assert read.json()["id"] == str(job_id)
        assert read.json()["state"] == "queued"
        assert read.json()["result"] is None

        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"
        assert cancelled.json()["cancel_requested_at"] is not None
        assert cancelled.json()["cancelled_at"] is not None
    finally:
        engine.dispose()


def test_enqueue_is_idempotently_bound_to_the_approval(
    tmp_path: Path,
) -> None:
    api_client, approvals, _, engine = client(tmp_path)
    approval = seed_approval(approvals)
    queue_path = (
        f"/projects/{PROJECT_ID}/execution-approvals/{approval.id}/execution-jobs"
    )

    try:
        with api_client as http:
            first = http.post(queue_path)
            repeated = http.post(queue_path)

        assert first.status_code == 201
        assert repeated.status_code == 201
        assert repeated.json()["id"] == first.json()["id"]
        assert repeated.json()["execution_approval_id"] == str(approval.id)
    finally:
        engine.dispose()


def test_job_route_does_not_leak_a_job_outside_its_project(
    tmp_path: Path,
) -> None:
    api_client, approvals, _, engine = client(tmp_path)
    approval = seed_approval(approvals)
    queue_path = (
        f"/projects/{PROJECT_ID}/execution-approvals/{approval.id}/execution-jobs"
    )

    try:
        with api_client as http:
            created = http.post(queue_path)
            job_id = UUID(created.json()["id"])
            response = http.get(f"/projects/{OTHER_PROJECT_ID}/execution-jobs/{job_id}")

        assert response.status_code == 404
        assert response.json() == {"detail": "Project not found"}
        assert UUID(response.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_unavailable_job_storage_fails_closed_without_execution(
    tmp_path: Path,
) -> None:
    api_client, approvals, _, engine = client(tmp_path, unavailable_jobs=True)
    approval = seed_approval(approvals)
    queue_path = (
        f"/projects/{PROJECT_ID}/execution-approvals/{approval.id}/execution-jobs"
    )

    try:
        with api_client as http:
            response = http.post(queue_path)

        assert response.status_code == 503
        assert response.json() == {
            "detail": "Execution job service is temporarily unavailable"
        }
        assert UUID(response.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_job_read_includes_the_already_redacted_durable_terminal_result(
    tmp_path: Path,
) -> None:
    api_client, approvals, jobs, engine = client(tmp_path)
    assert jobs is not None
    approval = seed_approval(approvals)
    queue_path = (
        f"/projects/{PROJECT_ID}/execution-approvals/{approval.id}/execution-jobs"
    )
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    results = SqlAlchemyExecutionResultRepository(sessions)

    try:
        with api_client as http:
            created = http.post(queue_path)
            assert created.status_code == 201
            job_id = UUID(created.json()["id"])

            claimed = jobs.claim_next()
            assert claimed is not None
            stored = results.record(
                project_id=PROJECT_ID,
                job_id=job_id,
                payload=ExecutionResultPayload(
                    outcome=ExecutionResultOutcome.SUCCEEDED,
                    failure_code=None,
                    assertion_results_json="[]",
                    request_evidence_json='{"headers":[],"method":"POST"}',
                    response_evidence_json=(
                        '{"body_bytes":0,"headers":[],"status_code":201}'
                    ),
                    transport_send_count=0,
                ),
            )

            read = http.get(f"{EXECUTION_JOBS_PATH}/{job_id}")

        assert read.status_code == 200
        body = read.json()
        assert body["state"] == "succeeded"
        assert body["result"] is not None
        assert body["result"]["id"] == str(stored.id)
        assert body["result"]["execution_job_id"] == str(job_id)
        assert body["result"]["outcome"] == "succeeded"
        assert body["result"]["failure_code"] is None
        assert body["result"]["assertion_results_json"] == "[]"
        assert body["result"]["transport_send_count"] == 0
    finally:
        engine.dispose()


def test_owner_evidence_route_re_redacts_canaries_from_durable_display(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "exec-006-durable-display-canary"
    api_client, approvals, jobs, engine = client(tmp_path)
    assert jobs is not None
    approval = seed_approval(approvals)
    queue_path = (
        f"/projects/{PROJECT_ID}/execution-approvals/{approval.id}/execution-jobs"
    )
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)

    caplog.set_level(logging.INFO, logger=AUTHORIZATION_AUDIT_LOGGER)

    try:
        with api_client as http:
            created = http.post(queue_path)
            assert created.status_code == 201
            job_id = UUID(created.json()["id"])

            claimed = jobs.claim_next()
            assert claimed is not None
            assert claimed.job.id == job_id

            with sessions.begin() as session:
                session.add(
                    ExecutionResultRecord(
                        id=uuid4(),
                        execution_job_id=job_id,
                        outcome=ExecutionResultOutcome.SUCCEEDED.value,
                        failure_code=None,
                        assertion_results=[
                            {
                                "target": "status_code",
                                "operator": "equals",
                                "passed": True,
                                "token": canary,
                            }
                        ],
                        request_evidence={
                            "method": "POST",
                            "url": (f"https://example.test/orders?token={canary}"),
                            "headers": [
                                ["X-Api-Token", canary],
                                ["Accept", "application/json"],
                            ],
                            "json_body": {
                                "password": canary,
                                "quantity": 2,
                            },
                        },
                        response_evidence={
                            "status_code": 201,
                            "elapsed_ms": 37,
                            "headers": [
                                ["Set-Cookie", canary],
                                ["Content-Type", "application/json"],
                            ],
                            "json_body": {
                                "nested": {
                                    "secret": canary,
                                },
                                "order_id": "ORDER-1001",
                            },
                        },
                        transport_send_count=1,
                        recorded_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
                    )
                )

            evidence = http.get(f"{EXECUTION_JOBS_PATH}/{job_id}/evidence")

        assert evidence.status_code == 200
        body = evidence.json()
        assert canary not in json.dumps(body)
        assert canary not in caplog.text
        assert body["execution_job_id"] == str(job_id)
        assert body["outcome"] == "succeeded"
        assert body["response_status_code"] == 201
        assert body["response_elapsed_ms"] == 37
        assert body["assertion_results"][0]["token"] == "[REDACTED]"
        assert body["request_evidence"]["headers"][0] == [
            "X-Api-Token",
            "[REDACTED]",
        ]
        assert body["request_evidence"]["json_body"]["password"] == "[REDACTED]"
        assert body["response_evidence"]["headers"][0] == [
            "Set-Cookie",
            "[REDACTED]",
        ]
        assert (
            body["response_evidence"]["json_body"]["nested"]["secret"] == "[REDACTED]"
        )
        assert UUID(evidence.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_owner_can_read_deterministic_failure_analysis_without_root_cause(
    tmp_path: Path,
) -> None:
    api_client, approvals, jobs, engine = client(tmp_path)
    assert jobs is not None
    approval = seed_approval(approvals)
    queue_path = (
        f"/projects/{PROJECT_ID}/execution-approvals/{approval.id}/execution-jobs"
    )
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    results = SqlAlchemyExecutionResultRepository(sessions)

    try:
        with api_client as http:
            created = http.post(queue_path)
            assert created.status_code == 201
            job_id = UUID(created.json()["id"])

            claimed = jobs.claim_next()
            assert claimed is not None
            results.record(
                project_id=PROJECT_ID,
                job_id=job_id,
                payload=ExecutionResultPayload(
                    outcome=ExecutionResultOutcome.FAILED,
                    failure_code="assertions_failed",
                    assertion_results_json=(
                        '[{"operator":"equals","passed":false,'
                        '"selector":null,"target":"status_code"}]'
                    ),
                    request_evidence_json='{"headers":[],"method":"POST"}',
                    response_evidence_json=(
                        '{"elapsed_ms":41,"headers":[],"status_code":500}'
                    ),
                    transport_send_count=1,
                ),
            )

            analysis = http.get(f"{EXECUTION_JOBS_PATH}/{job_id}/failure-analysis")

        assert analysis.status_code == 200
        body = analysis.json()
        assert body["execution_job_id"] == str(job_id)
        assert body["outcome"] == "failed"
        assert body["failure_code"] == "assertions_failed"
        assert body["evidence_sufficiency"] == "insufficient_for_root_cause"
        assert body["root_cause"] is None
        assert [item["code"] for item in body["observations"]] == [
            "terminal_outcome",
            "recorded_failure_code",
            "transport_send_count",
            "response_status_code",
            "response_elapsed_ms",
            "failed_assertion_count",
        ]
        assert body["hypotheses"][0]["code"] == (
            "target_response_did_not_match_approved_expectations"
        )
        assert body["alternatives"][0]["code"] == "approved_expectations_may_be_stale"
        assert body["next_checks"][0]["code"] == (
            "compare_redacted_response_to_approved_plan"
        )
        assert UUID(analysis.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_successful_execution_has_no_failure_analysis(
    tmp_path: Path,
) -> None:
    api_client, approvals, jobs, engine = client(tmp_path)
    assert jobs is not None
    approval = seed_approval(approvals)
    queue_path = (
        f"/projects/{PROJECT_ID}/execution-approvals/{approval.id}/execution-jobs"
    )
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    results = SqlAlchemyExecutionResultRepository(sessions)

    try:
        with api_client as http:
            created = http.post(queue_path)
            assert created.status_code == 201
            job_id = UUID(created.json()["id"])

            claimed = jobs.claim_next()
            assert claimed is not None
            results.record(
                project_id=PROJECT_ID,
                job_id=job_id,
                payload=ExecutionResultPayload(
                    outcome=ExecutionResultOutcome.SUCCEEDED,
                    failure_code=None,
                    assertion_results_json="[]",
                    request_evidence_json='{"headers":[],"method":"POST"}',
                    response_evidence_json=(
                        '{"elapsed_ms":17,"headers":[],"status_code":201}'
                    ),
                    transport_send_count=1,
                ),
            )

            analysis = http.get(f"{EXECUTION_JOBS_PATH}/{job_id}/failure-analysis")

        assert analysis.status_code == 409
        assert analysis.json() == {
            "detail": "Execution failure analysis is not available for this result"
        }
        assert UUID(analysis.headers["X-Correlation-ID"])
    finally:
        engine.dispose()
