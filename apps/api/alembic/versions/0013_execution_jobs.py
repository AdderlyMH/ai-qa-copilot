"""Create durable approved-execution job state.

Revision ID: 0013_execution_jobs
Revises: 0012_execution_approvals
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013_execution_jobs"
down_revision: str | None = "0012_execution_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create queue-owned execution state without enabling execution."""

    op.create_table(
        "execution_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("execution_approval_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(plan_hash) = 64",
            name="ck_execution_jobs_plan_hash_length",
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'cancelled', 'succeeded', 'failed')",
            name="ck_execution_jobs_state_allowed",
        ),
        sa.CheckConstraint(
            "(state = 'queued' AND started_at IS NULL AND finished_at IS NULL "
            "AND cancelled_at IS NULL) OR "
            "(state = 'running' AND started_at IS NOT NULL AND finished_at IS NULL "
            "AND cancelled_at IS NULL) OR "
            "(state IN ('succeeded', 'failed') AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL AND cancelled_at IS NULL) OR "
            "(state = 'cancelled' AND finished_at IS NULL "
            "AND cancelled_at IS NOT NULL)",
            name="ck_execution_jobs_lifecycle_timestamps",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_execution_jobs_project",
        ),
        sa.ForeignKeyConstraint(
            ["execution_approval_id"],
            ["execution_approvals.id"],
            name="fk_execution_jobs_approval",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_jobs"),
        sa.UniqueConstraint(
            "execution_approval_id",
            name="uq_execution_jobs_approval",
        ),
    )
    op.create_index(
        "ix_execution_jobs_worker_claim",
        "execution_jobs",
        ["state", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the EXEC-005 execution-job state."""

    op.drop_index(
        "ix_execution_jobs_worker_claim",
        table_name="execution_jobs",
    )
    op.drop_table("execution_jobs")
