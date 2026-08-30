"""Migration-owned provenance records for the ING-001 ingestion foundation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from ai_qa_copilot_api.projects import Base


class ParserVersionRecord(Base):
    """One immutable parser and normalization version available to ingestion."""

    __tablename__ = "parser_versions"
    __table_args__ = (
        CheckConstraint("length(trim(parser_name)) > 0"),
        CheckConstraint("length(trim(parser_version)) > 0"),
        CheckConstraint("length(trim(normalization_version)) > 0"),
        UniqueConstraint(
            "parser_name",
            "parser_version",
            "normalization_version",
            name="uq_parser_versions_identity",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    parser_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class DocumentRecord(Base):
    """A project-owned logical source; raw-object storage is intentionally later work."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("length(trim(document_type)) > 0"),
        CheckConstraint("length(trim(display_name)) > 0"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class DocumentVersionRecord(Base):
    """An immutable content version with parser provenance and a content digest."""

    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0"),
        CheckConstraint("byte_size >= 0"),
        CheckConstraint("length(content_sha256) = 64"),
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_number"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    parser_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parser_versions.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class SourceLocationRecord(Base):
    """A precise source coordinate belonging to exactly one document version."""

    __tablename__ = "source_locations"
    __table_args__ = (
        CheckConstraint("length(trim(location_kind)) > 0"),
        CheckConstraint("line_start IS NULL OR line_start > 0"),
        CheckConstraint("line_end IS NULL OR line_end > 0"),
        CheckConstraint(
            "line_start IS NULL OR line_end IS NULL OR line_end >= line_start"
        ),
        CheckConstraint("page_start IS NULL OR page_start > 0"),
        CheckConstraint("page_end IS NULL OR page_end > 0"),
        CheckConstraint(
            "page_start IS NULL OR page_end IS NULL OR page_end >= page_start"
        ),
        UniqueConstraint(
            "document_version_id",
            "id",
            name="uq_source_locations_version_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    document_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_versions.id"), nullable=False
    )
    location_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    json_pointer: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentSectionRecord(Base):
    """A normalized logical section with an auditable source coordinate."""

    __tablename__ = "document_sections"
    __table_args__ = (
        CheckConstraint("ordinal >= 0"),
        CheckConstraint("length(trim(normalized_text)) > 0"),
        CheckConstraint("length(content_sha256) = 64"),
        UniqueConstraint(
            "document_version_id", "ordinal", name="uq_document_sections_ordinal"
        ),
        UniqueConstraint(
            "document_version_id", "id", name="uq_document_sections_version_id"
        ),
        ForeignKeyConstraint(
            ["document_version_id", "source_location_id"],
            ["source_locations.document_version_id", "source_locations.id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    document_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_versions.id"), nullable=False
    )
    source_location_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    section_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class DocumentChunkRecord(Base):
    """A normalized retrieval unit; embeddings remain out of ING-001 scope."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint("ordinal >= 0"),
        CheckConstraint("length(trim(normalized_text)) > 0"),
        CheckConstraint("length(content_sha256) = 64"),
        CheckConstraint("length(trim(chunking_version)) > 0"),
        UniqueConstraint(
            "document_version_id", "ordinal", name="uq_document_chunks_ordinal"
        ),
        ForeignKeyConstraint(
            ["document_version_id", "document_section_id"],
            ["document_sections.document_version_id", "document_sections.id"],
        ),
        ForeignKeyConstraint(
            ["document_version_id", "source_location_id"],
            ["source_locations.document_version_id", "source_locations.id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    document_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_versions.id"), nullable=False
    )
    document_section_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    source_location_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(64), nullable=False)


class DocumentIntakeState(StrEnum):
    """Persisted outcome of bounded raw-document admission."""

    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class DocumentIntakeRecord(Base):
    """Private quarantine admission or sanitized preflight rejection record."""

    __tablename__ = "document_intakes"
    __table_args__ = (
        CheckConstraint("length(trim(original_filename)) > 0"),
        CheckConstraint("length(trim(declared_content_type)) > 0"),
        CheckConstraint("byte_size >= 0"),
        CheckConstraint(
            "(state = 'quarantined' AND document_id IS NOT NULL "
            "AND document_version_id IS NOT NULL AND quarantine_key IS NOT NULL "
            "AND content_sha256 IS NOT NULL AND rejection_code IS NULL) OR "
            "(state = 'rejected' AND document_id IS NULL "
            "AND document_version_id IS NULL AND quarantine_key IS NULL "
            "AND content_sha256 IS NULL AND rejection_code IS NOT NULL)"
        ),
        UniqueConstraint("document_version_id", name="uq_document_intakes_version"),
        UniqueConstraint("quarantine_key", name="uq_document_intakes_quarantine_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_versions.id"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    quarantine_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
