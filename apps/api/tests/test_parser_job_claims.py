from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    DocumentIntakeRecord,
    DocumentRecord,
    DocumentVersionRecord,
    ParserJobRecord,
    ParserVersionRecord,
)
from ai_qa_copilot_api.parser_job_claims import (
    ClaimedParserJob,
    ParserJobClaimRejected,
    SqlAlchemyParserJobClaims,
)
from ai_qa_copilot_api.parser_queue import ParserJob, SqlAlchemyParserJobQueue
from ai_qa_copilot_api.projects import Base, ProjectRecord, SqlAlchemyProjectRepository


NOW = datetime(2026, 9, 13, 3, tzinfo=timezone.utc)


@dataclass
class Harness:
    sessions: sessionmaker[Session]
    job: ParserJob

    def claims(self, now: datetime = NOW) -> SqlAlchemyParserJobClaims:
        return SqlAlchemyParserJobClaims(
            self.sessions,
            clock=lambda: now,
            intake_id=self.job.document_intake_id,
        )

    def row(self) -> ParserJobRecord:
        with self.sessions() as session:
            return session.scalars(
                select(ParserJobRecord).where(
                    ParserJobRecord.document_intake_id == self.job.document_intake_id
                )
            ).one()


@pytest.fixture(
    params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres_integration)]
)
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Harness]:
    postgres_url = os.environ.get("AI_QA_COPILOT_POSTGRES_INTEGRATION_DATABASE_URL")
    if request.param == "postgres" and not postgres_url:
        pytest.skip("Requires the isolated db-check PostgreSQL database")
    url = (
        postgres_url
        if request.param == "postgres"
        else f"sqlite+pysqlite:///{tmp_path / 'claims.db'}"
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
        name="Parser claim test", description=None
    )
    parser_id, document_id, version_id, intake_id = (uuid4() for _ in range(4))
    try:
        with sessions.begin() as session:
            session.add(
                ParserVersionRecord(
                    id=parser_id,
                    parser_name="claim-test",
                    parser_version=str(parser_id),
                    normalization_version="pending",
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
                DocumentIntakeRecord(
                    id=intake_id,
                    project_id=project.id,
                    document_id=document_id,
                    document_version_id=version_id,
                    state="quarantined",
                    quarantine_key=f"quarantine/{project.id}/{intake_id}/raw",
                    original_filename="requirements.md",
                    declared_content_type="text/markdown",
                    byte_size=1,
                    content_sha256="a" * 64,
                    rejection_code=None,
                    created_at=NOW,
                )
            )
        job = ParserJob(document_intake_id=intake_id)
        SqlAlchemyParserJobQueue(sessions, clock=lambda: NOW).enqueue(job)
        yield Harness(sessions, job)
    finally:
        # Delete only this fixture's records, including in the shared db-check DB.
        with sessions.begin() as session:
            for table, key in (
                (ParserJobRecord, ParserJobRecord.document_intake_id == intake_id),
                (DocumentIntakeRecord, DocumentIntakeRecord.id == intake_id),
                (DocumentVersionRecord, DocumentVersionRecord.id == version_id),
                (DocumentRecord, DocumentRecord.id == document_id),
                (ParserVersionRecord, ParserVersionRecord.id == parser_id),
                (ProjectRecord, ProjectRecord.id == project.id),
            ):
                session.execute(delete(table).where(key))
        engine.dispose()


def test_claim_is_durable_and_duplicate_enqueue_cannot_reopen_it(
    harness: Harness,
) -> None:
    claim = harness.claims().claim_next()
    assert claim is not None
    row = harness.row()
    assert row.state == "claimed"
    assert row.claim_token == claim.claim_token
    assert claim.document_intake_id == harness.job.document_intake_id
    assert claim.claim_expires_at == NOW + timedelta(seconds=60)
    assert "quarantine_key" not in claim.__dataclass_fields__
    SqlAlchemyParserJobQueue(harness.sessions, clock=lambda: NOW).enqueue(harness.job)
    assert harness.claims().claim_next() is None


def test_two_concurrent_consumers_only_claim_one_job(harness: Harness) -> None:
    barrier = Barrier(2)

    def attempt() -> ClaimedParserJob | None:
        barrier.wait(timeout=10)
        return harness.claims().claim_next()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        claims = [future.result(timeout=20) for future in futures]
    assert sum(claim is not None for claim in claims) == 1


@pytest.mark.parametrize(
    "field",
    ["job_id", "document_intake_id", "claim_token", "claimed_at", "claim_expires_at"],
)
def test_altered_claim_cannot_complete(harness: Harness, field: str) -> None:
    claim = harness.claims().claim_next()
    assert claim is not None
    altered = {
        "job_id": replace(claim, job_id=uuid4()),
        "document_intake_id": replace(claim, document_intake_id=uuid4()),
        "claim_token": replace(claim, claim_token=uuid4()),
        "claimed_at": replace(claim, claimed_at=NOW + timedelta(seconds=30)),
        "claim_expires_at": replace(
            claim, claim_expires_at=NOW + timedelta(seconds=30)
        ),
    }[field]
    with pytest.raises(ParserJobClaimRejected):
        harness.claims().reject(altered)
    assert harness.row().state == "claimed"
    harness.claims().reject(claim)


@pytest.mark.parametrize("reject", [True, False])
def test_terminal_failures_cannot_be_replayed(harness: Harness, reject: bool) -> None:
    claims = harness.claims()
    claim = claims.claim_next()
    assert claim is not None
    if reject:
        claims.reject(claim)
    else:
        claims.fail(claim)
    row = harness.row()
    assert row.state == ("rejected" if reject else "failed")
    assert row.failure_code == (
        "PARSER_DOCUMENT_REJECTED" if reject else "PARSER_WORKER_FAILED"
    )
    with pytest.raises(ParserJobClaimRejected):
        claims.fail(claim)
    SqlAlchemyParserJobQueue(harness.sessions, clock=lambda: NOW).enqueue(harness.job)
    assert claims.claim_next() is None


def test_expired_claim_fails_without_retry_and_late_completion_is_rejected(
    harness: Harness,
) -> None:
    claim = harness.claims().claim_next()
    assert claim is not None
    claims = harness.claims(claim.claim_expires_at)
    with pytest.raises(ParserJobClaimRejected):
        claims.reject(claim)
    assert claims.expire_claims() == 1
    assert claims.expire_claims() == 0
    assert harness.row().failure_code == "PARSER_CLAIM_EXPIRED"
    assert claims.claim_next() is None
    with pytest.raises(ParserJobClaimRejected):
        claims.fail(claim)


def test_database_rejects_claim_state_without_claim_provenance(
    harness: Harness,
) -> None:
    with pytest.raises(IntegrityError), harness.sessions.begin() as session:
        session.execute(
            update(ParserJobRecord)
            .where(ParserJobRecord.document_intake_id == harness.job.document_intake_id)
            .values(state="claimed")
        )
    assert harness.row().state == "queued"


def test_naive_clock_fails_before_claiming(harness: Harness) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        harness.claims(NOW.replace(tzinfo=None)).claim_next()
    assert harness.row().state == "queued"


def test_scoped_consumer_cannot_claim_or_complete_another_intake(
    harness: Harness,
) -> None:
    other = SqlAlchemyParserJobClaims(
        harness.sessions, clock=lambda: NOW, intake_id=uuid4()
    )
    assert other.claim_next() is None
    claim = harness.claims().claim_next()
    assert claim is not None
    with pytest.raises(ParserJobClaimRejected):
        other.fail(claim)
    assert harness.row().state == "claimed"
