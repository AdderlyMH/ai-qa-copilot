"""Create durable, one-time execution approvals.

Revision ID: 0012_execution_approvals
Revises: 0011_finding_feedback
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0012_execution_approvals"
down_revision: str | None = "0011_finding_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable approvals with database-enforced replay protection."""

    op.create_table(
        "execution_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_snapshot", sa.Text(), nullable=False),
        sa.Column("approver_id", sa.String(length=512), nullable=False),
        sa.Column(
            "approver_authentication_source",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(plan_hash) = 64",
            name="ck_execution_approvals_plan_hash_length",
        ),
        sa.CheckConstraint(
            "length(trim(plan_snapshot)) > 0",
            name="ck_execution_approvals_plan_snapshot_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(approver_id)) > 0",
            name="ck_execution_approvals_approver_id_not_blank",
        ),
        sa.CheckConstraint(
            "approver_authentication_source IN ('cognito', 'local_bypass')",
            name="ck_execution_approvals_approver_source_allowed",
        ),
        sa.CheckConstraint(
            "expires_at > approved_at",
            name="ck_execution_approvals_expiry_after_approval",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= approved_at",
            name="ck_execution_approvals_consumed_after_approval",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_execution_approvals_project",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_approvals"),
        sa.UniqueConstraint(
            "project_id",
            "plan_id",
            name="uq_execution_approvals_project_plan_id",
        ),
        sa.UniqueConstraint(
            "project_id",
            "plan_hash",
            name="uq_execution_approvals_project_plan_hash",
        ),
    )
    op.create_index(
        "ix_execution_approvals_claim",
        "execution_approvals",
        ["project_id", "plan_id", "plan_hash", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only EXEC-004 durable approval state."""

    op.drop_index(
        "ix_execution_approvals_claim",
        table_name="execution_approvals",
    )
    op.drop_table("execution_approvals")
