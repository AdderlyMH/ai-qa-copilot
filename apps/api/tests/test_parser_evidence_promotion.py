from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    DocumentChunkRecord,
    DocumentIntakeRecord,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
    ParserJobRecord,
    ParserVersionRecord,
    SourceLocationRecord,
    IndexingJobRecord,
    DocumentChunkEmbeddingRecord,
    EmbeddingCacheRecord,
)
from ai_qa_copilot_api.ingestion import (
    DocumentIntake,
    DocumentIntakeUnavailable,
    InMemoryQuarantineStorage,
    SqlAlchemyDocumentIntakeRepository,
    UploadMetadata,
)
from ai_qa_copilot_api.markdown_parser import (
    DocumentParseRejected,
    MAX_TEXT_CODEPOINTS,
    NORMALIZATION_VERSION,
    PARSER_VERSION,
    ParsedRequirement,
    parse_markdown_or_text,
)
from ai_qa_copilot_api.parser_evidence_promotion import (
    ClaimedDocument,
    ParserEvidenceUnavailable,
    PromotedParserEvidence,
    SqlAlchemyClaimedDocumentReader,
    SqlAlchemyParserEvidencePromotion,
)
from ai_qa_copilot_api.parser_job_claims import (
    ClaimedParserJob,
    ParserJobClaimRejected,
    SqlAlchemyParserJobClaims,
)
from ai_qa_copilot_api.parser_queue import ParserJob, SqlAlchemyParserJobQueue
from ai_qa_copilot_api.projects import Base, ProjectRecord, SqlAlchemyProjectRepository
from ai_qa_copilot_api.parser_promotion_worker import (
    ParserPromotionRunState,
    create_markdown_text_promotion_worker,
)
from ai_qa_copilot_api.indexing import (
    FakeEmbeddingAdapter,
    DEFAULT_CHUNKING_VERSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_VERSION,
)
from ai_qa_copilot_api.indexing_worker import (
    IndexingRunState,
    create_indexing_worker,
)


NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
RAW = b"# Checkout\nREQ-001: Quantity must be positive.\nREQ-002: Return status 201.\n"


@dataclass
class Harness:
    sessions: sessionmaker[Session]
    storage: InMemoryQuarantineStorage
    intake: DocumentIntake
    claim: ClaimedParserJob

    def read(self) -> ClaimedDocument:
        return SqlAlchemyClaimedDocumentReader(
            self.sessions, self.storage, clock=lambda: NOW
        ).read(self.claim)

    def promote(self) -> PromotedParserEvidence:
        document = self.read()
        return SqlAlchemyParserEvidencePromotion(
            self.sessions, clock=lambda: NOW
        ).promote(
            self.claim,
            document=document,
            requirements=parse_markdown_or_text(
                document_type=document.document_type, raw=document.raw
            ),
        )

    def assert_unpublished(self) -> None:
        with self.sessions() as session:
            for record in (
                DocumentSectionRecord,
                SourceLocationRecord,
                IndexingJobRecord,
            ):
                assert (
                    session.scalar(
                        select(record.id).where(
                            record.document_version_id
                            == self.intake.document_version_id
                        )
                    )
                    is None
                )
            version = session.get(
                DocumentVersionRecord, self.intake.document_version_id
            )
            assert version is not None
            parser = session.get(ParserVersionRecord, version.parser_version_id)
            assert parser is not None
            assert parser.parser_name == "quarantine-pending"
            job = session.get(ParserJobRecord, self.claim.job_id)
            assert job is not None
            assert job.state == "claimed"
            assert job.completed_at is None


