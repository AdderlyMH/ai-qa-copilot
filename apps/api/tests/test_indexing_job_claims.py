from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, event, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    DocumentRecord,
    DocumentVersionRecord,
    IndexingJobRecord,
    ParserVersionRecord,
)
from ai_qa_copilot_api.indexing import (
    DEFAULT_CHUNKING_VERSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_VERSION,
)
from ai_qa_copilot_api.indexing_job_claims import (
    ClaimedIndexingJob,
    IndexingJobClaimRejected,
    SqlAlchemyIndexingJobClaims,
)
from ai_qa_copilot_api.projects import Base, ProjectRecord, SqlAlchemyProjectRepository


NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)


@dataclass
class Harness:
    sessions: sessionmaker[Session]
    project_id: UUID
    document_version_id: UUID
    job_id: UUID

    def claims(self, now: datetime = NOW) -> SqlAlchemyIndexingJobClaims:
        return SqlAlchemyIndexingJobClaims(
            self.sessions,
            clock=lambda: now,
            document_version_id=self.document_version_id,
        )

    def row(self) -> IndexingJobRecord:
        with self.sessions() as session:
            row = session.get(IndexingJobRecord, self.job_id)
            assert row is not None
            return row


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param("postgres", marks=pytest.mark.postgres_integration),
    ]
)
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Harness]:
    postgres_url = os.environ.get("AI_QA_COPILOT_POSTGRES_INTEGRATION_DATABASE_URL")
    if request.param == "postgres" and not postgres_url:
        pytest.skip("Requires the isolated db-check PostgreSQL database")

    url = (
        postgres_url
        if request.param == "postgres"
        else f"sqlite+pysqlite:///{tmp_path / 'indexing-claims.db'}"
    )
    assert url is not None
    engine = create_engine(url)

    if request.param == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection: sqlite3.Connection, record: object) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)

    sessions = sessionmaker(engine, expire_on_commit=False)
    project = SqlAlchemyProjectRepository(sessions).create(
        name="Indexing claim test",
        description=None,
    )
    parser_id, document_id, version_id, job_id = (uuid4() for _ in range(4))

    try:
        with sessions.begin() as session:
            session.add(
                ParserVersionRecord(
                    id=parser_id,
                    parser_name="indexing-claim-test",
                    parser_version=str(parser_id),
                    normalization_version="v1",
                    created_at=NOW,
                )
            )
            session.add(
                DocumentRecord(
                    id=document_id,
                    project_id=project.id,
                    document_type="markdown",
                    display_name="requirements.md",
                    created_at=NOW,
                )
            )
            session.flush()
            session.add(
                DocumentVersionRecord(
                    id=version_id,
                    document_id=document_id,
                    parser_version_id=parser_id,
                    version_number=1,
                    content_sha256="a" * 64,
                    byte_size=1,
                    content_type="text/markdown",
                    created_at=NOW,
                )
            )
            session.flush()
            session.add(
                IndexingJobRecord(
                    id=job_id,
                    project_id=project.id,
                    document_version_id=version_id,
                    chunking_version=DEFAULT_CHUNKING_VERSION,
                    embedding_model=DEFAULT_EMBEDDING_MODEL,
                    embedding_version=DEFAULT_EMBEDDING_VERSION,
                    state="queued",
                    created_at=NOW,
                    claim_token=None,
                    claimed_at=None,
                    claim_expires_at=None,
                    completed_at=None,
                    failure_code=None,
                )
            )

        yield Harness(sessions, project.id, version_id, job_id)
    finally:
        with sessions.begin() as session:
            for table, condition in (
                (IndexingJobRecord, IndexingJobRecord.id == job_id),
                (DocumentVersionRecord, DocumentVersionRecord.id == version_id),
                (DocumentRecord, DocumentRecord.id == document_id),
                (ParserVersionRecord, ParserVersionRecord.id == parser_id),
                (ProjectRecord, ProjectRecord.id == project.id),
            ):
                session.execute(delete(table).where(condition))
        engine.dispose()


def test_claim_is_durable_and_never_includes_source_access(harness: Harness) -> None:
    claim = harness.claims().claim_next()

    assert claim is not None
    assert harness.row().state == "claimed"
    assert claim.claim_expires_at == NOW + timedelta(seconds=60)
    assert (claim.project_id, claim.document_version_id) == (
        harness.project_id,
        harness.document_version_id,
    )
    assert "quarantine_key" not in claim.__dataclass_fields__
    assert "raw" not in claim.__dataclass_fields__
    assert harness.claims().claim_next() is None


