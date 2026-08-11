"""Immutable server-selected public demo publication boundary."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Never, Protocol
from uuid import UUID

from ai_qa_copilot_api.audit import (
    AuditResult,
    AuthorizationActor,
    AuthorizationAuditor,
)
from ai_qa_copilot_api.authorization import (
    ApplicationPrincipal,
    AuthorizationDenied,
    DenialDisclosure,
    actor_for_principal,
)


DEMO_PUBLICATION_ID_VARIABLE = "DEMO_PUBLICATION_ID"
DEMO_PUBLICATION_REVISION_ID_VARIABLE = "DEMO_PUBLICATION_REVISION_ID"
DEMO_NOT_FOUND_DETAIL = "Demo publication not found"
DEMO_READ_ONLY_DETAIL = "Demo publication is read-only"
DEMO_UNAVAILABLE_DETAIL = "Demo publication is temporarily unavailable"
MAX_DEMO_TITLE_LENGTH = 200
MAX_DEMO_SUMMARY_LENGTH = 2_000
MAX_CITATION_EXCERPT_REVISIONS = 100
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class DemoConfigurationError(RuntimeError):
    """Raised when server-side demo selection configuration is incomplete."""


class DemoPublicationUnavailable(RuntimeError):
    """Raised when the selected publication cannot be read safely."""


class DemoDataClassification(StrEnum):
    """Data classifications retained on a publication record."""

    SYNTHETIC = "synthetic"
    PUBLIC = "public"
    PRIVATE = "private"
    CONFIDENTIAL = "confidential"


class DemoPublicationState(StrEnum):
    """Immutable publication lifecycle states."""

    DRAFT = "draft"
    PUBLISHED = "published"
    REPLACED = "replaced"


@dataclass(frozen=True)
class DemoPublicationSelection:
    """Exact publication revision selected only by server configuration."""

    publication_id: UUID
    publication_revision_id: UUID

    def __post_init__(self) -> None:
        if self.publication_id.int == 0 or self.publication_revision_id.int == 0:
            raise ValueError("Demo publication selection IDs must be non-zero UUIDs")


@dataclass(frozen=True)
class DemoPublicationSettings:
    """Optional fail-closed public demo selection."""

    selection: DemoPublicationSelection | None

    @classmethod
    def from_environment(cls) -> DemoPublicationSettings:
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, environment: Mapping[str, str]) -> DemoPublicationSettings:
        raw_publication_id = environment.get(DEMO_PUBLICATION_ID_VARIABLE, "").strip()
        raw_revision_id = environment.get(
            DEMO_PUBLICATION_REVISION_ID_VARIABLE, ""
        ).strip()
        if bool(raw_publication_id) != bool(raw_revision_id):
            raise DemoConfigurationError(
                f"{DEMO_PUBLICATION_ID_VARIABLE} and "
                f"{DEMO_PUBLICATION_REVISION_ID_VARIABLE} must be configured together"
            )
        if not raw_publication_id:
            return cls(selection=None)
        try:
            selection = DemoPublicationSelection(
                publication_id=UUID(raw_publication_id),
                publication_revision_id=UUID(raw_revision_id),
            )
        except ValueError as error:
            raise DemoConfigurationError(
                "Demo publication selection values must be non-zero UUIDs"
            ) from error
        return cls(selection=selection)


@dataclass(frozen=True)
class DemoPublication:
    """Repository record whose public eligibility is always revalidated."""

    selection: DemoPublicationSelection
    project_id: UUID
    report_revision_id: UUID
    traceability_revision_id: UUID
    citation_excerpt_revision_ids: tuple[UUID, ...]
    title: str
    summary: str
    data_classification: DemoDataClassification
    sanitization_policy_version: str
    content_hash: str
    state: DemoPublicationState
    sanitized: bool
    immutable: bool

    def expected_content_hash(self) -> str:
        """Hash the canonical public projection and its private scope binding."""

        payload = {
            "publication_id": str(self.selection.publication_id),
            "publication_revision_id": str(self.selection.publication_revision_id),
            "project_id": str(self.project_id),
            "report_revision_id": str(self.report_revision_id),
            "traceability_revision_id": str(self.traceability_revision_id),
            "citation_excerpt_revision_ids": [
                str(revision_id) for revision_id in self.citation_excerpt_revision_ids
            ],
            "title": self.title,
            "summary": self.summary,
            "data_classification": self.data_classification.value,
            "sanitization_policy_version": self.sanitization_policy_version,
        }
        canonical_bytes = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{sha256(canonical_bytes).hexdigest()}"


@dataclass(frozen=True)
class PublicDemoPublication:
    """Public response projection with no project or raw-object identifiers."""

    publication_id: UUID
    publication_revision_id: UUID
    report_revision_id: UUID
    traceability_revision_id: UUID
    citation_excerpt_revision_ids: tuple[UUID, ...]
    title: str
    summary: str
    content_hash: str


class DemoPublicationRepository(Protocol):
    """Exact-selection repository port implemented by later persistence work."""

    def get_exact(
        self, selection: DemoPublicationSelection
    ) -> DemoPublication | None: ...


class UnavailableDemoPublicationRepository:
    """Fail-closed default until a persistence adapter is configured."""

    def get_exact(self, selection: DemoPublicationSelection) -> None:
        del selection
        return None


class DemoPublicationService:
    """Resolve one server-selected immutable sanitized publication."""

    def __init__(
        self,
        settings: DemoPublicationSettings,
        repository: DemoPublicationRepository,
        auditor: AuthorizationAuditor,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._auditor = auditor

    def read_selected(
        self,
        *,
        principal: ApplicationPrincipal,
        method: str,
        correlation_id: UUID,
    ) -> PublicDemoPublication:
        actor = actor_for_principal(principal)
        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD"}:
            self._deny(
                actor=actor,
                correlation_id=correlation_id,
                action="demo.write",
                reason="demo_route_read_only",
                disclosure=DenialDisclosure.FORBIDDEN,
                public_detail=DEMO_READ_ONLY_DETAIL,
            )

        selection = self._settings.selection
        if selection is None:
            self._deny(
                actor=actor,
                correlation_id=correlation_id,
                action="demo.read",
                reason="demo_publication_not_configured",
            )

        try:
            publication = self._repository.get_exact(selection)
        except Exception as error:
            self._record(
                actor=actor,
                correlation_id=correlation_id,
                action="demo.read",
                result=AuditResult.DENIED,
                reason="demo_repository_unavailable",
                selection=selection,
            )
            raise DemoPublicationUnavailable(DEMO_UNAVAILABLE_DETAIL) from error

        if publication is None or not self._is_public(publication, selection):
            self._deny(
                actor=actor,
                correlation_id=correlation_id,
                action="demo.read",
                reason="demo_publication_not_public",
                selection=selection,
                project_id=publication.project_id if publication is not None else None,
            )

        self._record(
            actor=actor,
            correlation_id=correlation_id,
            action="demo.read",
            result=AuditResult.ALLOWED,
            reason="server_selected_sanitized_publication",
            selection=selection,
            project_id=publication.project_id,
        )
        return PublicDemoPublication(
            publication_id=publication.selection.publication_id,
            publication_revision_id=publication.selection.publication_revision_id,
            report_revision_id=publication.report_revision_id,
            traceability_revision_id=publication.traceability_revision_id,
            citation_excerpt_revision_ids=publication.citation_excerpt_revision_ids,
            title=publication.title,
            summary=publication.summary,
            content_hash=publication.content_hash,
        )

    def audit_identity_denial(
        self,
        *,
        actor: AuthorizationActor,
        method: str,
        correlation_id: UUID,
        reason: str,
    ) -> None:
        self._record(
            actor=actor,
            correlation_id=correlation_id,
            action="demo.read" if method.upper() in {"GET", "HEAD"} else "demo.write",
            result=AuditResult.DENIED,
            reason=reason,
            selection=self._settings.selection,
        )

    def _deny(
        self,
        *,
        actor: AuthorizationActor,
        correlation_id: UUID,
        action: str,
        reason: str,
        selection: DemoPublicationSelection | None = None,
        project_id: UUID | None = None,
        disclosure: DenialDisclosure = DenialDisclosure.NOT_FOUND,
        public_detail: str = DEMO_NOT_FOUND_DETAIL,
    ) -> Never:
        self._record(
            actor=actor,
            correlation_id=correlation_id,
            action=action,
            result=AuditResult.DENIED,
            reason=reason,
            selection=selection,
            project_id=project_id,
        )
        raise AuthorizationDenied(
            disclosure=disclosure,
            public_detail=public_detail,
            reason=reason,
        )

    def _record(
        self,
        *,
        actor: AuthorizationActor,
        correlation_id: UUID,
        action: str,
        result: AuditResult,
        reason: str,
        selection: DemoPublicationSelection | None,
        project_id: UUID | None = None,
    ) -> None:
        self._auditor.record(
            correlation_id=correlation_id,
            actor=actor,
            action=action,
            result=result,
            reason=reason,
            resource_type="demo_publication",
            resource_id=(
                str(selection.publication_id) if selection is not None else None
            ),
            resource_version=(
                str(selection.publication_revision_id)
                if selection is not None
                else None
            ),
            project_id=str(project_id) if project_id is not None else None,
        )

    @staticmethod
    def _is_public(
        publication: DemoPublication,
        selection: DemoPublicationSelection,
    ) -> bool:
        try:
            return all(
                (
                    publication.selection == selection,
                    publication.project_id.int != 0,
                    publication.report_revision_id.int != 0,
                    publication.traceability_revision_id.int != 0,
                    bool(publication.citation_excerpt_revision_ids),
                    len(publication.citation_excerpt_revision_ids)
                    <= MAX_CITATION_EXCERPT_REVISIONS,
                    all(
                        revision_id.int != 0
                        for revision_id in publication.citation_excerpt_revision_ids
                    ),
                    len(set(publication.citation_excerpt_revision_ids))
                    == len(publication.citation_excerpt_revision_ids),
                    bool(publication.title.strip()),
                    publication.title == publication.title.strip(),
                    len(publication.title) <= MAX_DEMO_TITLE_LENGTH,
                    bool(publication.summary.strip()),
                    publication.summary == publication.summary.strip(),
                    len(publication.summary) <= MAX_DEMO_SUMMARY_LENGTH,
                    publication.data_classification
                    in {
                        DemoDataClassification.SYNTHETIC,
                        DemoDataClassification.PUBLIC,
                    },
                    bool(publication.sanitization_policy_version.strip()),
                    publication.sanitization_policy_version
                    == publication.sanitization_policy_version.strip(),
                    SHA256_PATTERN.fullmatch(publication.content_hash) is not None,
                    publication.content_hash == publication.expected_content_hash(),
                    publication.state is DemoPublicationState.PUBLISHED,
                    publication.sanitized,
                    publication.immutable,
                )
            )
        except (AttributeError, TypeError, ValueError):
            return False