@pytest.fixture(
    params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres_integration)]
)
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Harness]:
    from hashlib import sha256

    postgres_url = os.environ.get("AI_QA_COPILOT_POSTGRES_INTEGRATION_DATABASE_URL")
    if request.param == "postgres" and not postgres_url:
        pytest.skip("Requires the isolated db-check PostgreSQL database")
    url = (
        postgres_url
        if request.param == "postgres"
        else f"sqlite:///{tmp_path / 'promotion.db'}"
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
        name="Parser promotion", description=None
    )
    storage = InMemoryQuarantineStorage()
    key = f"quarantine/{project.id}/{uuid4()}/raw"
    storage.put(key=key, content=BytesIO(RAW), content_type="text/markdown")
    intake = SqlAlchemyDocumentIntakeRepository(
        sessions, clock=lambda: NOW
    ).create_quarantined(
        project_id=project.id,
        metadata=UploadMetadata("requirements.md", "text/markdown", "identity"),
        document_type="markdown",
        byte_size=len(RAW),
        content_sha256=sha256(RAW).hexdigest(),
        quarantine_key=key,
    )
    SqlAlchemyParserJobQueue(sessions, clock=lambda: NOW).enqueue(
        ParserJob(document_intake_id=intake.id)
    )
    claim = SqlAlchemyParserJobClaims(
        sessions, clock=lambda: NOW, intake_id=intake.id
    ).claim_next()
    assert claim is not None
    try:
        yield Harness(sessions, storage, intake, claim)
    finally:
        # Clean only this fixture's records, never shared parser identities.
        with sessions.begin() as session:
            for table, condition in (
                (
                    DocumentChunkEmbeddingRecord,
                    DocumentChunkEmbeddingRecord.document_chunk_id.in_(
                        select(DocumentChunkRecord.id).where(
                            DocumentChunkRecord.document_version_id
                            == intake.document_version_id
                        )
                    ),
                ),
                (
                    DocumentChunkRecord,
                    DocumentChunkRecord.document_version_id
                    == intake.document_version_id,
                ),
                (
                    EmbeddingCacheRecord,
                    EmbeddingCacheRecord.project_id == project.id,
                ),
                (
                    IndexingJobRecord,
                    IndexingJobRecord.document_version_id == intake.document_version_id,
                ),
                (
                    DocumentSectionRecord,
                    DocumentSectionRecord.document_version_id
                    == intake.document_version_id,
                ),
                (
                    SourceLocationRecord,
                    SourceLocationRecord.document_version_id
                    == intake.document_version_id,
                ),
                (ParserJobRecord, ParserJobRecord.id == claim.job_id),
                (DocumentIntakeRecord, DocumentIntakeRecord.id == intake.id),
                (
                    DocumentVersionRecord,
                    DocumentVersionRecord.id == intake.document_version_id,
                ),
                (DocumentRecord, DocumentRecord.id == intake.document_id),
                (ProjectRecord, ProjectRecord.id == project.id),
            ):
                session.execute(delete(table).where(condition))
        engine.dispose()


