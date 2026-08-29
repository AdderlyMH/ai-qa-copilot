"""Create project-scoped document provenance records.

Revision ID: 0004_create_document_provenance
Revises: 0003_create_analysis_runs
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_create_document_provenance"
down_revision: str | None = "0003_create_analysis_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable document/version provenance and normalized-unit tables."""

    op.create_table(
        "parser_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parser_name", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(parser_name)) > 0", name="ck_parser_versions_name_not_blank"
        ),
        sa.CheckConstraint(
            "length(trim(parser_version)) > 0",
            name="ck_parser_versions_version_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(normalization_version)) > 0",
            name="ck_parser_versions_normalization_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_parser_versions"),
        sa.UniqueConstraint(
            "parser_name",
            "parser_version",
            "normalization_version",
            name="uq_parser_versions_identity",
        ),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(document_type)) > 0", name="ck_documents_type_not_blank"
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0", name="ck_documents_name_not_blank"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_documents_project"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index(
        "ix_documents_project_created_at", "documents", ["project_id", "created_at"]
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("parser_version_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version_number > 0", name="ck_document_versions_number_positive"
        ),
        sa.CheckConstraint(
            "byte_size >= 0", name="ck_document_versions_size_nonnegative"
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64", name="ck_document_versions_sha256_length"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_document_versions_document"
        ),
        sa.ForeignKeyConstraint(
            ["parser_version_id"],
            ["parser_versions.id"],
            name="fk_document_versions_parser_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_number"
        ),
    )
    op.create_index(
        "ix_document_versions_document_created_at",
        "document_versions",
        ["document_id", "created_at"],
    )
    op.create_table(
        "source_locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("location_kind", sa.String(length=32), nullable=False),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("json_pointer", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "length(trim(location_kind)) > 0",
            name="ck_source_locations_kind_not_blank",
        ),
        sa.CheckConstraint(
            "line_start IS NULL OR line_start > 0",
            name="ck_source_locations_line_start_positive",
        ),
        sa.CheckConstraint(
            "line_end IS NULL OR line_end > 0",
            name="ck_source_locations_line_end_positive",
        ),
        sa.CheckConstraint(
            "line_start IS NULL OR line_end IS NULL OR line_end >= line_start",
            name="ck_source_locations_line_range",
        ),
        sa.CheckConstraint(
            "page_start IS NULL OR page_start > 0",
            name="ck_source_locations_page_start_positive",
        ),
        sa.CheckConstraint(
            "page_end IS NULL OR page_end > 0",
            name="ck_source_locations_page_end_positive",
        ),
        sa.CheckConstraint(
            "page_start IS NULL OR page_end IS NULL OR page_end >= page_start",
            name="ck_source_locations_page_range",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_source_locations_document_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_locations"),
        sa.UniqueConstraint(
            "document_version_id", "id", name="uq_source_locations_version_id"
        ),
    )
    op.create_table(
        "document_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_location_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section_key", sa.String(length=255), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "ordinal >= 0", name="ck_document_sections_ordinal_nonnegative"
        ),
        sa.CheckConstraint(
            "length(trim(normalized_text)) > 0",
            name="ck_document_sections_text_not_blank",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64", name="ck_document_sections_sha256_length"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_document_sections_document_version",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "source_location_id"],
            ["source_locations.document_version_id", "source_locations.id"],
            name="fk_document_sections_source_location_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_sections"),
        sa.UniqueConstraint(
            "document_version_id", "ordinal", name="uq_document_sections_ordinal"
        ),
        sa.UniqueConstraint(
            "document_version_id", "id", name="uq_document_sections_version_id"
        ),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("document_section_id", sa.Uuid(), nullable=True),
        sa.Column("source_location_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("chunking_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "ordinal >= 0", name="ck_document_chunks_ordinal_nonnegative"
        ),
        sa.CheckConstraint(
            "length(trim(normalized_text)) > 0",
            name="ck_document_chunks_text_not_blank",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64", name="ck_document_chunks_sha256_length"
        ),
        sa.CheckConstraint(
            "length(trim(chunking_version)) > 0",
            name="ck_document_chunks_chunking_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_document_chunks_document_version",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "document_section_id"],
            ["document_sections.document_version_id", "document_sections.id"],
            name="fk_document_chunks_document_section_version",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "source_location_id"],
            ["source_locations.document_version_id", "source_locations.id"],
            name="fk_document_chunks_source_location_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "document_version_id", "ordinal", name="uq_document_chunks_ordinal"
        ),
    )
    op.create_index(
        "ix_document_chunks_version_ordinal",
        "document_chunks",
        ["document_version_id", "ordinal"],
    )


def downgrade() -> None:
    """Remove the ING-001 provenance schema in dependency-safe order."""

    op.drop_index("ix_document_chunks_version_ordinal", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_table("document_sections")
    op.drop_table("source_locations")
    op.drop_index(
        "ix_document_versions_document_created_at", table_name="document_versions"
    )
    op.drop_table("document_versions")
    op.drop_index("ix_documents_project_created_at", table_name="documents")
    op.drop_table("documents")
    op.drop_table("parser_versions")
