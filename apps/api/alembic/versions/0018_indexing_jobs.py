"""Create durable indexing jobs for accepted parser evidence."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0018_indexing_jobs"
down_revision: str | None = "0017_parser_job_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "indexing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunking_version", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_version", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.CheckConstraint("length(trim(chunking_version)) > 0"),
        sa.CheckConstraint("length(trim(embedding_model)) > 0"),
        sa.CheckConstraint("length(trim(embedding_version)) > 0"),
        sa.CheckConstraint(
            "(state = 'queued' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND claim_expires_at IS NULL AND completed_at IS NULL "
            "AND failure_code IS NULL) OR "
            "(state = 'claimed' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND claim_expires_at IS NOT NULL AND completed_at IS NULL "
            "AND failure_code IS NULL) OR "
            "(state = 'accepted' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND claim_expires_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(state = 'failed' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND claim_expires_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NOT NULL)",
            name="ck_indexing_jobs_lifecycle",
        ),
        sa.CheckConstraint(
            "claimed_at IS NULL OR "
            "(claimed_at >= created_at AND claim_expires_at > claimed_at "
            "AND (completed_at IS NULL OR completed_at >= claimed_at))",
            name="ck_indexing_jobs_timestamps",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN "
            "('INDEXING_WORKER_FAILED', 'INDEXING_CLAIM_EXPIRED')",
            name="ck_indexing_jobs_failure_code",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunking_version",
            "embedding_model",
            "embedding_version",
            name="uq_indexing_jobs_version_configuration",
        ),
    )
    op.create_index(
        "ix_indexing_jobs_worker_claim",
        "indexing_jobs",
        ["state", "created_at", "id"],
    )


def downgrade() -> None:
    used = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM indexing_jobs WHERE state <> 'queued'")
    )
    if used:
        raise RuntimeError(
            "Cannot downgrade indexing jobs while previously claimed jobs exist"
        )
    op.drop_index("ix_indexing_jobs_worker_claim", table_name="indexing_jobs")
    op.drop_table("indexing_jobs")