def test_promotion_persists_exact_evidence_and_accepts_once(harness: Harness) -> None:
    document = harness.read()
    assert document.raw == RAW
    assert "Quantity" not in repr(document)
    assert not hasattr(document, "quarantine_key")
    expected = parse_markdown_or_text(document_type="markdown", raw=RAW)
    result = harness.promote()
    with harness.sessions() as session:
        job = session.get(ParserJobRecord, harness.claim.job_id)
        assert job is not None and job.state == "accepted"
        assert job.completed_at is not None and job.failure_code is None
        version = session.get(DocumentVersionRecord, result.document_version_id)
        assert (
            version is not None
            and version.parser_version_id == result.parser_version_id
        )
        indexing_job = session.get(IndexingJobRecord, result.indexing_job_id)
        assert indexing_job is not None
        assert (
            indexing_job.project_id,
            indexing_job.document_version_id,
            indexing_job.chunking_version,
            indexing_job.embedding_model,
            indexing_job.embedding_version,
            indexing_job.state,
        ) == (
            harness.intake.project_id,
            result.document_version_id,
            DEFAULT_CHUNKING_VERSION,
            DEFAULT_EMBEDDING_MODEL,
            DEFAULT_EMBEDDING_VERSION,
            "queued",
        )
        assert (
            indexing_job.claim_token,
            indexing_job.claimed_at,
            indexing_job.claim_expires_at,
            indexing_job.completed_at,
            indexing_job.failure_code,
        ) == (None, None, None, None, None)
        parser = session.get(ParserVersionRecord, result.parser_version_id)
        assert parser is not None
        assert (parser.parser_version, parser.normalization_version) == (
            PARSER_VERSION,
            NORMALIZATION_VERSION,
        )
        rows = session.execute(
            select(DocumentSectionRecord, SourceLocationRecord)
            .join(
                SourceLocationRecord,
                SourceLocationRecord.id == DocumentSectionRecord.source_location_id,
            )
            .where(
                DocumentSectionRecord.document_version_id == result.document_version_id
            )
            .order_by(DocumentSectionRecord.ordinal)
        ).all()
        assert tuple(row[0].id for row in rows) == result.section_ids
        assert len(rows) == len(expected)
        assert (
            session.scalar(
                select(DocumentChunkRecord.id).where(
                    DocumentChunkRecord.document_version_id
                    == result.document_version_id
                )
            )
            is None
        )
        intake = session.get(DocumentIntakeRecord, harness.intake.id)
        assert intake is not None and intake.state == "quarantined"
        for (section, location), item in zip(rows, expected, strict=True):
            assert section.normalized_text == item.normalized_text
            assert section.content_sha256 == item.content_sha256
            assert section.section_key == item.requirement_id
            assert location.document_version_id == result.document_version_id
            assert (location.line_start, location.line_end, location.heading) == (
                item.line_start,
                item.line_end,
                item.heading,
            )
            assert location.location_kind == "line_range"
    with pytest.raises(ParserJobClaimRejected):
        SqlAlchemyParserEvidencePromotion(harness.sessions, clock=lambda: NOW).promote(
            harness.claim, document=document, requirements=expected
        )
    with pytest.raises(ParserJobClaimRejected):
        harness.read()


def test_promoted_evidence_drives_real_indexing_worker_once(harness: Harness) -> None:
    requirements = parse_markdown_or_text(document_type="markdown", raw=RAW)
    adapter = FakeEmbeddingAdapter(
        {item.normalized_text: (float(item.ordinal + 1),) for item in requirements}
    )

    promotion = harness.promote()
    worker = create_indexing_worker(
        harness.sessions,
        adapter,
        runtime_verifier=lambda: None,
    )
    run = worker.run_once()

    assert run.state == IndexingRunState.ACCEPTED
    assert run.job_id == promotion.indexing_job_id
    assert run.document_version_id == promotion.document_version_id
    assert (
        run.chunk_count,
        run.chunks_created,
        run.embeddings_created,
        run.embedding_cache_hits,
    ) == (2, 2, 2, 0)
    assert adapter.requests == [tuple(item.normalized_text for item in requirements)]

    with harness.sessions() as session:
        job = session.get(IndexingJobRecord, promotion.indexing_job_id)
        assert job is not None
        assert job.state == "accepted"
        assert job.completed_at is not None
        assert job.failure_code is None

        chunks = tuple(
            session.scalars(
                select(DocumentChunkRecord)
                .where(
                    DocumentChunkRecord.document_version_id
                    == promotion.document_version_id
                )
                .order_by(DocumentChunkRecord.ordinal)
            )
        )
        assert [chunk.normalized_text for chunk in chunks] == [
            item.normalized_text for item in requirements
        ]

        attachment_count = session.scalar(
            select(func.count(DocumentChunkEmbeddingRecord.id))
            .join(
                DocumentChunkRecord,
                DocumentChunkRecord.id
                == DocumentChunkEmbeddingRecord.document_chunk_id,
            )
            .where(
                DocumentChunkRecord.document_version_id == promotion.document_version_id
            )
        )
        assert attachment_count == 2

    second = worker.run_once()
    assert second.state == IndexingRunState.IDLE
    assert adapter.requests == [tuple(item.normalized_text for item in requirements)]


