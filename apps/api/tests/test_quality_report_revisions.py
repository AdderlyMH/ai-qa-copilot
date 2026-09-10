from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import QualityReportRevisionRecord
from ai_qa_copilot_api.projects import Base, ProjectRecord
from ai_qa_copilot_api.quality_report_revisions import (
    QualityReportRevisionRejected,
    SqlAlchemyQualityReportRevisionRepository,
)
from ai_qa_copilot_api.quality_report_snapshots import (
    QualityReportEvidenceSnapshot,
    QualityReportSnapshotInput,
    SnapshotExecutionEvidenceState,
    build_quality_report_snapshot,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-00000000b001")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-00000000b002")
REPORT_ID = UUID("00000000-0000-0000-0000-00000000b003")


def repository() -> tuple[
    SqlAlchemyQualityReportRevisionRepository,
    sessionmaker[Session],
]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)

    with session_factory.begin() as session:
        session.add_all(
            (
                ProjectRecord(
                    id=PROJECT_ID,
                    name="Report project",
                    description=None,
                    created_at=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc),
                    archived_at=None,
                ),
                ProjectRecord(
                    id=OTHER_PROJECT_ID,
                    name="Other project",
                    description=None,
                    created_at=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc),
                    archived_at=None,
                ),
            )
        )

    return (
        SqlAlchemyQualityReportRevisionRepository(session_factory),
        session_factory,
    )


def snapshot() -> QualityReportEvidenceSnapshot:
    return build_quality_report_snapshot(
        snapshot_input=QualityReportSnapshotInput(
            project_id=PROJECT_ID,
            source_document_version_ids=(),
            citations=(),
            requirement_analysis_runs=(),
            generated_test_cases=(),
            execution_evidence=(),
            failure_analyses=(),
            execution_evidence_state=SnapshotExecutionEvidenceState.NOT_RUN,
            created_at=datetime(2026, 9, 10, 12, 1, tzinfo=timezone.utc),
        ),
        id_factory=lambda: REPORT_ID,
    )


def test_repository_stores_and_reads_one_immutable_snapshot() -> None:
    report_repository, _ = repository()
    original = snapshot()

    stored = report_repository.create(
        project_id=PROJECT_ID,
        snapshot=original,
    )
    fetched = report_repository.get(
        project_id=PROJECT_ID,
        revision_id=REPORT_ID,
    )

    assert fetched == stored
    assert stored.snapshot.canonical_json() == original.canonical_json()
    assert stored.report_sha256 == original.report.content_sha256()
    assert stored.snapshot_sha256 == original.content_sha256()
    assert report_repository.list_for_project(project_id=PROJECT_ID) == (stored,)


def test_repository_returns_same_revision_for_an_idempotent_snapshot_retry() -> None:
    report_repository, _ = repository()
    original = snapshot()

    first = report_repository.create(
        project_id=PROJECT_ID,
        snapshot=original,
    )
    second = report_repository.create(
        project_id=PROJECT_ID,
        snapshot=original,
    )

    assert second == first
    assert report_repository.list_for_project(project_id=PROJECT_ID) == (first,)


def test_repository_denies_cross_project_reads() -> None:
    report_repository, _ = repository()
    report_repository.create(
        project_id=PROJECT_ID,
        snapshot=snapshot(),
    )

    assert (
        report_repository.get(
            project_id=OTHER_PROJECT_ID,
            revision_id=REPORT_ID,
        )
        is None
    )
    assert report_repository.list_for_project(project_id=OTHER_PROJECT_ID) == ()


def test_repository_rejects_summary_tampering_before_persistence() -> None:
    report_repository, _ = repository()
    original = snapshot()
    tampered = replace(
        original,
        summary=replace(original.summary, execution_count=1),
    )

    with pytest.raises(
        QualityReportRevisionRejected,
        match="violates the immutable snapshot contract",
    ):
        report_repository.create(
            project_id=PROJECT_ID,
            snapshot=tampered,
        )


def test_repository_rejects_a_durable_hash_mismatch_on_read() -> None:
    report_repository, session_factory = repository()
    report_repository.create(
        project_id=PROJECT_ID,
        snapshot=snapshot(),
    )

    with session_factory.begin() as session:
        record = session.get(QualityReportRevisionRecord, REPORT_ID)
        assert record is not None
        record.snapshot_sha256 = "0" * 64

    with pytest.raises(
        QualityReportRevisionRejected,
        match="snapshot hash does not match",
    ):
        report_repository.get(
            project_id=PROJECT_ID,
            revision_id=REPORT_ID,
        )


POSTGRES_INTEGRATION_DATABASE_URL = "AI_QA_COPILOT_POSTGRES_INTEGRATION_DATABASE_URL"


@pytest.mark.postgres_integration
def test_postgres_repository_persists_immutable_revision() -> None:
    database_url = os.environ.get(POSTGRES_INTEGRATION_DATABASE_URL, "").strip()
    if not database_url:
        pytest.skip("requires the isolated PostgreSQL database from db-check")

    engine = create_engine(database_url)
    foreign_project_id = UUID("00000000-0000-0000-0000-000000000099")
    repository = SqlAlchemyQualityReportRevisionRepository.from_database_url(
        database_url
    )

    try:
        with engine.begin() as connection:
            connection.execute(
                text("TRUNCATE TABLE quality_report_revisions, projects CASCADE")
            )
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, name, description, created_at, archived_at) "
                    "VALUES "
                    "(:project_id, 'Report project', NULL, CURRENT_TIMESTAMP, NULL), "
                    "(:foreign_project_id, 'Foreign project', NULL, CURRENT_TIMESTAMP, NULL)"
                ),
                {
                    "project_id": PROJECT_ID,
                    "foreign_project_id": foreign_project_id,
                },
            )

        stored = repository.create(
            project_id=PROJECT_ID,
            snapshot=snapshot(),
        )
        retried = repository.create(
            project_id=PROJECT_ID,
            snapshot=snapshot(),
        )

        assert retried == stored
        assert repository.get(project_id=PROJECT_ID, revision_id=stored.id) == stored
        assert repository.list_for_project(project_id=PROJECT_ID) == (stored,)
        assert (
            repository.get(
                project_id=foreign_project_id,
                revision_id=stored.id,
            )
            is None
        )

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT project_id, schema_version, canonical_report_json, "
                    "snapshot_json, report_sha256, snapshot_sha256 "
                    "FROM quality_report_revisions WHERE id = :revision_id"
                ),
                {"revision_id": stored.id},
            ).one()

        assert row.project_id == PROJECT_ID
        assert row.schema_version == stored.schema_version
        assert row.canonical_report_json
        assert row.snapshot_json
        assert row.report_sha256 == stored.report_sha256
        assert row.snapshot_sha256 == stored.snapshot_sha256
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("TRUNCATE TABLE quality_report_revisions, projects CASCADE")
            )
        engine.dispose()
