"""Central fail-closed project authorization policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Never
from uuid import UUID

from fastapi import Request

from ai_qa_copilot_api.audit import (
    AuditPrincipalType,
    AuditResult,
    AuthorizationActor,
    AuthorizationAuditor,
)
from ai_qa_copilot_api.auth import (
    AnonymousGuestPrincipal,
    AuthBoundary,
    CognitoOwnerPrincipal,
    LocalDevelopmentOwnerPrincipal,
    OwnerResolutionFailure,
    OwnerPrincipal,
)


PRIVATE_RESOURCE_NOT_FOUND_DETAIL = "Resource not found"
LOCAL_DEVELOPMENT_ACTOR_ID = "local-development-owner"


class ProjectAction(StrEnum):
    """Project-scoped actions whose authority must remain deterministic."""

    READ = "project.read"
    MUTATE = "project.mutate"
    READ_RAW_OBJECT = "project.raw_object.read"
    INVOKE_MODEL = "project.model.invoke"
    ENQUEUE_JOB = "project.job.enqueue"
    APPROVE = "project.approval.mutate"
    EXECUTE = "project.execution.start"


class ProjectResourceType(StrEnum):
    """Private resource categories protected by the project boundary."""

    PROJECT = "project"
    ARTIFACT = "artifact"
    RAW_OBJECT = "raw_object"
    REPORT = "report"
    JOB = "job"
    APPROVAL = "approval"
    EXECUTION = "execution"


class DenialDisclosure(StrEnum):
    """Safe public response strategy for a denied authorization decision."""

    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class ProjectResourceReference:
    """Trusted repository reference used for an exact project-scope check."""

    project_id: UUID
    resource_type: ProjectResourceType
    resource_id: UUID
    resource_version: str | None = None

    def __post_init__(self) -> None:
        if self.project_id.int == 0 or self.resource_id.int == 0:
            raise ValueError("Project and resource IDs must be non-zero UUIDs")
        if self.resource_version is not None and (
            not self.resource_version
            or self.resource_version != self.resource_version.strip()
        ):
            raise ValueError("Resource version must be a non-empty value when present")

    @classmethod
    def project(cls, project_id: UUID) -> ProjectResourceReference:
        return cls(
            project_id=project_id,
            resource_type=ProjectResourceType.PROJECT,
            resource_id=project_id,
        )


ApplicationPrincipal = OwnerPrincipal | AnonymousGuestPrincipal


@dataclass(frozen=True)
class AuthorizedProjectScope:
    """Capability returned only after an owner and exact scope are authorized."""

    principal: OwnerPrincipal
    project_id: UUID
    action: ProjectAction
    resource: ProjectResourceReference


class AuthorizationDenied(Exception):
    """Deterministic denial with a safe HTTP disclosure strategy."""

    def __init__(
        self,
        *,
        disclosure: DenialDisclosure,
        public_detail: str,
        reason: str,
    ) -> None:
        super().__init__(public_detail)
        self.disclosure = disclosure
        self.public_detail = public_detail
        self.reason = reason

    @property
    def status_code(self) -> Literal[403, 404]:
        if self.disclosure is DenialDisclosure.FORBIDDEN:
            return 403
        return 404


def actor_for_principal(principal: ApplicationPrincipal) -> AuthorizationActor:
    """Convert a trusted application principal to safe audit identity data."""

    if isinstance(principal, CognitoOwnerPrincipal):
        return AuthorizationActor(
            principal_type=AuditPrincipalType.OWNER,
            actor_id=principal.subject,
        )
    if isinstance(principal, LocalDevelopmentOwnerPrincipal):
        return AuthorizationActor(
            principal_type=AuditPrincipalType.OWNER,
            actor_id=LOCAL_DEVELOPMENT_ACTOR_ID,
        )
    return AuthorizationActor(
        principal_type=AuditPrincipalType.GUEST,
        actor_id=None,
    )


def actor_for_owner_resolution_failure(
    error: OwnerResolutionFailure,
) -> AuthorizationActor:
    """Retain a validated non-owner subject but no untrusted token identity."""

    return AuthorizationActor(
        principal_type=(
            AuditPrincipalType.AUTHENTICATED_NON_OWNER
            if error.actor_id is not None
            else AuditPrincipalType.UNKNOWN
        ),
        actor_id=error.actor_id,
    )


class ProjectAuthorizationPolicy:
    """Authorize only an owner operating on one exact project resource scope."""

    def __init__(self, auditor: AuthorizationAuditor) -> None:
        self._auditor = auditor

    def authorize(
        self,
        *,
        principal: ApplicationPrincipal,
        action: ProjectAction,
        requested_project_id: UUID,
        resource: ProjectResourceReference,
        correlation_id: UUID,
    ) -> AuthorizedProjectScope:
        actor = actor_for_principal(principal)

        raw_object_action_mismatch = (
            resource.resource_type is ProjectResourceType.RAW_OBJECT
            and action is not ProjectAction.READ_RAW_OBJECT
        ) or (
            action is ProjectAction.READ_RAW_OBJECT
            and resource.resource_type is not ProjectResourceType.RAW_OBJECT
        )
        if raw_object_action_mismatch or (
            resource.resource_type is ProjectResourceType.RAW_OBJECT
            and resource.resource_version is None
        ):
            self._deny(
                correlation_id=correlation_id,
                actor=actor,
                action=action,
                reason="raw_object_action_or_version_invalid",
                requested_project_id=requested_project_id,
                resource=resource,
            )

        if not isinstance(
            principal,
            (CognitoOwnerPrincipal, LocalDevelopmentOwnerPrincipal),
        ):
            self._deny(
                correlation_id=correlation_id,
                actor=actor,
                action=action,
                reason="guest_private_project_access",
                requested_project_id=requested_project_id,
                resource=resource,
            )

        if requested_project_id != resource.project_id:
            self._deny(
                correlation_id=correlation_id,
                actor=actor,
                action=action,
                reason="project_scope_mismatch",
                requested_project_id=requested_project_id,
                resource=resource,
            )

        self._record(
            correlation_id=correlation_id,
            actor=actor,
            action=action,
            result=AuditResult.ALLOWED,
            reason="owner_project_scope_match",
            requested_project_id=requested_project_id,
            resource=resource,
        )
        return AuthorizedProjectScope(
            principal=principal,
            project_id=requested_project_id,
            action=action,
            resource=resource,
        )

    def _deny(
        self,
        *,
        correlation_id: UUID,
        actor: AuthorizationActor,
        action: ProjectAction,
        reason: str,
        requested_project_id: UUID,
        resource: ProjectResourceReference,
    ) -> Never:
        self._record(
            correlation_id=correlation_id,
            actor=actor,
            action=action,
            result=AuditResult.DENIED,
            reason=reason,
            requested_project_id=requested_project_id,
            resource=resource,
        )
        raise AuthorizationDenied(
            disclosure=DenialDisclosure.NOT_FOUND,
            public_detail=PRIVATE_RESOURCE_NOT_FOUND_DETAIL,
            reason=reason,
        )

    def _record(
        self,
        *,
        correlation_id: UUID,
        actor: AuthorizationActor,
        action: ProjectAction,
        result: AuditResult,
        reason: str,
        requested_project_id: UUID,
        resource: ProjectResourceReference,
    ) -> None:
        self._auditor.record(
            correlation_id=correlation_id,
            actor=actor,
            action=action.value,
            result=result,
            reason=reason,
            resource_type=resource.resource_type.value,
            resource_id=str(resource.resource_id),
            resource_version=resource.resource_version,
            project_id=str(requested_project_id),
        )


class ProjectAuthorizationBoundary:
    """Resolve owner identity and project scope as one audited request boundary."""

    def __init__(
        self,
        auth_boundary: AuthBoundary,
        policy: ProjectAuthorizationPolicy,
        auditor: AuthorizationAuditor,
    ) -> None:
        self._auth_boundary = auth_boundary
        self._policy = policy
        self._auditor = auditor

    def authorize_request(
        self,
        *,
        request: Request,
        action: ProjectAction,
        requested_project_id: UUID,
        resource: ProjectResourceReference,
        correlation_id: UUID,
    ) -> AuthorizedProjectScope:
        try:
            principal = self._auth_boundary.resolve_owner(request)
        except OwnerResolutionFailure as error:
            self._auditor.record(
                correlation_id=correlation_id,
                actor=actor_for_owner_resolution_failure(error),
                action=action.value,
                result=AuditResult.DENIED,
                reason=error.reason,
                resource_type=resource.resource_type.value,
                resource_id=str(resource.resource_id),
                resource_version=resource.resource_version,
                project_id=str(requested_project_id),
            )
            raise

        return self._policy.authorize(
            principal=principal,
            action=action,
            requested_project_id=requested_project_id,
            resource=resource,
            correlation_id=correlation_id,
        )
