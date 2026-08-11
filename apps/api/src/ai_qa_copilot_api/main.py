from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal, Never
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from ai_qa_copilot_api.audit import (
    AuthorizationAuditSink,
    AuthorizationAuditUnavailable,
    AuthorizationAuditor,
    StructuredLoggingAuditSink,
)
from ai_qa_copilot_api.auth import (
    AuthBoundary,
    AuthSettings,
    OwnerResolutionFailure,
    TokenValidator,
)
from ai_qa_copilot_api.authorization import (
    AuthorizationDenied,
    ProjectAuthorizationBoundary,
    ProjectAuthorizationPolicy,
    actor_for_owner_resolution_failure,
)
from ai_qa_copilot_api.demo import (
    DEMO_UNAVAILABLE_DETAIL,
    DemoPublicationRepository,
    DemoPublicationService,
    DemoPublicationSettings,
    DemoPublicationUnavailable,
    UnavailableDemoPublicationRepository,
)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: Literal["ai-qa-copilot-api"]


class PublicDemoResponse(BaseModel):
    """Sanitized public projection selected entirely by the server."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    publication_id: UUID
    publication_revision_id: UUID
    report_revision_id: UUID
    traceability_revision_id: UUID
    citation_excerpt_revision_ids: tuple[UUID, ...]
    title: str
    summary: str
    content_hash: str


def create_app(
    auth_settings: AuthSettings | None = None,
    token_validator: TokenValidator | None = None,
    *,
    demo_settings: DemoPublicationSettings | None = None,
    demo_publication_repository: DemoPublicationRepository | None = None,
    authorization_audit_sink: AuthorizationAuditSink | None = None,
) -> FastAPI:
    """Build the API with identity and authorization initialized at startup."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = auth_settings or AuthSettings.from_environment()
        selected_demo_settings = (
            demo_settings
            if demo_settings is not None
            else DemoPublicationSettings.from_environment()
        )
        audit_sink = (
            authorization_audit_sink
            if authorization_audit_sink is not None
            else StructuredLoggingAuditSink()
        )
        auditor = AuthorizationAuditor(audit_sink)
        auth_boundary = AuthBoundary(settings, token_validator)
        project_policy = ProjectAuthorizationPolicy(auditor)
        application.state.auth_boundary = auth_boundary
        application.state.project_authorization_policy = project_policy
        application.state.project_authorization_boundary = ProjectAuthorizationBoundary(
            auth_boundary, project_policy, auditor
        )
        application.state.demo_publication_service = DemoPublicationService(
            selected_demo_settings,
            (
                demo_publication_repository
                if demo_publication_repository is not None
                else UnavailableDemoPublicationRepository()
            ),
            auditor,
        )
        yield

    application = FastAPI(lifespan=lifespan)

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="ai-qa-copilot-api")

    @application.api_route(
        "/demo",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
        response_model=PublicDemoResponse,
    )
    def public_demo(request: Request, response: Response) -> PublicDemoResponse:
        correlation_id = uuid4()
        boundary = getattr(request.app.state, "auth_boundary", None)
        service = getattr(request.app.state, "demo_publication_service", None)
        if not isinstance(boundary, AuthBoundary) or not isinstance(
            service, DemoPublicationService
        ):
            raise RuntimeError("Authorization boundaries were not initialized")

        try:
            principal = boundary.resolve_public_demo_principal(request)
        except OwnerResolutionFailure as error:
            try:
                service.audit_identity_denial(
                    actor=actor_for_owner_resolution_failure(error),
                    method=request.method,
                    correlation_id=correlation_id,
                    reason=error.reason,
                )
            except AuthorizationAuditUnavailable:
                _raise_service_unavailable(correlation_id)
            headers = {"X-Correlation-ID": str(correlation_id)}
            if error.status_code == status.HTTP_401_UNAUTHORIZED:
                headers["WWW-Authenticate"] = "Bearer"
            raise HTTPException(
                status_code=error.status_code,
                detail=error.detail,
                headers=headers,
            ) from None

        try:
            publication = service.read_selected(
                principal=principal,
                method=request.method,
                correlation_id=correlation_id,
            )
        except AuthorizationDenied as error:
            raise HTTPException(
                status_code=error.status_code,
                detail=error.public_detail,
                headers={"X-Correlation-ID": str(correlation_id)},
            ) from None
        except (AuthorizationAuditUnavailable, DemoPublicationUnavailable):
            _raise_service_unavailable(correlation_id)

        response.headers["X-Correlation-ID"] = str(correlation_id)
        return PublicDemoResponse.model_validate(publication)

    return application


def _raise_service_unavailable(correlation_id: UUID) -> Never:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=DEMO_UNAVAILABLE_DETAIL,
        headers={"X-Correlation-ID": str(correlation_id)},
    )


app = create_app()
