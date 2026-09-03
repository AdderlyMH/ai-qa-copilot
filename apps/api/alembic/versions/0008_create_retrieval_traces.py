"""Create immutable hybrid-retrieval traces and candidate score records.

Revision ID: 0008_retrieval_traces
Revises: 0007_chunk_embedding_cache
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_retrieval_traces"
down_revision: str | None = "0007_chunk_embedding_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Persist bounded query inputs and all lexical/semantic fusion candidates."""

    op.create_table(
        "retrieval_traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_version", sa.String(length=64), nullable=False),
        sa.Column("fusion_method", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("query_embedding", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_version", sa.String(length=64), nullable=False),
        sa.Column("document_version_ids", sa.JSON(), nullable=True),
        sa.Column("document_types", sa.JSON(), nullable=True),
        sa.Column("chunking_version", sa.String(length=64), nullable=True),
        sa.Column("candidate_limit", sa.Integer(), nullable=False),
        sa.Column("result_limit", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(retrieval_version)) > 0",
            name="ck_retrieval_traces_version_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(fusion_method)) > 0",
            name="ck_retrieval_traces_fusion_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(query)) > 0", name="ck_retrieval_traces_query_not_blank"
        ),
        sa.CheckConstraint(
            "length(trim(embedding_model)) > 0",
            name="ck_retrieval_traces_model_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(embedding_version)) > 0",
            name="ck_retrieval_traces_embedding_version_not_blank",
        ),
        sa.CheckConstraint(
            "candidate_limit > 0", name="ck_retrieval_traces_candidates_positive"
        ),
        sa.CheckConstraint(
            "result_limit > 0", name="ck_retrieval_traces_results_positive"
        ),
        sa.CheckConstraint(
            "candidate_limit >= result_limit",
            name="ck_retrieval_traces_limits_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_retrieval_traces_project"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retrieval_traces"),
    )
    op.create_index(
        "ix_retrieval_traces_project_created",
        "retrieval_traces",
        ["project_id", "created_at"],
    )
    op.create_table(
        "retrieval_trace_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_trace_id", sa.Uuid(), nullable=False),
        sa.Column("document_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("lexical_score", sa.Float(), nullable=True),
        sa.Column("lexical_rank", sa.Integer(), nullable=True),
        sa.Column("semantic_distance", sa.Float(), nullable=True),
        sa.Column("semantic_rank", sa.Integer(), nullable=True),
        sa.Column("fusion_score", sa.Float(), nullable=False),
        sa.Column("final_rank", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "lexical_rank IS NULL OR lexical_rank > 0",
            name="ck_trace_candidates_lexical_rank_positive",
        ),
        sa.CheckConstraint(
            "semantic_rank IS NULL OR semantic_rank > 0",
            name="ck_trace_candidates_semantic_rank_positive",
        ),
        sa.CheckConstraint(
            "final_rank IS NULL OR final_rank > 0",
            name="ck_trace_candidates_final_rank_positive",
        ),
        sa.CheckConstraint(
            "(lexical_rank IS NULL AND lexical_score IS NULL) OR "
            "(lexical_rank IS NOT NULL AND lexical_score IS NOT NULL)",
            name="ck_trace_candidates_lexical_pair",
        ),
        sa.CheckConstraint(
            "(semantic_rank IS NULL AND semantic_distance IS NULL) OR "
            "(semantic_rank IS NOT NULL AND semantic_distance IS NOT NULL)",
            name="ck_trace_candidates_semantic_pair",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_trace_id"],
            ["retrieval_traces.id"],
            name="fk_trace_candidates_trace",
        ),
        sa.ForeignKeyConstraint(
            ["document_chunk_id"],
            ["document_chunks.id"],
            name="fk_trace_candidates_chunk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retrieval_trace_candidates"),
        sa.UniqueConstraint(
            "retrieval_trace_id",
            "document_chunk_id",
            name="uq_retrieval_trace_candidates_trace_chunk",
        ),
    )


def downgrade() -> None:
    """Remove RAG-003 trace state while leaving accepted embeddings untouched."""

    op.drop_table("retrieval_trace_candidates")
    op.drop_index("ix_retrieval_traces_project_created", table_name="retrieval_traces")
    op.drop_table("retrieval_traces")
