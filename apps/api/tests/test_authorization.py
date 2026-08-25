from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from ai_qa_copilot_api.audit import (
    AUTHORIZATION_AUDIT_LOGGER,
    AuditPrincipalType,
    AuditResult,
    AuthorizationActor,
    AuthorizationAuditEvent,
    AuthorizationAuditUnavailable,
    AuthorizationAuditor,
    StructuredLoggingAuditSink,
)
from ai_qa_copilot_api.auth import (
    AnonymousGuestPrincipal,
    AppEnvironment,
    AuthBoundary,
    AuthSettings,
    CognitoIdentity,
    CognitoOwnerPrincipal,
    CognitoSettings,
    LocalDevelopmentOwnerPrincipal,
    OwnerResolutionFailure,
)
from ai_qa_copilot_api.authorization import (
    AuthorizationDenied,
    ProjectAction,
    ProjectAuthorizationBoundary,
    ProjectAuthorizationPolicy,
    ProjectResourceReference,
    ProjectResourceType,
)
from ai_qa_copilot_api.demo import (
    DemoConfigurationError,
    DemoDataClassification,
    DemoPublication,
    DemoPublicationSelection,
    DemoPublicationSettings,
    DemoPublicationState,
)
from ai_qa_copilot_api.main import create_app


PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")
OTHER_PROJECT_ID = UUID("10000000-0000-4000-8000-000000000002")
RESOURCE_ID = UUID("20000000-0000-4000-8000-000000000001")
PUBLICATION_ID = UUID("30000000-0000-4000-8000-000000000001")
PUBLICATION_REVISION_ID = UUID("30000000-0000-4000-8000-000000000002")
OTHER_PUBLICATION_ID = UUID("30000000-0000-4000-8000-000000000003")
OTHER_PUBLICATION_REVISION_ID = UUID("30000000-0000-4000-8000-000000000004")
REPORT_REVISION_ID = UUID("40000000-0000-4000-8000-000000000001")
TRACEABILITY_REVISION_ID = UUID("50000000-0000-4000-8000-000000000001")
CITATION_REVISION_ID = UUID("60000000-0000-4000-8000-000000000001")
CORRELATION_ID = UUID("70000000-0000-4000-8000-000000000001")
EVENT_ID = UUID("80000000-0000-4000-8000-000000000001")
FIXED_TIME = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example"
CLIENT_ID = "client-id-example"
OWNER_SUBJECT = "owner-subject"


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[AuthorizationAuditEvent] = []

    def record(self, event: AuthorizationAuditEvent) -> None:
        self.events.append(event)


class FailingAuditSink:
    def record(self, event: AuthorizationAuditEvent) -> None:
        del event
        raise RuntimeError("audit unavailable")


class RecordingDemoRepository:
    def __init__(self, publication: DemoPublication | None) -> None:
        self.publication = publication
        self.selections: list[DemoPublicationSelection] = []

    def get_exact(self, selection: DemoPublicationSelection) -> DemoPublication | None:
        self.selections.append(selection)
        return self.publication


class FailingDemoRepository:
    def get_exact(self, selection: DemoPublicationSelection) -> DemoPublication:
        del selection
        raise RuntimeError("database unavailable")


class StaticTokenValidator:
    def __init__(self, identity: CognitoIdentity) -> None:
        self.identity = identity

    def validate(self, token: str) -> CognitoIdentity:
        del token
        return self.identity


class PublicationTransform(Protocol):
    def __call__(self, publication: DemoPublication) -> DemoPublication: ...


def selection() -> DemoPublicationSelection:
    return DemoPublicationSelection(
        publication_id=PUBLICATION_ID,
        publication_revision_id=PUBLICATION_REVISION_ID,
    )


def publication() -> DemoPublication:
    value = DemoPublication(
        selection=selection(),
        project_id=PROJECT_ID,
        report_revision_id=REPORT_REVISION_ID,
        traceability_revision_id=TRACEABILITY_REVISION_ID,
        citation_excerpt_revision_ids=(CITATION_REVISION_ID,),
        title="Synthetic checkout quality review",
        summary="Sanitized QA evidence for a synthetic checkout API.",
        data_classification=DemoDataClassification.SYNTHETIC,
        sanitization_policy_version="demo-sanitization-v1",
        content_hash=f"sha256:{'0' * 64}",
        state=DemoPublicationState.PUBLISHED,
        sanitized=True,
        immutable=True,
    )
    return replace(value, content_hash=value.expected_content_hash())


