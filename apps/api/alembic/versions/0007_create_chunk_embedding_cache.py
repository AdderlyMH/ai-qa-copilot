"""Create versioned, project-scoped embedding cache records.

Revision ID: 0007_create_chunk_embedding_cache
Revises: 0006_create_parser_jobs
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_create_chunk_embedding_cache"
down_revision: str | None = "0006_create_parser_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow multiple chunking versions and persist reusable embeddings."""

    op.drop_constraint("uq_document_chunks_ordinal", "document_chunks", type_="unique")
    op.create_unique_constraint(
        "uq_document_chunks_version_chunking_ordinal",
        "document_chunks",
        ["document_version_id", "chunking_version", "ordinal"],
    )
    op.create_table(
        "embedding_cache_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_version", sa.String(length=64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_embedding_cache_entries_sha256_length",
        ),
        sa.CheckConstraint(
            "length(trim(embedding_model)) > 0",
            name="ck_embedding_cache_entries_model_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(embedding_version)) > 0",
            name="ck_embedding_cache_entries_version_not_blank",
        ),
        sa.CheckConstraint(
            "dimensions > 0", name="ck_embedding_cache_entries_dimensions_positive"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_embedding_cache_entries_project"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_embedding_cache_entries"),
        sa.UniqueConstraint(
            "project_id",
            "content_sha256",
            "embedding_model",
            "embedding_version",
            name="uq_embedding_cache_identity",
        ),
    )
    op.create_index(
        "ix_embedding_cache_entries_project_content",
        "embedding_cache_entries",
        ["project_id", "content_sha256"],
    )
    op.create_table(
        "document_chunk_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_cache_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(embedding_model)) > 0",
            name="ck_document_chunk_embeddings_model_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(embedding_version)) > 0",
            name="ck_document_chunk_embeddings_version_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["document_chunk_id"],
            ["document_chunks.id"],
            name="fk_chunk_embeddings_chunk",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_cache_id"],
            ["embedding_cache_entries.id"],
            name="fk_chunk_embeddings_cache",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunk_embeddings"),
        sa.UniqueConstraint(
            "document_chunk_id",
            "embedding_model",
            "embedding_version",
            name="uq_document_chunk_embeddings_identity",
        ),
    )


def downgrade() -> None:
    """Remove all RAG-001 durable state and restore the prior chunk constraint."""

    op.drop_table("document_chunk_embeddings")
    op.drop_index(
        "ix_embedding_cache_entries_project_content",
        table_name="embedding_cache_entries",
    )
    op.drop_table("embedding_cache_entries")
    op.drop_constraint(
        "uq_document_chunks_version_chunking_ordinal",
        "document_chunks",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_document_chunks_ordinal",
        "document_chunks",
        ["document_version_id", "ordinal"],
    )