@pytest.mark.parametrize(
    "field",
    ["job_id", "document_intake_id", "claim_token", "claimed_at", "claim_expires_at"],
)
def test_altered_claim_cannot_read_or_publish(harness: Harness, field: str) -> None:
    claims = {
        "job_id": replace(harness.claim, job_id=uuid4()),
        "document_intake_id": replace(harness.claim, document_intake_id=uuid4()),
        "claim_token": replace(harness.claim, claim_token=uuid4()),
        "claimed_at": replace(harness.claim, claimed_at=NOW + timedelta(seconds=1)),
        "claim_expires_at": replace(
            harness.claim, claim_expires_at=NOW + timedelta(seconds=30)
        ),
    }
    altered = claims[field]
    with pytest.raises(ParserJobClaimRejected):
        SqlAlchemyClaimedDocumentReader(
            harness.sessions, harness.storage, clock=lambda: NOW
        ).read(altered)
    with pytest.raises(ParserJobClaimRejected):
        SqlAlchemyParserEvidencePromotion(harness.sessions, clock=lambda: NOW).promote(
            altered,
            document=ClaimedDocument("markdown", RAW),
            requirements=parse_markdown_or_text(document_type="markdown", raw=RAW),
        )
    harness.assert_unpublished()


@pytest.mark.parametrize("mutation", ["digest", "size", "content_type", "missing"])
def test_reader_rejects_altered_or_missing_storage(
    harness: Harness, mutation: str
) -> None:
    key = harness.intake.quarantine_key
    assert key is not None
    if mutation == "missing":
        harness.storage.delete(key=key)
        error: type[Exception] = DocumentIntakeUnavailable
    else:
        error = DocumentParseRejected
        raw = RAW.replace(b"positive", b"negative") if mutation == "digest" else RAW
        if mutation == "size":
            raw += b"x"
        harness.storage.objects[key] = (
            raw,
            "text/plain" if mutation == "content_type" else "text/markdown",
        )
    with pytest.raises(error):
        harness.read()
    harness.assert_unpublished()


@pytest.mark.parametrize("during_read", [False, True])
def test_reader_rejects_expiry_before_or_during_io(
    harness: Harness, during_read: bool
) -> None:
    times = iter(
        [
            NOW if during_read else harness.claim.claim_expires_at,
            harness.claim.claim_expires_at,
        ]
    )
    with pytest.raises(ParserJobClaimRejected):
        SqlAlchemyClaimedDocumentReader(
            harness.sessions, harness.storage, clock=lambda: next(times)
        ).read(harness.claim)
    harness.assert_unpublished()


@pytest.mark.parametrize("during_write", [False, True])
def test_expired_promotion_rolls_back_everything(
    harness: Harness, during_write: bool
) -> None:
    times = iter(
        [
            NOW if during_write else harness.claim.claim_expires_at,
            harness.claim.claim_expires_at,
        ]
    )
    with pytest.raises(ParserJobClaimRejected):
        SqlAlchemyParserEvidencePromotion(
            harness.sessions, clock=lambda: next(times)
        ).promote(
            harness.claim,
            document=harness.read(),
            requirements=parse_markdown_or_text(document_type="markdown", raw=RAW),
        )
    harness.assert_unpublished()


def test_insert_failure_rolls_back_claim_parser_and_partial_evidence(
    harness: Harness,
) -> None:
    with harness.sessions() as session:
        parser_ids_before = set(session.scalars(select(ParserVersionRecord.id)))
    duplicate_id = uuid4()
    with pytest.raises(ParserEvidenceUnavailable):
        SqlAlchemyParserEvidencePromotion(
            harness.sessions, clock=lambda: NOW, id_factory=lambda: duplicate_id
        ).promote(
            harness.claim,
            document=harness.read(),
            requirements=parse_markdown_or_text(document_type="markdown", raw=RAW),
        )
    harness.assert_unpublished()
    with harness.sessions() as session:
        assert set(session.scalars(select(ParserVersionRecord.id))) == parser_ids_before