def demo_settings() -> DemoPublicationSettings:
    return DemoPublicationSettings(selection=selection())


def local_auth_settings(*, bypass: bool = False) -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=bypass,
        cognito=None,
    )


def cognito_auth_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=False,
        cognito=CognitoSettings(
            issuer=ISSUER,
            client_id=CLIENT_ID,
            owner_subject=OWNER_SUBJECT,
        ),
    )


def fixed_auditor(sink: RecordingAuditSink) -> AuthorizationAuditor:
    return AuthorizationAuditor(
        sink,
        clock=lambda: FIXED_TIME,
        event_id_factory=lambda: EVENT_ID,
    )


def project_resource(
    *,
    project_id: UUID = PROJECT_ID,
    resource_type: ProjectResourceType = ProjectResourceType.ARTIFACT,
    version: str | None = "revision-1",
) -> ProjectResourceReference:
    return ProjectResourceReference(
        project_id=project_id,
        resource_type=resource_type,
        resource_id=RESOURCE_ID,
        resource_version=version,
    )


def request_with_authorization(authorization: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("ascii")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/projects/example",
            "raw_path": b"/projects/example",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


def test_owner_project_scope_returns_capability_and_complete_audit_event() -> None:
    sink = RecordingAuditSink()
    policy = ProjectAuthorizationPolicy(fixed_auditor(sink))
    owner = CognitoOwnerPrincipal(issuer=ISSUER, subject=OWNER_SUBJECT)
    resource = project_resource()

    scope = policy.authorize(
        principal=owner,
        action=ProjectAction.READ,
        requested_project_id=PROJECT_ID,
        resource=resource,
        correlation_id=CORRELATION_ID,
    )

    assert scope.principal is owner
    assert scope.project_id == PROJECT_ID
    assert scope.resource is resource
    assert scope.action is ProjectAction.READ
    assert len(sink.events) == 1
    assert sink.events[0].as_dict() == {
        "event_id": str(EVENT_ID),
        "occurred_at": FIXED_TIME.isoformat(),
        "correlation_id": str(CORRELATION_ID),
        "principal_type": "owner",
        "actor_id": OWNER_SUBJECT,
        "action": "project.read",
        "result": "allowed",
        "reason": "owner_project_scope_match",
        "resource_type": "artifact",
        "resource_id": str(RESOURCE_ID),
        "resource_version": "revision-1",
        "project_id": str(PROJECT_ID),
    }
    with pytest.raises(AttributeError):
        setattr(sink.events[0], "reason", "changed")


def test_structured_logging_adapter_emits_one_parseable_credential_free_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    auditor = AuthorizationAuditor(
        StructuredLoggingAuditSink(),
        clock=lambda: FIXED_TIME,
        event_id_factory=lambda: EVENT_ID,
    )

    with caplog.at_level(logging.INFO, logger=AUTHORIZATION_AUDIT_LOGGER):
        auditor.record(
            correlation_id=CORRELATION_ID,
            actor=AuthorizationActor(
                principal_type=AuditPrincipalType.OWNER,
                actor_id=OWNER_SUBJECT,
            ),
            action="project.read",
            result=AuditResult.ALLOWED,
            reason="owner_project_scope_match",
            resource_type="project",
            resource_id=str(PROJECT_ID),
            project_id=str(PROJECT_ID),
        )

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    prefix = "authorization_audit="
    assert message.startswith(prefix)
    payload = json.loads(message.removeprefix(prefix))
    assert payload["correlation_id"] == str(CORRELATION_ID)
    assert payload["actor_id"] == OWNER_SUBJECT
    assert "authorization" not in payload
    assert "token" not in payload


def test_cross_project_owner_access_is_hidden_and_audited() -> None:
    sink = RecordingAuditSink()
    policy = ProjectAuthorizationPolicy(fixed_auditor(sink))

    with pytest.raises(AuthorizationDenied) as denial:
        policy.authorize(
            principal=CognitoOwnerPrincipal(issuer=ISSUER, subject=OWNER_SUBJECT),
            action=ProjectAction.READ,
            requested_project_id=PROJECT_ID,
            resource=project_resource(project_id=OTHER_PROJECT_ID),
            correlation_id=CORRELATION_ID,
        )

    assert denial.value.status_code == 404
    assert denial.value.public_detail == "Resource not found"
    assert denial.value.reason == "project_scope_mismatch"
    assert sink.events[0].result is AuditResult.DENIED
    assert sink.events[0].reason == "project_scope_mismatch"
    assert sink.events[0].project_id == str(PROJECT_ID)


@pytest.mark.parametrize(
    ("action", "resource_type", "version"),
    (
        (ProjectAction.MUTATE, ProjectResourceType.PROJECT, None),
        (ProjectAction.READ_RAW_OBJECT, ProjectResourceType.RAW_OBJECT, "object-v1"),
        (ProjectAction.INVOKE_MODEL, ProjectResourceType.PROJECT, None),
        (ProjectAction.ENQUEUE_JOB, ProjectResourceType.JOB, "job-v1"),
        (ProjectAction.APPROVE, ProjectResourceType.APPROVAL, "approval-v1"),
        (ProjectAction.EXECUTE, ProjectResourceType.EXECUTION, "plan-v1"),
    ),
)
def test_guest_private_write_raw_and_spend_actions_fail_closed_before_side_effects(
    action: ProjectAction,
    resource_type: ProjectResourceType,
    version: str | None,
) -> None:
    sink = RecordingAuditSink()
    policy = ProjectAuthorizationPolicy(fixed_auditor(sink))
    side_effect_count = 0

    with pytest.raises(AuthorizationDenied) as denial:
        policy.authorize(
            principal=AnonymousGuestPrincipal(),
            action=action,
            requested_project_id=PROJECT_ID,
            resource=project_resource(
                resource_type=resource_type,
                version=version,
            ),
            correlation_id=CORRELATION_ID,
        )
        side_effect_count += 1

    assert side_effect_count == 0
    assert denial.value.status_code == 404
    assert sink.events[0].principal_type is AuditPrincipalType.GUEST
    assert sink.events[0].actor_id is None
    assert sink.events[0].result is AuditResult.DENIED
    assert sink.events[0].reason == "guest_private_project_access"


@pytest.mark.parametrize(
    ("action", "resource_type", "version"),
    (
        (ProjectAction.READ_RAW_OBJECT, ProjectResourceType.RAW_OBJECT, None),
        (ProjectAction.READ, ProjectResourceType.RAW_OBJECT, "object-v1"),
        (ProjectAction.READ_RAW_OBJECT, ProjectResourceType.ARTIFACT, "object-v1"),
    ),
)
def test_raw_object_requires_an_exact_action_and_version_even_for_owner(
    action: ProjectAction,
    resource_type: ProjectResourceType,
    version: str | None,
) -> None:
    sink = RecordingAuditSink()
    policy = ProjectAuthorizationPolicy(fixed_auditor(sink))

    with pytest.raises(AuthorizationDenied) as denial:
        policy.authorize(
            principal=LocalDevelopmentOwnerPrincipal(),
            action=action,
            requested_project_id=PROJECT_ID,
            resource=project_resource(
                resource_type=resource_type,
                version=version,
            ),
            correlation_id=CORRELATION_ID,
        )

    assert denial.value.reason == "raw_object_action_or_version_invalid"
    assert sink.events[0].result is AuditResult.DENIED


def test_audit_sink_failure_prevents_an_allow_decision() -> None:
    policy = ProjectAuthorizationPolicy(AuthorizationAuditor(FailingAuditSink()))

    with pytest.raises(AuthorizationAuditUnavailable):
        policy.authorize(
            principal=LocalDevelopmentOwnerPrincipal(),
            action=ProjectAction.READ,
            requested_project_id=PROJECT_ID,
            resource=project_resource(),
            correlation_id=CORRELATION_ID,
        )


def test_project_request_boundary_audits_missing_owner_credentials() -> None:
    sink = RecordingAuditSink()
    auditor = fixed_auditor(sink)
    policy = ProjectAuthorizationPolicy(auditor)
    boundary = ProjectAuthorizationBoundary(
        AuthBoundary(local_auth_settings()),
        policy,
        auditor,
    )

    with pytest.raises(OwnerResolutionFailure) as denial:
        boundary.authorize_request(
            request=request_with_authorization(),
            action=ProjectAction.MUTATE,
            requested_project_id=PROJECT_ID,
            resource=ProjectResourceReference.project(PROJECT_ID),
            correlation_id=CORRELATION_ID,
        )

    assert denial.value.status_code == 401
    assert sink.events[0].principal_type is AuditPrincipalType.UNKNOWN
    assert sink.events[0].actor_id is None
    assert sink.events[0].result is AuditResult.DENIED
    assert sink.events[0].reason == "invalid_or_missing_credentials"
    assert sink.events[0].action == "project.mutate"


def test_project_request_boundary_returns_one_audited_local_owner_scope() -> None:
    sink = RecordingAuditSink()
    auditor = fixed_auditor(sink)
    boundary = ProjectAuthorizationBoundary(
        AuthBoundary(local_auth_settings(bypass=True)),
        ProjectAuthorizationPolicy(auditor),
        auditor,
    )

    scope = boundary.authorize_request(
        request=request_with_authorization(),
        action=ProjectAction.READ,
        requested_project_id=PROJECT_ID,
        resource=ProjectResourceReference.project(PROJECT_ID),
        correlation_id=CORRELATION_ID,
    )

    assert isinstance(scope.principal, LocalDevelopmentOwnerPrincipal)
    assert scope.project_id == PROJECT_ID
    assert len(sink.events) == 1
    assert sink.events[0].result is AuditResult.ALLOWED
    assert sink.events[0].actor_id == "local-development-owner"


def test_project_request_boundary_audits_valid_non_owner_subject() -> None:
    sink = RecordingAuditSink()
    auditor = fixed_auditor(sink)
    non_owner_subject = "authenticated-non-owner"
    auth_boundary = AuthBoundary(
        cognito_auth_settings(),
        StaticTokenValidator(CognitoIdentity(issuer=ISSUER, subject=non_owner_subject)),
    )
    boundary = ProjectAuthorizationBoundary(
        auth_boundary,
        ProjectAuthorizationPolicy(auditor),
        auditor,
    )

    with pytest.raises(OwnerResolutionFailure) as denial:
        boundary.authorize_request(
            request=request_with_authorization("Bearer valid-non-owner-token"),
            action=ProjectAction.READ,
            requested_project_id=PROJECT_ID,
            resource=ProjectResourceReference.project(PROJECT_ID),
            correlation_id=CORRELATION_ID,
        )

    assert denial.value.status_code == 403
    assert sink.events[0].principal_type is AuditPrincipalType.AUTHENTICATED_NON_OWNER
    assert sink.events[0].actor_id == non_owner_subject
    assert sink.events[0].reason == "valid_non_owner"


def test_project_request_boundary_fails_closed_when_identity_denial_cannot_audit() -> (
    None
):
    auditor = AuthorizationAuditor(FailingAuditSink())
    boundary = ProjectAuthorizationBoundary(
        AuthBoundary(local_auth_settings()),
        ProjectAuthorizationPolicy(auditor),
        auditor,
    )

    with pytest.raises(AuthorizationAuditUnavailable):
        boundary.authorize_request(
            request=request_with_authorization(),
            action=ProjectAction.READ,
            requested_project_id=PROJECT_ID,
            resource=ProjectResourceReference.project(PROJECT_ID),
            correlation_id=CORRELATION_ID,
        )


def test_server_selected_sanitized_publication_is_the_only_demo_response() -> None:
    sink = RecordingAuditSink()
    repository = RecordingDemoRepository(publication())
    app = create_app(
        local_auth_settings(),
        demo_settings=demo_settings(),
        demo_publication_repository=repository,
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.get(
            "/demo",
            params={
                "publication_id": str(OTHER_PUBLICATION_ID),
                "publication_revision_id": str(OTHER_PUBLICATION_REVISION_ID),
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "publication_id": str(PUBLICATION_ID),
        "publication_revision_id": str(PUBLICATION_REVISION_ID),
        "report_revision_id": str(REPORT_REVISION_ID),
        "traceability_revision_id": str(TRACEABILITY_REVISION_ID),
        "citation_excerpt_revision_ids": [str(CITATION_REVISION_ID)],
        "title": "Synthetic checkout quality review",
        "summary": "Sanitized QA evidence for a synthetic checkout API.",
        "content_hash": publication().content_hash,
    }
    assert "project_id" not in response.json()
    assert repository.selections == [selection()]
    assert UUID(response.headers["X-Correlation-ID"]) == sink.events[0].correlation_id
    assert sink.events[0].principal_type is AuditPrincipalType.GUEST
    assert sink.events[0].result is AuditResult.ALLOWED
    assert sink.events[0].reason == "server_selected_sanitized_publication"


def test_demo_head_is_read_only_and_returns_no_body() -> None:
    sink = RecordingAuditSink()
    app = create_app(
        local_auth_settings(),
        demo_settings=demo_settings(),
        demo_publication_repository=RecordingDemoRepository(publication()),
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.head("/demo")

    assert response.status_code == 200
    assert response.content == b""
    assert sink.events[0].action == "demo.read"
    assert sink.events[0].result is AuditResult.ALLOWED


@pytest.mark.parametrize("method", ("post", "put", "patch", "delete"))
def test_demo_write_verbs_are_forbidden_and_never_read_the_repository(
    method: str,
) -> None:
    sink = RecordingAuditSink()
    repository = RecordingDemoRepository(publication())
    app = create_app(
        local_auth_settings(),
        demo_settings=demo_settings(),
        demo_publication_repository=repository,
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.request(method.upper(), "/demo")

    assert response.status_code == 403
    assert response.json() == {"detail": "Demo publication is read-only"}
    assert repository.selections == []
    assert sink.events[0].action == "demo.write"
    assert sink.events[0].result is AuditResult.DENIED
    assert sink.events[0].reason == "demo_route_read_only"


def test_public_demo_write_is_forbidden_even_for_local_owner() -> None:
    sink = RecordingAuditSink()
    repository = RecordingDemoRepository(publication())
    app = create_app(
        local_auth_settings(bypass=True),
        demo_settings=demo_settings(),
        demo_publication_repository=repository,
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.post("/demo")

    assert response.status_code == 403
    assert repository.selections == []
    assert sink.events[0].principal_type is AuditPrincipalType.OWNER
    assert sink.events[0].result is AuditResult.DENIED


@pytest.mark.parametrize(
    "transform",
    (
        lambda value: replace(
            value,
            selection=DemoPublicationSelection(
                publication_id=OTHER_PUBLICATION_ID,
                publication_revision_id=OTHER_PUBLICATION_REVISION_ID,
            ),
        ),
        lambda value: replace(value, state=DemoPublicationState.DRAFT),
        lambda value: replace(value, sanitized=False),
        lambda value: replace(value, immutable=False),
        lambda value: replace(
            value, data_classification=DemoDataClassification.PRIVATE
        ),
        lambda value: replace(value, content_hash="not-a-sha256"),
        lambda value: replace(value, title="Changed after hashing"),
        lambda value: replace(value, citation_excerpt_revision_ids=()),
    ),
)
def test_unselected_or_unsafe_demo_records_return_safe_not_found(
    transform: PublicationTransform,
) -> None:
    sink = RecordingAuditSink()
    app = create_app(
        local_auth_settings(),
        demo_settings=demo_settings(),
        demo_publication_repository=RecordingDemoRepository(transform(publication())),
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.get("/demo")

    assert response.status_code == 404
    assert response.json() == {"detail": "Demo publication not found"}
    assert sink.events[0].result is AuditResult.DENIED
    assert sink.events[0].reason == "demo_publication_not_public"


def test_missing_demo_selection_returns_not_found_without_repository_access() -> None:
    sink = RecordingAuditSink()
    repository = RecordingDemoRepository(publication())
    app = create_app(
        local_auth_settings(),
        demo_settings=DemoPublicationSettings(selection=None),
        demo_publication_repository=repository,
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.get("/demo")

    assert response.status_code == 404
    assert repository.selections == []
    assert sink.events[0].reason == "demo_publication_not_configured"


def test_partial_or_invalid_server_demo_selection_is_rejected() -> None:
    with pytest.raises(DemoConfigurationError, match="must be configured together"):
        DemoPublicationSettings.from_mapping(
            {"DEMO_PUBLICATION_ID": str(PUBLICATION_ID)}
        )
    with pytest.raises(DemoConfigurationError, match="non-zero UUIDs"):
        DemoPublicationSettings.from_mapping(
            {
                "DEMO_PUBLICATION_ID": str(UUID(int=0)),
                "DEMO_PUBLICATION_REVISION_ID": str(PUBLICATION_REVISION_ID),
            }
        )


def test_demo_repository_failure_is_audited_and_fails_closed() -> None:
    sink = RecordingAuditSink()
    app = create_app(
        local_auth_settings(),
        demo_settings=demo_settings(),
        demo_publication_repository=FailingDemoRepository(),
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.get("/demo")

    assert response.status_code == 503
    assert response.json() == {"detail": "Demo publication is temporarily unavailable"}
    assert sink.events[0].result is AuditResult.DENIED
    assert sink.events[0].reason == "demo_repository_unavailable"


def test_invalid_demo_bearer_is_unauthorized_audited_and_never_loaded() -> None:
    sink = RecordingAuditSink()
    repository = RecordingDemoRepository(publication())
    app = create_app(
        local_auth_settings(),
        demo_settings=demo_settings(),
        demo_publication_repository=repository,
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.get(
            "/demo",
            headers={"Authorization": "Bearer never-log-this-token"},
        )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert repository.selections == []
    assert sink.events[0].principal_type is AuditPrincipalType.UNKNOWN
    assert sink.events[0].reason == "invalid_or_missing_credentials"
    assert "never-log-this-token" not in str(sink.events[0].as_dict())


def test_valid_non_owner_demo_bearer_is_forbidden_with_actor_audit() -> None:
    sink = RecordingAuditSink()
    repository = RecordingDemoRepository(publication())
    non_owner_subject = "authenticated-non-owner"
    app = create_app(
        cognito_auth_settings(),
        StaticTokenValidator(CognitoIdentity(issuer=ISSUER, subject=non_owner_subject)),
        demo_settings=demo_settings(),
        demo_publication_repository=repository,
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.get(
            "/demo",
            headers={"Authorization": "Bearer validated-non-owner-token"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Owner access required"}
    assert repository.selections == []
    assert sink.events[0].principal_type is AuditPrincipalType.AUTHENTICATED_NON_OWNER
    assert sink.events[0].actor_id == non_owner_subject
    assert sink.events[0].reason == "valid_non_owner"


def test_local_bypass_owner_demo_read_is_identified_in_audit() -> None:
    sink = RecordingAuditSink()
    app = create_app(
        local_auth_settings(bypass=True),
        demo_settings=demo_settings(),
        demo_publication_repository=RecordingDemoRepository(publication()),
        authorization_audit_sink=sink,
    )

    with TestClient(app) as client:
        response = client.get("/demo")

    assert response.status_code == 200
    assert sink.events[0].principal_type is AuditPrincipalType.OWNER
    assert sink.events[0].actor_id == "local-development-owner"


def test_demo_audit_failure_returns_service_unavailable_not_public_data() -> None:
    app = create_app(
        local_auth_settings(),
        demo_settings=demo_settings(),
        demo_publication_repository=RecordingDemoRepository(publication()),
        authorization_audit_sink=FailingAuditSink(),
    )

    with TestClient(app) as client:
        response = client.get("/demo")

    assert response.status_code == 503
    assert response.json() == {"detail": "Demo publication is temporarily unavailable"}


def test_publication_settings_do_not_accept_request_or_role_fields() -> None:
    assert set(DemoPublicationSettings.__dataclass_fields__) == {"selection"}
    assert set(DemoPublicationSelection.__dataclass_fields__) == {
        "publication_id",
        "publication_revision_id",
    }
    assert "role" not in DemoPublicationSettings.__dataclass_fields__