def test_two_concurrent_consumers_only_claim_one_job(harness: Harness) -> None:
    barrier = Barrier(2)

    def attempt() -> ClaimedIndexingJob | None:
        barrier.wait(timeout=10)
        return harness.claims().claim_next()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        claims = [future.result(timeout=20) for future in futures]

    assert sum(claim is not None for claim in claims) == 1


@pytest.mark.parametrize(
    "field",
    [
        "job_id",
        "project_id",
        "document_version_id",
        "chunking_version",
        "embedding_model",
        "embedding_version",
        "claim_token",
        "claimed_at",
        "claim_expires_at",
    ],
)
def test_altered_claim_cannot_complete(harness: Harness, field: str) -> None:
    claim = harness.claims().claim_next()
    assert claim is not None

    altered = {
        "job_id": replace(claim, job_id=uuid4()),
        "project_id": replace(claim, project_id=uuid4()),
        "document_version_id": replace(claim, document_version_id=uuid4()),
        "chunking_version": replace(claim, chunking_version="other-chunking"),
        "embedding_model": replace(claim, embedding_model="other-model"),
        "embedding_version": replace(claim, embedding_version="other-version"),
        "claim_token": replace(claim, claim_token=uuid4()),
        "claimed_at": replace(claim, claimed_at=NOW + timedelta(seconds=30)),
        "claim_expires_at": replace(
            claim,
            claim_expires_at=NOW + timedelta(seconds=30),
        ),
    }[field]

    with pytest.raises(IndexingJobClaimRejected):
        harness.claims().accept(altered)

    assert harness.row().state == "claimed"
    harness.claims().accept(claim)


@pytest.mark.parametrize("accepted", [True, False])
def test_terminal_jobs_cannot_be_replayed(harness: Harness, accepted: bool) -> None:
    claims = harness.claims()
    claim = claims.claim_next()
    assert claim is not None

    if accepted:
        claims.accept(claim)
    else:
        claims.fail(claim)

    row = harness.row()
    assert row.state == ("accepted" if accepted else "failed")
    assert row.failure_code == (None if accepted else "INDEXING_WORKER_FAILED")

    with pytest.raises(IndexingJobClaimRejected):
        claims.fail(claim)
    assert claims.claim_next() is None


def test_expired_claim_fails_without_retry_and_late_completion_is_rejected(
    harness: Harness,
) -> None:
    claim = harness.claims().claim_next()
    assert claim is not None

    claims = harness.claims(claim.claim_expires_at)
    with pytest.raises(IndexingJobClaimRejected):
        claims.accept(claim)

    assert claims.expire_claims() == 1
    assert claims.expire_claims() == 0
    assert harness.row().failure_code == "INDEXING_CLAIM_EXPIRED"
    assert claims.claim_next() is None

    with pytest.raises(IndexingJobClaimRejected):
        claims.fail(claim)


def test_database_rejects_claim_state_without_claim_provenance(
    harness: Harness,
) -> None:
    with pytest.raises(IntegrityError), harness.sessions.begin() as session:
        session.execute(
            update(IndexingJobRecord)
            .where(IndexingJobRecord.id == harness.job_id)
            .values(state="claimed")
        )

    assert harness.row().state == "queued"


def test_naive_clock_fails_before_claiming(harness: Harness) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        harness.claims(NOW.replace(tzinfo=None)).claim_next()

    assert harness.row().state == "queued"


def test_scoped_consumer_cannot_claim_or_complete_another_version(
    harness: Harness,
) -> None:
    other = SqlAlchemyIndexingJobClaims(
        harness.sessions,
        clock=lambda: NOW,
        document_version_id=uuid4(),
    )
    assert other.claim_next() is None

    claim = harness.claims().claim_next()
    assert claim is not None

    with pytest.raises(IndexingJobClaimRejected):
        other.fail(claim)
    assert harness.row().state == "claimed"


def test_configuration_scope_leaves_nonmatching_job_queued(harness: Harness) -> None:
    claims = SqlAlchemyIndexingJobClaims(
        harness.sessions,
        clock=lambda: NOW,
        chunking_version="other-chunking",
    )

    assert claims.claim_next() is None
    assert harness.row().state == "queued"

    with pytest.raises(ValueError, match="non-empty"):
        SqlAlchemyIndexingJobClaims(harness.sessions, chunking_version=" ")
