"""Create immutable finding-feedback events.

Revision ID: 0011_finding_feedback
Revises: 0010_requirement_analysis
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_finding_feedback"
down_revision: str | None = "0010_requirement_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create project-scoped, provenance-preserving feedback events."""

    op.create_table(
        "finding_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_finding_id", sa.Uuid(), nullable=False),
        sa.Column("citation_ids", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("annotation", sa.Text(), nullable=True),
        sa.Column("reviewer_id", sa.String(length=512), nullable=False),
        sa.Column(
            "reviewer_authentication_source",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('accept', 'reject', 'annotate')",
            name="ck_finding_feedback_action_allowed",
        ),
        sa.CheckConstraint(
            "(action = 'annotate' AND annotation IS NOT NULL "
            "AND length(trim(annotation)) > 0) OR "
            "(action IN ('accept', 'reject') AND annotation IS NULL)",
            name="ck_finding_feedback_annotation_state",
        ),
        sa.CheckConstraint(
            "length(trim(reviewer_id)) > 0",
            name="ck_finding_feedback_reviewer_id_not_blank",
        ),
        sa.CheckConstraint(
            "reviewer_authentication_source IN ('cognito', 'local_bypass')",
            name="ck_finding_feedback_reviewer_authentication_source_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_finding_feedback_project",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_analysis_run_id"],
            ["requirement_analysis_runs.id"],
            name="fk_finding_feedback_run",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_finding_id"],
            ["requirement_findings.id"],
            name="fk_finding_feedback_finding",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_finding_feedback"),
    )
    op.create_index(
        "ix_finding_feedback_project_run_finding_created_at",
        "finding_feedback",
        [
            "project_id",
            "requirement_analysis_run_id",
            "requirement_finding_id",
            "created_at",
        ],
        unique=False,
    )


def downgrade() -> None:
    """Remove only ANA-005 feedback state."""

    op.drop_index(
        "ix_finding_feedback_project_run_finding_created_at",
        table_name="finding_feedback",
    )
    op.drop_table("finding_feedback")
