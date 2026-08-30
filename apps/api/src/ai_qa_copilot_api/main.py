from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal, Never
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ai_qa_copilot_api.audit import (
    AuthorizationAuditSink,
    AuthorizationAuditUnavailable,
    AuthorizationAuditor,
    StructuredLoggingAuditSink,
)
from ai_qa_copilot_api.analysis_runs import (
    ANALYSIS_RUNS_UNAVAILABLE_DETAIL,
    AnalysisRunService,
    AnalysisRunUnavailable,
    UnavailableAnalysisRunService,
    analysis_run_service_from_environment,
)
from ai_qa_copilot_api.auth import (
    AuthBoundary,
    AuthSettings,
    OwnerResolutionFailure,
    TokenValidator,
)
from ai_qa_copilot_api.authorization import (
    AuthorizationDenied,
    ProjectAction,
    ProjectAuthorizationBoundary,
    ProjectAuthorizationPolicy,
    ProjectResourceReference,
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
from ai_qa_copilot_api.ingestion import (
    DOCUMENT_INTAKE_UNAVAILABLE_DETAIL,
    DocumentIntake,
    DocumentIntakeRepository,
    DocumentIntakeService,
    DocumentIntakeState,
    DocumentIntakeUnavailable,
    QuarantineStorage,
    UploadPolicy,
    UnavailableDocumentIntakeRepository,
    UnavailableQuarantineStorage,
)
from ai_qa_copilot_api.projects import (
    PROJECTS_UNAVAILABLE_DETAIL,
    ProjectRepository,
    ProjectRepositoryUnavailable,
    project_repository_from_environment,
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


class ProjectCreateRequest(BaseModel):
    """Owner-supplied project fields; ownership remains server-controlled."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str | None, Field(max_length=2_000)] = None


class ProjectResponse(BaseModel):
    """Public owner projection for the minimal project vertical slice."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    name: str
    description: str | None
    created_at: datetime
    archived_at: datetime | None


class AnalysisRunCreateRequest(BaseModel):
    """One explicitly synthetic input submitted for the SKEL-005 proof."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    synthetic_text: Annotated[str, Field(min_length=1, max_length=4_000)]


class AnalysisRunResponse(BaseModel):
    """Persisted result plus the fixed model-configuration projection."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    project_id: UUID
    synthetic_text: str
    output_json: dict[str, object]
    provider_response_id: str
    model_id: str
    configuration_version: str
    prompt_version: str
    schema_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    created_at: datetime


class DocumentIntakeResponse(BaseModel):
    """Safe owner projection for a quarantined candidate or preflight rejection."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    project_id: UUID
    state: DocumentIntakeState
    document_id: UUID | None
    document_version_id: UUID | None
    byte_size: int
    content_sha256: str | None
    rejection_code: str | None
    deduplicated: bool
    created_at: datetime


def create_app(
    auth_settings: AuthSettings | None = None,
    token_validator: TokenValidator | None = None,
    *,
    demo_settings: DemoPublicationSettings | None = None,
    demo_publication_repository: DemoPublicationRepository | None = None,
    authorization_audit_sink: AuthorizationAuditSink | None = None,
    project_repository: ProjectRepository | None = None,
    document_intake_repository: DocumentIntakeRepository | None = None,
    quarantine_storage: QuarantineStorage | None = None,
    document_intake_policy: UploadPolicy = UploadPolicy(),
    analysis_run_service: AnalysisRunService
    | UnavailableAnalysisRunService
    | None = None,
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
        application.state.project_repository = (
            project_repository
            if project_repository is not None
            else project_repository_from_environment()
        )
        application.state.document_intake_service = DocumentIntakeService(
            (
                document_intake_repository
                if document_intake_repository is not None
                else UnavailableDocumentIntakeRepository()
            ),
            (
                quarantine_storage
                if quarantine_storage is not None
                else UnavailableQuarantineStorage()
            ),
            policy=document_intake_policy,
        )
        application.state.analysis_run_service = (
            analysis_run_service
            if analysis_run_service is not None
            else analysis_run_service_from_environment()
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

    @application.post(
        "/projects",
        status_code=status.HTTP_201_CREATED,
        response_model=ProjectResponse,
    )
    def create_project(
        payload: ProjectCreateRequest,
        request: Request,
        response: Response,
    ) -> ProjectResponse:
        correlation_id = uuid4()
        boundary, repository = _project_dependencies(request)
        _authorize_project_collection(
            boundary=boundary,
            request=request,
            action=ProjectAction.MUTATE,
            correlation_id=correlation_id,
        )
        try:
            project = repository.create(
                name=payload.name,
                description=payload.description,
            )
        except ProjectRepositoryUnavailable:
            _raise_projects_unavailable(correlation_id)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        return ProjectResponse.model_validate(project)

    @application.get("/projects", response_model=list[ProjectResponse])
    def list_projects(request: Request, response: Response) -> list[ProjectResponse]:
        correlation_id = uuid4()
        boundary, repository = _project_dependencies(request)
        _authorize_project_collection(
            boundary=boundary,
            request=request,
            action=ProjectAction.LIST,
            correlation_id=correlation_id,
        )
        try:
            projects = repository.list_active()
        except ProjectRepositoryUnavailable:
            _raise_projects_unavailable(correlation_id)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        return [ProjectResponse.model_validate(project) for project in projects]

    @application.get("/projects/{project_id}", response_model=ProjectResponse)
    def get_project(
        project_id: UUID,
        request: Request,
        response: Response,
    ) -> ProjectResponse:
        correlation_id = uuid4()
        boundary, repository = _project_dependencies(request)
        _authorize_project_resource(
            boundary=boundary,
            request=request,
            action=ProjectAction.READ,
            project_id=project_id,
            correlation_id=correlation_id,
        )
        try:
            project = repository.get(project_id)
        except ProjectRepositoryUnavailable:
            _raise_projects_unavailable(correlation_id)
        if project is None:
            _raise_project_not_found(correlation_id)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        return ProjectResponse.model_validate(project)

    @application.post(
        "/projects/{project_id}/archive",
        response_model=ProjectResponse,
    )
    def archive_project(
        project_id: UUID,
        request: Request,
        response: Response,
    ) -> ProjectResponse:
        correlation_id = uuid4()
        boundary, repository = _project_dependencies(request)
        _authorize_project_resource(
            boundary=boundary,
            request=request,
            action=ProjectAction.MUTATE,
            project_id=project_id,
            correlation_id=correlation_id,
        )
        try:
            project = repository.archive(project_id)
        except ProjectRepositoryUnavailable:
            _raise_projects_unavailable(correlation_id)
        if project is None:
            _raise_project_not_found(correlation_id)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        return ProjectResponse.model_validate(project)

    @application.post(
        "/projects/{project_id}/documents",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=DocumentIntakeResponse,
    )
    async def upload_document(
        project_id: UUID,
        request: Request,
        response: Response,
    ) -> DocumentIntakeResponse:
        """Accept raw bytes only after owner authorization and bounded preflight."""

        correlation_id = uuid4()
        boundary, project_repository = _project_dependencies(request)
        _authorize_project_resource(
            boundary=boundary,
            request=request,
            action=ProjectAction.INGEST,
            project_id=project_id,
            correlation_id=correlation_id,
        )
        _require_project(project_repository, project_id, correlation_id)
        service = _document_intake_service(request)
        try:
            intake = await service.receive(
                project_id=project_id,
                stream=request.stream(),
                filename=request.headers.get("X-Upload-Filename"),
                content_type=request.headers.get("Content-Type"),
                content_encoding=request.headers.get("Content-Encoding"),
                content_length=request.headers.get("Content-Length"),
            )
        except DocumentIntakeUnavailable:
            _raise_document_intake_unavailable(correlation_id)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        if intake.state is DocumentIntakeState.REJECTED:
            _raise_document_intake_rejected(intake, correlation_id)
        return _document_intake_response(intake)

    @application.post(
        "/projects/{project_id}/analysis-runs",
        status_code=status.HTTP_201_CREATED,
        response_model=AnalysisRunResponse,
    )
    def create_analysis_run(
        project_id: UUID,
        payload: AnalysisRunCreateRequest,
        request: Request,
        response: Response,
    ) -> AnalysisRunResponse:
        correlation_id = uuid4()
        boundary, project_repository = _project_dependencies(request)
        _authorize_project_resource(
            boundary=boundary,
            request=request,
            action=ProjectAction.INVOKE_MODEL,
            project_id=project_id,
            correlation_id=correlation_id,
        )
        _require_project(project_repository, project_id, correlation_id)
        service = _analysis_run_service(request)
        try:
            analysis_run = service.create(
                project_id=project_id,
                synthetic_text=payload.synthetic_text,
                correlation_id=correlation_id,
            )
        except AnalysisRunUnavailable:
            _raise_analysis_runs_unavailable(correlation_id)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        return AnalysisRunResponse.model_validate(analysis_run)

    @application.get(
        "/projects/{project_id}/analysis-runs",
        response_model=list[AnalysisRunResponse],
    )
    def list_analysis_runs(
        project_id: UUID,
        request: Request,
        response: Response,
    ) -> list[AnalysisRunResponse]:
        correlation_id = uuid4()
        boundary, project_repository = _project_dependencies(request)
        _authorize_project_resource(
            boundary=boundary,
            request=request,
            action=ProjectAction.READ,
            project_id=project_id,
            correlation_id=correlation_id,
        )
        _require_project(project_repository, project_id, correlation_id)
        service = _analysis_run_service(request)
        try:
            analysis_runs = service.list_for_project(project_id)
        except AnalysisRunUnavailable:
            _raise_analysis_runs_unavailable(correlation_id)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        return [AnalysisRunResponse.model_validate(item) for item in analysis_runs]

    return application


def _raise_service_unavailable(correlation_id: UUID) -> Never:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=DEMO_UNAVAILABLE_DETAIL,
        headers={"X-Correlation-ID": str(correlation_id)},
    )


def _project_dependencies(
    request: Request,
) -> tuple[ProjectAuthorizationBoundary, ProjectRepository]:
    boundary = getattr(request.app.state, "project_authorization_boundary", None)
    repository = getattr(request.app.state, "project_repository", None)
    if not isinstance(boundary, ProjectAuthorizationBoundary) or repository is None:
        raise RuntimeError("Project boundaries were not initialized")
    return boundary, repository


def _analysis_run_service(
    request: Request,
) -> AnalysisRunService | UnavailableAnalysisRunService:
    service = getattr(request.app.state, "analysis_run_service", None)
    if not isinstance(service, (AnalysisRunService, UnavailableAnalysisRunService)):
        raise RuntimeError("Analysis-run boundary was not initialized")
    return service


def _document_intake_service(request: Request) -> DocumentIntakeService:
    service = getattr(request.app.state, "document_intake_service", None)
    if not isinstance(service, DocumentIntakeService):
        raise RuntimeError("Document-intake boundary was not initialized")
    return service


def _require_project(
    repository: ProjectRepository,
    project_id: UUID,
    correlation_id: UUID,
) -> None:
    try:
        project = repository.get(project_id)
    except ProjectRepositoryUnavailable:
        _raise_projects_unavailable(correlation_id)
    if project is None:
        _raise_project_not_found(correlation_id)


def _authorize_project_collection(
    *,
    boundary: ProjectAuthorizationBoundary,
    request: Request,
    action: ProjectAction,
    correlation_id: UUID,
) -> None:
    try:
        boundary.authorize_collection_request(
            request=request,
            action=action,
            correlation_id=correlation_id,
        )
    except OwnerResolutionFailure as error:
        _raise_owner_resolution_denial(error, correlation_id)
    except AuthorizationDenied as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.public_detail,
            headers={"X-Correlation-ID": str(correlation_id)},
        ) from None
    except AuthorizationAuditUnavailable:
        _raise_projects_unavailable(correlation_id)


def _authorize_project_resource(
    *,
    boundary: ProjectAuthorizationBoundary,
    request: Request,
    action: ProjectAction,
    project_id: UUID,
    correlation_id: UUID,
) -> None:
    try:
        boundary.authorize_request(
            request=request,
            action=action,
            requested_project_id=project_id,
            resource=ProjectResourceReference.project(project_id),
            correlation_id=correlation_id,
        )
    except OwnerResolutionFailure as error:
        _raise_owner_resolution_denial(error, correlation_id)
    except AuthorizationDenied as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.public_detail,
            headers={"X-Correlation-ID": str(correlation_id)},
        ) from None
    except AuthorizationAuditUnavailable:
        _raise_projects_unavailable(correlation_id)


def _raise_owner_resolution_denial(
    error: OwnerResolutionFailure,
    correlation_id: UUID,
) -> Never:
    headers = {"X-Correlation-ID": str(correlation_id)}
    if error.status_code == status.HTTP_401_UNAUTHORIZED:
        headers["WWW-Authenticate"] = "Bearer"
    raise HTTPException(
        status_code=error.status_code,
        detail=error.detail,
        headers=headers,
    )


def _raise_project_not_found(correlation_id: UUID) -> Never:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Project not found",
        headers={"X-Correlation-ID": str(correlation_id)},
    )


def _raise_projects_unavailable(correlation_id: UUID) -> Never:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=PROJECTS_UNAVAILABLE_DETAIL,
        headers={"X-Correlation-ID": str(correlation_id)},
    )


def _raise_analysis_runs_unavailable(correlation_id: UUID) -> Never:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=ANALYSIS_RUNS_UNAVAILABLE_DETAIL,
        headers={"X-Correlation-ID": str(correlation_id)},
    )


def _document_intake_response(intake: DocumentIntake) -> DocumentIntakeResponse:
    return DocumentIntakeResponse(
        id=intake.id,
        project_id=intake.project_id,
        state=intake.state,
        document_id=intake.document_id,
        document_version_id=intake.document_version_id,
        byte_size=intake.byte_size,
        content_sha256=intake.content_sha256,
        rejection_code=intake.rejection_code,
        deduplicated=intake.deduplicated,
        created_at=intake.created_at,
    )


def _raise_document_intake_rejected(
    intake: DocumentIntake, correlation_id: UUID
) -> Never:
    if intake.rejection_code is None:
        raise RuntimeError("Rejected intake must include a rejection code")
    status_code = (
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        if intake.rejection_code in {"UPLOAD_SIZE_LIMIT", "UPLOAD_PROJECT_SIZE_LIMIT"}
        else status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        if intake.rejection_code
        in {
            "UPLOAD_TYPE_UNSUPPORTED",
            "UPLOAD_TYPE_MISMATCH",
            "UPLOAD_CONTENT_ENCODING_UNSUPPORTED",
        }
        else status.HTTP_400_BAD_REQUEST
    )
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": intake.rejection_code,
            "message": "Document upload was rejected",
            "retryable": False,
        },
        headers={"X-Correlation-ID": str(correlation_id)},
    )


def _raise_document_intake_unavailable(correlation_id: UUID) -> Never:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=DOCUMENT_INTAKE_UNAVAILABLE_DETAIL,
        headers={"X-Correlation-ID": str(correlation_id)},
    )


app = create_app()
