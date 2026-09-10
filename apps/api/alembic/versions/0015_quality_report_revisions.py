"""Create immutable canonical QA report revision storage.

Revision ID: 0015_quality_report_revisions
Revises: 0014_execution_results
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0015_quality_report_revisions"
down_revision: str | None = "0014_execution_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable report revision state without report-generation routes."""

    op.create_table(
        "quality_report_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("canonical_report_json", sa.Text(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(schema_version)) > 0",
            name="ck_quality_report_revisions_schema_version_present",
        ),
        sa.CheckConstraint(
            "length(trim(canonical_report_json)) > 0",
            name="ck_quality_report_revisions_report_json_present",
        ),
        sa.CheckConstraint(
            "length(trim(snapshot_json)) > 0",
            name="ck_quality_report_revisions_snapshot_json_present",
        ),
        sa.CheckConstraint(
            "length(report_sha256) = 64",
            name="ck_quality_report_revisions_report_sha256_length",
        ),
        sa.CheckConstraint(
            "length(snapshot_sha256) = 64",
            name="ck_quality_report_revisions_snapshot_sha256_length",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_quality_report_revisions_project",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quality_report_revisions"),
        sa.UniqueConstraint(
            "project_id",
            "snapshot_sha256",
            name="uq_quality_report_revisions_project_snapshot_sha256",
        ),
    )
    op.create_index(
        "ix_quality_report_revisions_project_created_at",
        "quality_report_revisions",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only REP-002 durable report revision state."""

    op.drop_index(
        "ix_quality_report_revisions_project_created_at",
        table_name="quality_report_revisions",
    )
    op.drop_table("quality_report_revisions")
