"""Immutable persistence boundary for canonical QA report evidence snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from typing import Protocol
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import QualityReportRevisionRecord
from ai_qa_copilot_api.quality_report_snapshots import (
    QualityReportEvidenceSnapshot,
    QualityReportSnapshotRejected,
    validate_quality_report_evidence_snapshot,
)
from ai_qa_copilot_api.quality_reports import QUALITY_REPORT_SCHEMA_VERSION


class QualityReportRevisionUnavailable(RuntimeError):
    """Raised when durable quality-report revision state cannot be accessed."""


class QualityReportRevisionRejected(ValueError):
    """Raised when a report revision is malformed, altered, or out of scope."""


@dataclass(frozen=True)
class StoredQualityReportRevision:
    """One immutable, project-scoped canonical QA report revision."""

    id: UUID
    project_id: UUID
    schema_version: str
    snapshot: QualityReportEvidenceSnapshot
    report_sha256: str
    snapshot_sha256: str
    created_at: datetime


class QualityReportRevisionRepository(Protocol):
    """Durable boundary for immutable report snapshot creation and viewing."""

    def create(
        self,
        *,
        project_id: UUID,
        snapshot: QualityReportEvidenceSnapshot,
    ) -> StoredQualityReportRevision: ...

    def get(
        self,
        *,
        project_id: UUID,
        revision_id: UUID,
    ) -> StoredQualityReportRevision | None: ...

    def list_for_project(
        self,
        *,
        project_id: UUID,
    ) -> tuple[StoredQualityReportRevision, ...]: ...


class SqlAlchemyQualityReportRevisionRepository:
    """Persist and read immutable canonical snapshot revisions only."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
    ) -> None:
        self._session_factory = session_factory

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
    ) -> SqlAlchemyQualityReportRevisionRepository:
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def create(
        self,
        *,
        project_id: UUID,
        snapshot: QualityReportEvidenceSnapshot,
    ) -> StoredQualityReportRevision:
        validated_snapshot = _validated_snapshot_for_project(
            project_id=project_id,
            snapshot=snapshot,
        )
        canonical_report_json = validated_snapshot.report.canonical_json()
        snapshot_json = validated_snapshot.canonical_json()
        report_sha256 = validated_snapshot.report.content_sha256()
        snapshot_sha256 = validated_snapshot.content_sha256()

        try:
            with self._session_factory.begin() as session:
                existing_by_snapshot = session.execute(
                    select(QualityReportRevisionRecord)
                    .where(
                        QualityReportRevisionRecord.project_id == project_id,
                        QualityReportRevisionRecord.snapshot_sha256 == snapshot_sha256,
                    )
                    .with_for_update()
                ).scalar_one_or_none()

                if existing_by_snapshot is not None:
                    existing = _stored_revision_from_record(existing_by_snapshot)
                    if existing.snapshot.canonical_json() == snapshot_json:
                        return existing
                    raise QualityReportRevisionRejected(
                        "A report snapshot hash already identifies different content"
                    )

                existing_by_id = session.get(
                    QualityReportRevisionRecord,
                    validated_snapshot.report.id,
                )
                if existing_by_id is not None:
                    existing = _stored_revision_from_record(existing_by_id)
                    if (
                        existing.project_id == project_id
                        and existing.snapshot.canonical_json() == snapshot_json
                    ):
                        return existing
                    raise QualityReportRevisionRejected(
                        "A quality report revision id cannot be reused"
                    )

                record = QualityReportRevisionRecord(
                    id=validated_snapshot.report.id,
                    project_id=project_id,
                    schema_version=QUALITY_REPORT_SCHEMA_VERSION,
                    canonical_report_json=canonical_report_json,
                    snapshot_json=snapshot_json,
                    report_sha256=report_sha256,
                    snapshot_sha256=snapshot_sha256,
                    created_at=validated_snapshot.report.created_at,
                )
                session.add(record)
                session.flush()

                return _stored_revision_from_record(record)
        except QualityReportRevisionRejected:
            raise
        except SQLAlchemyError as error:
            raise QualityReportRevisionUnavailable from error

    def get(
        self,
        *,
        project_id: UUID,
        revision_id: UUID,
    ) -> StoredQualityReportRevision | None:
        try:
            with self._session_factory() as session:
                record = session.execute(
                    select(QualityReportRevisionRecord).where(
                        QualityReportRevisionRecord.id == revision_id,
                        QualityReportRevisionRecord.project_id == project_id,
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise QualityReportRevisionUnavailable from error

        return _stored_revision_from_record(record) if record is not None else None

    def list_for_project(
        self,
        *,
        project_id: UUID,
    ) -> tuple[StoredQualityReportRevision, ...]:
        statement = (
            select(QualityReportRevisionRecord)
            .where(QualityReportRevisionRecord.project_id == project_id)
            .order_by(
                QualityReportRevisionRecord.created_at.desc(),
                QualityReportRevisionRecord.id.desc(),
            )
        )

        try:
            with self._session_factory() as session:
                records = tuple(session.scalars(statement))
        except SQLAlchemyError as error:
            raise QualityReportRevisionUnavailable from error

        return tuple(_stored_revision_from_record(record) for record in records)


class UnavailableQualityReportRevisionRepository:
    """Fail closed until durable report storage is configured."""

    def create(
        self,
        *,
        project_id: UUID,
        snapshot: QualityReportEvidenceSnapshot,
    ) -> StoredQualityReportRevision:
        del project_id, snapshot
        raise QualityReportRevisionUnavailable

    def get(
        self,
        *,
        project_id: UUID,
        revision_id: UUID,
    ) -> StoredQualityReportRevision | None:
        del project_id, revision_id
        raise QualityReportRevisionUnavailable

    def list_for_project(
        self,
        *,
        project_id: UUID,
    ) -> tuple[StoredQualityReportRevision, ...]:
        del project_id
        raise QualityReportRevisionUnavailable


def quality_report_revision_repository_from_environment() -> (
    QualityReportRevisionRepository
):
    """Build immutable report persistence only from DATABASE_URL."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableQualityReportRevisionRepository()
    return SqlAlchemyQualityReportRevisionRepository.from_database_url(database_url)


def _validated_snapshot_for_project(
    *,
    project_id: UUID,
    snapshot: QualityReportEvidenceSnapshot,
) -> QualityReportEvidenceSnapshot:
    if not isinstance(project_id, UUID):
        raise QualityReportRevisionRejected("Quality report project id must be a UUID")
    if not isinstance(snapshot, QualityReportEvidenceSnapshot):
        raise QualityReportRevisionRejected("Quality report snapshot is malformed")

    try:
        validated_snapshot = validate_quality_report_evidence_snapshot(
            snapshot.as_payload()
        )
    except QualityReportSnapshotRejected as error:
        raise QualityReportRevisionRejected(
            "Quality report snapshot violates the immutable snapshot contract"
        ) from error

    if validated_snapshot.report.project_id != project_id:
        raise QualityReportRevisionRejected(
            "Quality report snapshot does not belong to the supplied project"
        )

    return validated_snapshot


def _stored_revision_from_record(
    record: QualityReportRevisionRecord,
) -> StoredQualityReportRevision:
    if record.schema_version != QUALITY_REPORT_SCHEMA_VERSION:
        raise QualityReportRevisionRejected(
            "Quality report revision has an unsupported schema version"
        )

    try:
        parsed_snapshot: object = json.loads(record.snapshot_json)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise QualityReportRevisionRejected(
            "Quality report revision snapshot JSON is malformed"
        ) from error

    if not isinstance(parsed_snapshot, dict):
        raise QualityReportRevisionRejected(
            "Quality report revision snapshot JSON must be an object"
        )

    try:
        snapshot = validate_quality_report_evidence_snapshot(parsed_snapshot)
    except QualityReportSnapshotRejected as error:
        raise QualityReportRevisionRejected(
            "Quality report revision snapshot violates the immutable snapshot contract"
        ) from error

    canonical_report_json = snapshot.report.canonical_json()
    canonical_snapshot_json = snapshot.canonical_json()
    report_sha256 = snapshot.report.content_sha256()
    snapshot_sha256 = snapshot.content_sha256()

    if record.id != snapshot.report.id:
        raise QualityReportRevisionRejected(
            "Quality report revision id does not match its canonical report"
        )
    if record.project_id != snapshot.report.project_id:
        raise QualityReportRevisionRejected(
            "Quality report revision project does not match its canonical report"
        )
    if record.canonical_report_json != canonical_report_json:
        raise QualityReportRevisionRejected(
            "Quality report revision canonical report JSON does not match"
        )
    if record.snapshot_json != canonical_snapshot_json:
        raise QualityReportRevisionRejected(
            "Quality report revision snapshot JSON is not canonical"
        )
    if record.report_sha256 != report_sha256:
        raise QualityReportRevisionRejected(
            "Quality report revision canonical report hash does not match"
        )
    if record.snapshot_sha256 != snapshot_sha256:
        raise QualityReportRevisionRejected(
            "Quality report revision snapshot hash does not match"
        )
    if _utc_datetime(record.created_at) != snapshot.report.created_at:
        raise QualityReportRevisionRejected(
            "Quality report revision timestamp does not match its canonical report"
        )

    return StoredQualityReportRevision(
        id=record.id,
        project_id=record.project_id,
        schema_version=record.schema_version,
        snapshot=snapshot,
        report_sha256=record.report_sha256,
        snapshot_sha256=record.snapshot_sha256,
        created_at=_utc_datetime(record.created_at),
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
