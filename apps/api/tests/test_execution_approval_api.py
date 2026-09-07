from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import socket
from urllib import request as urllib_request
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.citations import (
    Citation,
    CitationUnavailable,
    SourceLocation,
    UnavailableCitationRepository,
)
from ai_qa_copilot_api.execution_approvals import (
    SqlAlchemyExecutionApprovalRepository,
    UnavailableExecutionApprovalRepository,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import Base, Project


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000811")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000812")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000813")

PLAN_REVIEW_PATH = f"/projects/{PROJECT_ID}/execution-plan-reviews"
APPROVAL_PATH = f"/projects/{PROJECT_ID}/execution-approvals"


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


def generated_test_case_payload() -> dict[str, object]:
    return {
        "schema_version": "generated-test-case/v1",
        "id": "00000000-0000-0000-0000-000000000814",
        "title": "Create a synthetic order",
        "kind": "positive",
        "source_finding_id": "00000000-0000-0000-0000-000000000815",
        "citation_ids": [str(CITATION_ID)],
        "request": {
            "method": "POST",
            "path": "/orders",
            "query": [],
            "headers": [],
            "json_body": {"quantity": 2},
        },
        "assertions": [
            {
                "target": "status_code",
                "selector": None,
                "operator": "equals",
                "expected_value": 201,
            }
        ],
    }


class FakeProjectRepository:
    def __init__(self) -> None:
        self.project = Project(
            id=PROJECT_ID,
            name="Execution approval project",
            description=None,
            created_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
            archived_at=None,
        )

    def create(self, *, name: str, description: str | None) -> Project:
        del name, description
        raise AssertionError("EXEC-004 must not create projects")

    def list_active(self) -> list[Project]:
        return [self.project]

    def get(self, project_id: UUID) -> Project | None:
        return self.project if project_id == PROJECT_ID else None

    def archive(self, project_id: UUID) -> Project | None:
        del project_id
        raise AssertionError("EXEC-004 must not archive projects")


class FakeCitationRepository(UnavailableCitationRepository):
    def __init__(
        self,
        *,
        available_project_id: UUID = PROJECT_ID,
        unavailable: bool = False,
    ) -> None:
        self.available_project_id = available_project_id
        self.unavailable = unavailable
        self.lookups: list[tuple[UUID, UUID]] = []

    def create_from_selected_candidate(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_id: UUID,
    ) -> Citation:
        del project_id, retrieval_trace_id, document_chunk_id
        raise AssertionError("EXEC-004 must not create citations")

    def get_for_project(
        self,
        *,
        project_id: UUID,
        citation_id: UUID,
    ) -> Citation | None:
        self.lookups.append((project_id, citation_id))
        if self.unavailable:
            raise CitationUnavailable
        if project_id != self.available_project_id or citation_id != CITATION_ID:
            return None

        return Citation(
            id=CITATION_ID,
            project_id=PROJECT_ID,
            retrieval_trace_id=UUID("00000000-0000-0000-0000-000000000816"),
            document_chunk_id=UUID("00000000-0000-0000-0000-000000000817"),
            document_version_id=UUID("00000000-0000-0000-0000-000000000818"),
            source_location=SourceLocation(
                id=UUID("00000000-0000-0000-0000-000000000819"),
                location_kind="markdown_lines",
                heading="Orders",
                line_start=1,
                line_end=2,
                page_start=None,
                page_end=None,
                json_pointer=None,
            ),
            document_type="markdown",
            display_name="requirements.md",
            passage="Orders must be creatable.",
            created_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
        )


def client(
    tmp_path: Path,
    *,
    citation_repository: FakeCitationRepository | None = None,
    auth_settings: AuthSettings | None = None,
    unavailable_approvals: bool = False,
) -> tuple[TestClient, FakeCitationRepository, Engine]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'approvals.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    citations = citation_repository or FakeCitationRepository()
    approvals = (
        UnavailableExecutionApprovalRepository()
        if unavailable_approvals
        else SqlAlchemyExecutionApprovalRepository(sessions)
    )
    app = create_app(
        auth_settings or local_bypass_settings(),
        project_repository=FakeProjectRepository(),
        citation_repository=citations,
        execution_approval_repository=approvals,
    )
    return TestClient(app), citations, engine


def reviewed_plan_hash(http: TestClient) -> str:
    response = http.post(
        PLAN_REVIEW_PATH,
        json={
            "generated_test_case": generated_test_case_payload(),
            "target_id": "synthetic-order-api",
        },
    )

    assert response.status_code == 200
    plan_hash = response.json()["plan_hash"]
    assert isinstance(plan_hash, str)
    return plan_hash


def approval_payload(
    expected_plan_hash: str,
    *,
    generated_test_case: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "generated_test_case": generated_test_case or generated_test_case_payload(),
        "target_id": "synthetic-order-api",
        "expected_plan_hash": expected_plan_hash,
        "comment": "Approved for the future restricted worker.",
    }


