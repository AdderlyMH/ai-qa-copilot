from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    DocumentChunkRecord,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
    ParserVersionRecord,
    SourceLocationRecord,
)
from ai_qa_copilot_api.projects import Base, ProjectRecord


TIMESTAMP = datetime(2026, 8, 29, tzinfo=timezone.utc)
CONTENT_SHA256 = "a" * 64


@pytest.fixture
def sessions(tmp_path: Path) -> Generator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'documents.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    engine.dispose()


def create_provenance_graph(sessions: sessionmaker[Session]) -> tuple[UUID, UUID]:
    project_id = UUID("00000000-0000-0000-0000-000000000101")
    parser_version_id = UUID("00000000-0000-0000-0000-000000000102")
    document_id = UUID("00000000-0000-0000-0000-000000000103")
    version_id = UUID("00000000-0000-0000-0000-000000000104")
    location_id = UUID("00000000-0000-0000-0000-000000000105")
    section_id = UUID("00000000-0000-0000-0000-000000000106")
    chunk_id = UUID("00000000-0000-0000-0000-000000000107")
    with sessions.begin() as session:
        session.add_all(
            [
                ProjectRecord(
                    id=project_id,
                    name="Ingestion provenance",
                    description=None,
                    created_at=TIMESTAMP,
                    archived_at=None,
                ),
                ParserVersionRecord(
                    id=parser_version_id,
                    parser_name="markdown",
                    parser_version="v1",
                    normalization_version="normalized-v1",
                    created_at=TIMESTAMP,
                ),
                DocumentRecord(
                    id=document_id,
                    project_id=project_id,
                    document_type="markdown",
                    display_name="checkout-requirements.md",
                    created_at=TIMESTAMP,
                ),
                DocumentVersionRecord(
                    id=version_id,
                    document_id=document_id,
                    parser_version_id=parser_version_id,
                    version_number=1,
                    content_sha256=CONTENT_SHA256,
                    byte_size=42,
                    content_type="text/markdown",
                    created_at=TIMESTAMP,
                ),
                SourceLocationRecord(
                    id=location_id,
                    document_version_id=version_id,
                    location_kind="line_range",
                    heading="Checkout validation",
                    line_start=12,
                    line_end=16,
                    page_start=None,
                    page_end=None,
                    json_pointer=None,
                ),
                DocumentSectionRecord(
                    id=section_id,
                    document_version_id=version_id,
                    source_location_id=location_id,
                    ordinal=0,
                    section_key="REQ-CHECKOUT-001",
                    normalized_text="Cart IDs must be present.",
                    content_sha256="b" * 64,
                ),
                DocumentChunkRecord(
                    id=chunk_id,
                    document_version_id=version_id,
                    document_section_id=section_id,
                    source_location_id=location_id,
                    ordinal=0,
                    normalized_text="Cart IDs must be present.",
                    content_sha256="b" * 64,
                    chunking_version="chunking-v1",
                ),
            ]
        )
    return project_id, chunk_id


def test_document_provenance_records_are_project_scoped_and_traceable(
    sessions: sessionmaker[Session],
) -> None:
    project_id, chunk_id = create_provenance_graph(sessions)
    statement = (
        select(DocumentChunkRecord)
        .join(
            DocumentVersionRecord,
            DocumentChunkRecord.document_version_id == DocumentVersionRecord.id,
        )
        .join(DocumentRecord, DocumentVersionRecord.document_id == DocumentRecord.id)
        .where(DocumentRecord.project_id == project_id)
    )

    with sessions() as session:
        chunk = session.scalar(statement)
        assert chunk is not None
        version = session.get(DocumentVersionRecord, chunk.document_version_id)
        location = session.get(SourceLocationRecord, chunk.source_location_id)

    assert chunk.id == chunk_id
    assert version is not None
    assert version.parser_version_id == UUID("00000000-0000-0000-0000-000000000102")
    assert version.content_sha256 == CONTENT_SHA256
    assert location is not None
    assert (location.heading, location.line_start, location.line_end) == (
        "Checkout validation",
        12,
        16,
    )


def test_document_versions_reject_duplicate_version_numbers(
    sessions: sessionmaker[Session],
) -> None:
    _, chunk_id = create_provenance_graph(sessions)
    duplicate_id = UUID("00000000-0000-0000-0000-000000000108")
    with sessions() as session:
        original = session.get(DocumentChunkRecord, chunk_id)
        assert original is not None
        version = session.get(DocumentVersionRecord, original.document_version_id)
        assert version is not None
        session.add(
            DocumentVersionRecord(
                id=duplicate_id,
                document_id=version.document_id,
                parser_version_id=version.parser_version_id,
                version_number=version.version_number,
                content_sha256="c" * 64,
                byte_size=1,
                content_type="text/markdown",
                created_at=TIMESTAMP,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_document_chunks_reject_duplicate_ordinals(
    sessions: sessionmaker[Session],
) -> None:
    _, chunk_id = create_provenance_graph(sessions)
    duplicate_id = UUID("00000000-0000-0000-0000-000000000110")
    with sessions() as session:
        original = session.get(DocumentChunkRecord, chunk_id)
        assert original is not None
        session.add(
            DocumentChunkRecord(
                id=duplicate_id,
                document_version_id=original.document_version_id,
                document_section_id=original.document_section_id,
                source_location_id=original.source_location_id,
                ordinal=original.ordinal,
                normalized_text="A duplicate chunk is not a new provenance unit.",
                content_sha256="c" * 64,
                chunking_version="chunking-v1",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_source_locations_reject_inverted_line_ranges(
    sessions: sessionmaker[Session],
) -> None:
    _, chunk_id = create_provenance_graph(sessions)
    invalid_id = UUID("00000000-0000-0000-0000-000000000109")
    with sessions() as session:
        chunk = session.get(DocumentChunkRecord, chunk_id)
        assert chunk is not None
        session.add(
            SourceLocationRecord(
                id=invalid_id,
                document_version_id=chunk.document_version_id,
                location_kind="line_range",
                heading=None,
                line_start=9,
                line_end=8,
                page_start=None,
                page_end=None,
                json_pointer=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
