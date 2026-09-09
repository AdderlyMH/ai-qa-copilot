from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.citations import (
    Citation,
    CitationUnavailable,
    SourceLocation,
    UnavailableCitationRepository,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import Project


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000701")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000702")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000703")

PLAN_REVIEW_PATH = f"/projects/{PROJECT_ID}/execution-plan-reviews"


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


def generated_test_case_payload(
    *,
    citation_id: UUID = CITATION_ID,
) -> dict[str, object]:
    return {
        "schema_version": "generated-test-case/v1",
        "id": "00000000-0000-0000-0000-000000000704",
        "title": "Create a synthetic order",
        "kind": "positive",
        "source_finding_id": "00000000-0000-0000-0000-000000000705",
        "citation_ids": [str(citation_id)],
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
            name="Execution plan project",
            description=None,
            created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            archived_at=None,
        )

    def create(self, *, name: str, description: str | None) -> Project:
        del name, description
        raise AssertionError("EXEC-003 must not create projects")

    def list_active(self) -> list[Project]:
        return [self.project]

    def get(self, project_id: UUID) -> Project | None:
        return self.project if project_id == PROJECT_ID else None

    def archive(self, project_id: UUID) -> Project | None:
        del project_id
        raise AssertionError("EXEC-003 must not archive projects")


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
        raise AssertionError("EXEC-003 must not create citations")

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
            retrieval_trace_id=UUID("00000000-0000-0000-0000-000000000706"),
            document_chunk_id=UUID("00000000-0000-0000-0000-000000000707"),
            document_version_id=UUID("00000000-0000-0000-0000-000000000708"),
            source_location=SourceLocation(
                id=UUID("00000000-0000-0000-0000-000000000709"),
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
            created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )


def client(
    *,
    citation_repository: FakeCitationRepository | None = None,
    auth_settings: AuthSettings | None = None,
) -> tuple[TestClient, FakeCitationRepository]:
    repository = citation_repository or FakeCitationRepository()
    app = create_app(
        auth_settings or local_bypass_settings(),
        project_repository=FakeProjectRepository(),
        citation_repository=repository,
    )
    return TestClient(app), repository


def test_owner_can_review_a_non_persistent_immutable_execution_plan() -> None:
    api_client, repository = client()

    with api_client as http:
        response = http.post(
            PLAN_REVIEW_PATH,
            json={
                "generated_test_case": generated_test_case_payload(),
                "target_id": "synthetic-order-api",
                "limits": {
                    "request_timeout_ms": 5_000,
                    "max_request_body_bytes": 64_000,
                    "max_response_bytes": 128_000,
                    "max_assertions": 10,
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert UUID(body["plan_id"])
    assert len(body["plan_hash"]) == 64
    assert body["target_id"] == "synthetic-order-api"
    assert body["target_base_url"] == "https://ai-qa-sandbox.onrender.com"
    assert body["method"] == "POST"
    assert body["path"] == "/orders"
    assert body["citation_ids"] == [str(CITATION_ID)]
    assert body["limits"]["request_timeout_ms"] == 5_000
    assert body["estimate"] == {
        "request_count": 1,
        "request_body_bytes": len(b'{"quantity":2}'),
        "assertion_count": 1,
        "maximum_response_bytes": 128_000,
        "maximum_duration_ms": 5_000,
    }
    assert UUID(response.headers["X-Correlation-ID"])
    assert repository.lookups == [(PROJECT_ID, CITATION_ID)]


def test_material_plan_input_change_returns_a_different_hash() -> None:
    api_client, _ = client()
    first_payload = generated_test_case_payload()
    second_payload = generated_test_case_payload()
    request = second_payload["request"]
    assert isinstance(request, dict)
    request["json_body"] = {"quantity": 3}

    with api_client as http:
        first = http.post(
            PLAN_REVIEW_PATH,
            json={
                "generated_test_case": first_payload,
                "target_id": "synthetic-order-api",
            },
        )
        second = http.post(
            PLAN_REVIEW_PATH,
            json={
                "generated_test_case": second_payload,
                "target_id": "synthetic-order-api",
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["plan_hash"] != second.json()["plan_hash"]


def test_unknown_target_is_rejected_after_citation_validation() -> None:
    api_client, repository = client()

    with api_client as http:
        response = http.post(
            PLAN_REVIEW_PATH,
            json={
                "generated_test_case": generated_test_case_payload(),
                "target_id": "https://untrusted.example/orders",
            },
        )

    assert response.status_code == 400
    assert UUID(response.headers["X-Correlation-ID"])
    assert repository.lookups == [(PROJECT_ID, CITATION_ID)]


def test_foreign_or_missing_citation_is_rejected() -> None:
    api_client, repository = client(
        citation_repository=FakeCitationRepository(
            available_project_id=OTHER_PROJECT_ID
        )
    )

    with api_client as http:
        response = http.post(
            PLAN_REVIEW_PATH,
            json={
                "generated_test_case": generated_test_case_payload(),
                "target_id": "synthetic-order-api",
            },
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Citation not found"}
    assert UUID(response.headers["X-Correlation-ID"])
    assert repository.lookups == [(PROJECT_ID, CITATION_ID)]


def test_invalid_generated_test_payload_is_rejected_before_citation_lookup() -> None:
    api_client, repository = client()
    payload = generated_test_case_payload()
    payload["request"] = {"method": "POST"}

    with api_client as http:
        response = http.post(
            PLAN_REVIEW_PATH,
            json={
                "generated_test_case": payload,
                "target_id": "synthetic-order-api",
            },
        )

    assert response.status_code == 400
    assert UUID(response.headers["X-Correlation-ID"])
    assert repository.lookups == []


def test_citation_repository_unavailability_returns_503() -> None:
    api_client, _ = client(citation_repository=FakeCitationRepository(unavailable=True))

    with api_client as http:
        response = http.post(
            PLAN_REVIEW_PATH,
            json={
                "generated_test_case": generated_test_case_payload(),
                "target_id": "synthetic-order-api",
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Citation service is temporarily unavailable"}
    assert UUID(response.headers["X-Correlation-ID"])


def test_plan_review_requires_owner_authentication() -> None:
    api_client, _ = client(
        auth_settings=AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=None,
        )
    )

    with api_client as http:
        response = http.post(
            PLAN_REVIEW_PATH,
            json={
                "generated_test_case": generated_test_case_payload(),
                "target_id": "synthetic-order-api",
            },
        )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