@pytest.mark.parametrize(
    "mutation", ["raw", "ordinal", "line", "text", "digest", "empty"]
)
def test_promotion_rejects_forged_input_or_output(
    harness: Harness, mutation: str
) -> None:
    document = harness.read()
    requirements = parse_markdown_or_text(document_type="markdown", raw=RAW)
    first = requirements[0]
    changed = {
        "ordinal": replace(first, ordinal=99),
        "line": replace(first, line_start=99, line_end=99),
        "text": replace(first, normalized_text="Invented evidence."),
        "digest": replace(first, content_sha256="0" * 64),
    }
    if mutation == "raw":
        document = replace(document, raw=RAW.replace(b"positive", b"negative"))
        requirements = parse_markdown_or_text(
            document_type="markdown", raw=document.raw
        )
    elif mutation == "empty":
        requirements = ()
    else:
        requirements = (changed[mutation], *requirements[1:])
    with pytest.raises(DocumentParseRejected):
        SqlAlchemyParserEvidencePromotion(harness.sessions, clock=lambda: NOW).promote(
            harness.claim, document=document, requirements=requirements
        )
    harness.assert_unpublished()


def test_promotion_rechecks_database_digest_after_read(harness: Harness) -> None:
    document = harness.read()
    with harness.sessions.begin() as session:
        session.execute(
            update(DocumentVersionRecord)
            .where(DocumentVersionRecord.id == harness.intake.document_version_id)
            .values(content_sha256="0" * 64)
        )
    with pytest.raises(DocumentParseRejected):
        SqlAlchemyParserEvidencePromotion(harness.sessions, clock=lambda: NOW).promote(
            harness.claim,
            document=document,
            requirements=parse_markdown_or_text(document_type="markdown", raw=RAW),
        )
    harness.assert_unpublished()


def test_concurrent_promotion_has_exactly_one_winner(harness: Harness) -> None:
    document = harness.read()
    requirements = parse_markdown_or_text(document_type="markdown", raw=RAW)
    barrier = Barrier(2)

    def attempt() -> bool:
        barrier.wait(timeout=10)
        try:
            SqlAlchemyParserEvidencePromotion(
                harness.sessions, clock=lambda: NOW
            ).promote(
                harness.claim,
                document=document,
                requirements=requirements,
            )
            return True
        except ParserJobClaimRejected:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sum(future.result(timeout=20) for future in futures) == 1
    with harness.sessions() as session:
        assert (
            len(
                tuple(
                    session.scalars(
                        select(DocumentSectionRecord.id).where(
                            DocumentSectionRecord.document_version_id
                            == harness.intake.document_version_id
                        )
                    )
                )
            )
            == 2
        )


