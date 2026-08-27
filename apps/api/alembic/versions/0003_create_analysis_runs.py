"""Create persisted synthetic analysis runs.

Revision ID: 0003_create_analysis_runs
Revises: 0002_create_projects
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_create_analysis_runs"
down_revision: str | None = "0002_create_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the small project-scoped run projection required by SKEL-005."""

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("synthetic_text", sa.Text(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("provider_response_id", sa.String(length=255), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("configuration_version", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("schema_name", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(synthetic_text)) > 0", name="ck_analysis_runs_text_not_blank"
        ),
        sa.CheckConstraint(
            "input_tokens >= 0", name="ck_analysis_runs_input_tokens_nonnegative"
        ),
        sa.CheckConstraint(
            "output_tokens >= 0", name="ck_analysis_runs_output_tokens_nonnegative"
        ),
        sa.CheckConstraint(
            "total_tokens >= 0", name="ck_analysis_runs_total_tokens_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_analysis_runs_project"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_runs"),
    )
    op.create_index(
        "ix_analysis_runs_project_created_at",
        "analysis_runs",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the SKEL-005 run projection and its index."""

    op.drop_index("ix_analysis_runs_project_created_at", table_name="analysis_runs")
    op.drop_table("analysis_runs")
