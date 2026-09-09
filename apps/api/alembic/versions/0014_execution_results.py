"""Create durable redacted restricted-execution results.

Revision ID: 0014_execution_results
Revises: 0013_execution_jobs
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0014_execution_results"
down_revision: str | None = "0013_execution_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one immutable redacted result for each terminal execution job."""

    op.create_table(
        "execution_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_job_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("assertion_results", sa.JSON(), nullable=False),
        sa.Column("request_evidence", sa.JSON(), nullable=True),
        sa.Column("response_evidence", sa.JSON(), nullable=True),
        sa.Column("transport_send_count", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'failed', 'cancelled')",
            name="ck_execution_results_outcome_allowed",
        ),
        sa.CheckConstraint(
            "transport_send_count >= 0 AND transport_send_count <= 1",
            name="ck_execution_results_send_count_bounded",
        ),
        sa.CheckConstraint(
            "(outcome = 'succeeded' AND failure_code IS NULL) OR "
            "(outcome IN ('failed', 'cancelled') "
            "AND failure_code IS NOT NULL "
            "AND length(trim(failure_code)) > 0)",
            name="ck_execution_results_failure_code_matches_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["execution_job_id"],
            ["execution_jobs.id"],
            name="fk_execution_results_job",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_results"),
        sa.UniqueConstraint(
            "execution_job_id",
            name="uq_execution_results_job",
        ),
    )
    op.create_index(
        "ix_execution_results_recorded_at",
        "execution_results",
        ["recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only EXEC-005 durable execution-result state."""

    op.drop_index(
        "ix_execution_results_recorded_at",
        table_name="execution_results",
    )
    op.drop_table("execution_results")