def test_owner_can_create_a_durable_plan_bound_approval(tmp_path: Path) -> None:
    api_client, citations, engine = client(tmp_path)

    try:
        with api_client as http:
            expected_plan_hash = reviewed_plan_hash(http)
            response = http.post(
                APPROVAL_PATH,
                json=approval_payload(expected_plan_hash),
            )

        assert response.status_code == 201
        body = response.json()
        assert UUID(body["id"])
        assert body["project_id"] == str(PROJECT_ID)
        assert UUID(body["plan_id"])
        assert body["plan_hash"] == expected_plan_hash
        assert body["approver_id"] == "local-development-owner"
        assert body["approver_authentication_source"] == "local_bypass"
        assert body["consumed_at"] is None

        approved_at = datetime.fromisoformat(body["approved_at"])
        expires_at = datetime.fromisoformat(body["expires_at"])
        assert expires_at - approved_at == timedelta(minutes=10)
        assert UUID(response.headers["X-Correlation-ID"])
        assert citations.lookups == [
            (PROJECT_ID, CITATION_ID),
            (PROJECT_ID, CITATION_ID),
        ]
    finally:
        engine.dispose()


def test_changed_plan_material_is_rejected_against_the_reviewed_hash(
    tmp_path: Path,
) -> None:
    api_client, _, engine = client(tmp_path)
    changed_payload = generated_test_case_payload()
    request = changed_payload["request"]
    assert isinstance(request, dict)
    request["json_body"] = {"quantity": 3}

    try:
        with api_client as http:
            expected_plan_hash = reviewed_plan_hash(http)
            response = http.post(
                APPROVAL_PATH,
                json=approval_payload(
                    expected_plan_hash,
                    generated_test_case=changed_payload,
                ),
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": ("Expected plan hash does not match the rebuilt immutable plan")
        }
        assert UUID(response.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_duplicate_approval_for_the_same_plan_is_rejected(tmp_path: Path) -> None:
    api_client, _, engine = client(tmp_path)

    try:
        with api_client as http:
            expected_plan_hash = reviewed_plan_hash(http)
            first = http.post(
                APPROVAL_PATH,
                json=approval_payload(expected_plan_hash),
            )
            duplicate = http.post(
                APPROVAL_PATH,
                json=approval_payload(expected_plan_hash),
            )

        assert first.status_code == 201
        assert duplicate.status_code == 409
        assert duplicate.json() == {
            "detail": "An approval already exists for this immutable plan"
        }
        assert UUID(duplicate.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_foreign_citation_is_rejected_before_approval_persistence(
    tmp_path: Path,
) -> None:
    api_client, citations, engine = client(
        tmp_path,
        citation_repository=FakeCitationRepository(
            available_project_id=OTHER_PROJECT_ID
        ),
    )

    try:
        with api_client as http:
            response = http.post(
                APPROVAL_PATH,
                json=approval_payload("0" * 64),
            )

        assert response.status_code == 404
        assert response.json() == {"detail": "Citation not found"}
        assert citations.lookups == [(PROJECT_ID, CITATION_ID)]
        assert UUID(response.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_invalid_proposal_is_rejected_before_citation_or_approval_work(
    tmp_path: Path,
) -> None:
    api_client, citations, engine = client(tmp_path)
    invalid_payload = generated_test_case_payload()
    invalid_payload["request"] = {"method": "POST"}

    try:
        with api_client as http:
            response = http.post(
                APPROVAL_PATH,
                json=approval_payload(
                    "0" * 64,
                    generated_test_case=invalid_payload,
                ),
            )

        assert response.status_code == 400
        assert citations.lookups == []
        assert UUID(response.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_approval_route_fails_closed_when_persistence_is_unavailable(
    tmp_path: Path,
) -> None:
    api_client, _, engine = client(tmp_path, unavailable_approvals=True)

    try:
        with api_client as http:
            expected_plan_hash = reviewed_plan_hash(http)
            response = http.post(
                APPROVAL_PATH,
                json=approval_payload(expected_plan_hash),
            )

        assert response.status_code == 503
        assert response.json() == {
            "detail": "Execution approval service is temporarily unavailable"
        }
        assert UUID(response.headers["X-Correlation-ID"])
    finally:
        engine.dispose()


def test_approval_route_requires_owner_authentication(tmp_path: Path) -> None:
    api_client, _, engine = client(
        tmp_path,
        auth_settings=AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=None,
        ),
    )

    try:
        with api_client as http:
            response = http.post(
                APPROVAL_PATH,
                json=approval_payload("0" * 64),
            )

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
    finally:
        engine.dispose()


def test_approval_creation_performs_no_dns_or_outbound_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client, _, engine = client(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("EXEC-004 must not perform network I/O")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(urllib_request, "urlopen", forbidden)

    try:
        with api_client as http:
            expected_plan_hash = reviewed_plan_hash(http)
            response = http.post(
                APPROVAL_PATH,
                json=approval_payload(expected_plan_hash),
            )

        assert response.status_code == 201
    finally:
        engine.dispose()
