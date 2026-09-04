"""Create deterministic requirement-analysis runs and findings.

Revision ID: 0010_requirement_analysis
Revises: 0009_create_citations
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_requirement_analysis"
down_revision: str | None = "0009_create_citations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "requirement_analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("analyzer_version", sa.String(length=64), nullable=False),
        sa.Column("citation_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(analyzer_version)) > 0",
            name="ck_requirement_analysis_runs_analyzer_version_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_requirement_analysis_runs_project",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_requirement_analysis_runs"),
    )
    op.create_index(
        "ix_requirement_analysis_runs_project_created_at",
        "requirement_analysis_runs",
        ["project_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "requirement_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("unsupported", sa.Boolean(), nullable=False),
        sa.Column("unsupported_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(category)) > 0",
            name="ck_requirement_findings_category_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(severity)) > 0",
            name="ck_requirement_findings_severity_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(analysis)) > 0",
            name="ck_requirement_findings_analysis_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(recommendation)) > 0",
            name="ck_requirement_findings_recommendation_not_blank",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_requirement_findings_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_requirement_findings_project",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_analysis_run_id"],
            ["requirement_analysis_runs.id"],
            name="fk_requirement_findings_run",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_requirement_findings"),
    )
    op.create_index(
        "ix_requirement_findings_run_created_at",
        "requirement_findings",
        ["requirement_analysis_run_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_requirement_findings_run_created_at",
        table_name="requirement_findings",
    )
    op.drop_table("requirement_findings")
    op.drop_index(
        "ix_requirement_analysis_runs_project_created_at",
        table_name="requirement_analysis_runs",
    )
    op.drop_table("requirement_analysis_runs")
