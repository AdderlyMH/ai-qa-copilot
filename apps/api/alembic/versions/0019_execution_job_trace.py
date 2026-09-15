"""Persist safe workflow trace correlation for execution jobs."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0019_execution_job_trace"
down_revision: str | None = "0018_indexing_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_jobs",
        sa.Column("workflow_trace_id", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    used = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM execution_jobs WHERE workflow_trace_id IS NOT NULL"
        )
    )
    if used:
        raise RuntimeError(
            "Cannot downgrade execution jobs while workflow trace evidence exists"
        )
    op.drop_column("execution_jobs", "workflow_trace_id")
