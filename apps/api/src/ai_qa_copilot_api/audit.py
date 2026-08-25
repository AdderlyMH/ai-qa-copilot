"""Append-only authorization audit-event boundary."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4


AUTHORIZATION_AUDIT_LOGGER = "ai_qa_copilot_api.authorization_audit"


class AuditPrincipalType(StrEnum):
    """Trusted principal categories retained in authorization audit events."""

    OWNER = "owner"
    GUEST = "guest"
    AUTHENTICATED_NON_OWNER = "authenticated_non_owner"
    UNKNOWN = "unknown"


class AuditResult(StrEnum):
    """Possible deterministic authorization outcomes."""

    ALLOWED = "allowed"
    DENIED = "denied"


@dataclass(frozen=True)
class AuthorizationActor:
    """Actor data safe to retain after identity processing."""

    principal_type: AuditPrincipalType
    actor_id: str | None

    def __post_init__(self) -> None:
        identified_types = {
            AuditPrincipalType.OWNER,
            AuditPrincipalType.AUTHENTICATED_NON_OWNER,
        }
        if self.principal_type in identified_types:
            if self.actor_id is None or not self.actor_id.strip():
                raise ValueError("Identified authorization actors require an actor ID")
        elif self.actor_id is not None:
            raise ValueError("Guest and unknown actors must not carry an actor ID")


@dataclass(frozen=True)
class AuthorizationAuditEvent:
    """Immutable authorization decision record passed to an append-only sink."""

    event_id: UUID
    occurred_at: datetime
    correlation_id: UUID
    principal_type: AuditPrincipalType
    actor_id: str | None
    action: str
    result: AuditResult
    reason: str
    resource_type: str
    resource_id: str | None
    resource_version: str | None
    project_id: str | None

    def __post_init__(self) -> None:
        if self.event_id.int == 0 or self.correlation_id.int == 0:
            raise ValueError("Authorization audit IDs must be non-zero UUIDs")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("Authorization audit timestamps must be timezone-aware")
        AuthorizationActor(
            principal_type=self.principal_type,
            actor_id=self.actor_id,
        )
        for name, required_value in (
            ("action", self.action),
            ("reason", self.reason),
            ("resource_type", self.resource_type),
        ):
            if not required_value or required_value != required_value.strip():
                raise ValueError(f"Authorization audit {name} must be non-empty")
        for name, optional_value in (
            ("resource_id", self.resource_id),
            ("resource_version", self.resource_version),
            ("project_id", self.project_id),
        ):
            if optional_value is not None and (
                not optional_value or optional_value != optional_value.strip()
            ):
                raise ValueError(
                    f"Authorization audit {name} must be non-empty when present"
                )

    def as_dict(self) -> dict[str, object]:
        """Return a stable structured-log representation without credentials."""

        return {
            "event_id": str(self.event_id),
            "occurred_at": self.occurred_at.astimezone(timezone.utc).isoformat(),
            "correlation_id": str(self.correlation_id),
            "principal_type": self.principal_type.value,
            "actor_id": self.actor_id,
            "action": self.action,
            "result": self.result.value,
            "reason": self.reason,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "resource_version": self.resource_version,
            "project_id": self.project_id,
        }


class AuthorizationAuditSink(Protocol):
    """Port for an append-only authorization-event destination."""

    def record(self, event: AuthorizationAuditEvent) -> None: ...


class AuthorizationAuditUnavailable(RuntimeError):
    """Raised when a security-sensitive decision cannot be audited."""


class StructuredLoggingAuditSink:
    """Default JSON logging adapter; durable persistence is a later adapter."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(AUTHORIZATION_AUDIT_LOGGER)

    def record(self, event: AuthorizationAuditEvent) -> None:
        payload = json.dumps(
            event.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        self._logger.info("authorization_audit=%s", payload)


def utc_now() -> datetime:
    """Return an aware UTC timestamp for an audit event."""

    return datetime.now(timezone.utc)


class AuthorizationAuditor:
    """Construct complete immutable events and fail closed on sink errors."""

    def __init__(
        self,
        sink: AuthorizationAuditSink,
        *,
        clock: Callable[[], datetime] = utc_now,
        event_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._sink = sink
        self._clock = clock
        self._event_id_factory = event_id_factory

    def record(
        self,
        *,
        correlation_id: UUID,
        actor: AuthorizationActor,
        action: str,
        result: AuditResult,
        reason: str,
        resource_type: str,
        resource_id: str | None = None,
        resource_version: str | None = None,
        project_id: str | None = None,
    ) -> AuthorizationAuditEvent:
        event = AuthorizationAuditEvent(
            event_id=self._event_id_factory(),
            occurred_at=self._clock(),
            correlation_id=correlation_id,
            principal_type=actor.principal_type,
            actor_id=actor.actor_id,
            action=action,
            result=result,
            reason=reason,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=resource_version,
            project_id=project_id,
        )
        try:
            self._sink.record(event)
        except Exception as error:
            raise AuthorizationAuditUnavailable(
                "Authorization audit sink rejected the decision"
            ) from error
        return event
