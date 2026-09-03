"""Create immutable project-scoped citations over selected retrieval candidates.

Revision ID: 0009_create_citations
Revises: 0008_retrieval_traces
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_create_citations"
down_revision: str | None = "0008_retrieval_traces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Persist only citations backed by an existing retrieval candidate."""

    op.create_table(
        "citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_trace_id", sa.Uuid(), nullable=False),
        sa.Column("document_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_location_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_citations_project"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_citations_document_version",
        ),
        sa.ForeignKeyConstraint(
            ["source_location_id"],
            ["source_locations.id"],
            name="fk_citations_source_location",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_trace_id", "document_chunk_id"],
            [
                "retrieval_trace_candidates.retrieval_trace_id",
                "retrieval_trace_candidates.document_chunk_id",
            ],
            name="fk_citations_trace_candidate",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_citations"),
        sa.UniqueConstraint(
            "retrieval_trace_id",
            "document_chunk_id",
            name="uq_citations_trace_chunk",
        ),
    )
    op.create_index("ix_citations_project_id", "citations", ["project_id", "id"])


def downgrade() -> None:
    """Remove RAG-004 citation state while preserving retrieval traces."""

    op.drop_index("ix_citations_project_id", table_name="citations")
    op.drop_table("citations")
