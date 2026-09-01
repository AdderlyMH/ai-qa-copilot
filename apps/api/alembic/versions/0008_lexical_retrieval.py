"""Add the PostgreSQL full-text index used by lexical retrieval.

Revision ID: 0008_lexical_retrieval
Revises: 0007_chunk_embedding_cache
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_lexical_retrieval"
down_revision: str | None = "0007_chunk_embedding_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the immutable PostgreSQL FTS index over normalized chunk text."""

    op.create_index(
        "ix_document_chunks_lexical_tsvector",
        "document_chunks",
        [sa.text("to_tsvector('simple', normalized_text)")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Remove the lexical retrieval index without changing accepted content."""

    op.drop_index(
        "ix_document_chunks_lexical_tsvector",
        table_name="document_chunks",
    )