@pytest.mark.parametrize("character", ["a", "é"])
def test_parser_codepoint_limit_is_inclusive(character: str) -> None:
    # Short lines isolate the codepoint limit from the independent per-line limit.
    text = (character * 999 + "\n") * (MAX_TEXT_CODEPOINTS // 1000)
    assert len(text) == MAX_TEXT_CODEPOINTS
    parsed: tuple[ParsedRequirement, ...] = parse_markdown_or_text(
        document_type="text", raw=text.encode()
    )
    assert len(parsed) == MAX_TEXT_CODEPOINTS // 1000
    with pytest.raises(DocumentParseRejected, match="PARSER_TEXT_CODEPOINT_LIMIT"):
        parse_markdown_or_text(document_type="text", raw=(text + character).encode())


def test_plain_text_uses_the_same_promotion_contract(harness: Harness) -> None:
    with harness.sessions.begin() as session:
        session.execute(
            update(DocumentRecord)
            .where(DocumentRecord.id == harness.intake.document_id)
            .values(document_type="text")
        )
        session.execute(
            update(DocumentVersionRecord)
            .where(DocumentVersionRecord.id == harness.intake.document_version_id)
            .values(content_type="text/plain")
        )
        session.execute(
            update(DocumentIntakeRecord)
            .where(DocumentIntakeRecord.id == harness.intake.id)
            .values(declared_content_type="text/plain")
        )
    key = harness.intake.quarantine_key
    assert key is not None
    harness.storage.objects[key] = (RAW, "text/plain")
    assert harness.read().document_type == "text"
    assert len(harness.promote().section_ids) == 2


def test_existing_parser_identity_is_reused(harness: Harness) -> None:
    with harness.sessions.begin() as session:
        parser_id = session.scalar(
            select(ParserVersionRecord.id).where(
                ParserVersionRecord.parser_name == "markdown-text",
                ParserVersionRecord.parser_version == PARSER_VERSION,
                ParserVersionRecord.normalization_version == NORMALIZATION_VERSION,
            )
        )
        if parser_id is None:
            parser_id = uuid4()
            session.add(
                ParserVersionRecord(
                    id=parser_id,
                    parser_name="markdown-text",
                    parser_version=PARSER_VERSION,
                    normalization_version=NORMALIZATION_VERSION,
                    created_at=NOW,
                )
            )
    assert harness.promote().parser_version_id == parser_id


def test_existing_locations_are_not_overwritten(harness: Harness) -> None:
    location_id = uuid4()
    with harness.sessions.begin() as session:
        session.add(
            SourceLocationRecord(
                id=location_id,
                document_version_id=harness.intake.document_version_id,
                location_kind="line_range",
                line_start=1,
                line_end=1,
            )
        )
    with pytest.raises(DocumentParseRejected, match="PARSER_EVIDENCE_ALREADY_EXISTS"):
        harness.promote()
    with harness.sessions() as session:
        assert session.get(SourceLocationRecord, location_id) is not None
        job = session.get(ParserJobRecord, harness.claim.job_id)
        assert job is not None and job.state == "claimed"
        assert (
            session.scalar(
                select(DocumentSectionRecord.id).where(
                    DocumentSectionRecord.document_version_id
                    == harness.intake.document_version_id
                )
            )
            is None
        )


def test_rejected_claim_cannot_publish_previously_read_bytes(harness: Harness) -> None:
    document = harness.read()
    SqlAlchemyParserJobClaims(harness.sessions, clock=lambda: NOW).reject(harness.claim)
    with pytest.raises(ParserJobClaimRejected):
        SqlAlchemyParserEvidencePromotion(harness.sessions, clock=lambda: NOW).promote(
            harness.claim,
            document=document,
            requirements=parse_markdown_or_text(document_type="markdown", raw=RAW),
        )
    with harness.sessions() as session:
        job = session.get(ParserJobRecord, harness.claim.job_id)
        assert job is not None and job.state == "rejected"
        assert (
            session.scalar(
                select(DocumentSectionRecord.id).where(
                    DocumentSectionRecord.document_version_id
                    == harness.intake.document_version_id
                )
            )
            is None
        )


def test_factory_wires_real_markdown_promotion_dependencies(
    harness: Harness,
) -> None:
    with harness.sessions.begin() as session:
        session.execute(
            update(ParserJobRecord)
            .where(ParserJobRecord.id == harness.claim.job_id)
            .values(
                state="queued",
                claim_token=None,
                claimed_at=None,
                claim_expires_at=None,
            )
        )

    worker = create_markdown_text_promotion_worker(
        harness.sessions,
        harness.storage,
        clock=lambda: NOW,
        runtime_verifier=lambda: None,
    )

    result = worker.run_once()

    assert result.state == ParserPromotionRunState.ACCEPTED
    assert result.job_id == harness.claim.job_id
    assert result.document_version_id == harness.intake.document_version_id
    assert result.section_count == 2
