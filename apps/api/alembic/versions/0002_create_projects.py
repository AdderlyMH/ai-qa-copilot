"""Create durable project records.

Revision ID: 0002_create_projects
Revises: 0001_enable_pgvector
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_create_projects"
down_revision: str | None = "0001_enable_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the minimum project table required by SKEL-003."""

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_projects_name_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )
    op.create_index(
        "ix_projects_active_created_at",
        "projects",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the SKEL-003 project table and its index."""

    op.drop_index("ix_projects_active_created_at", table_name="projects")
    op.drop_table("projects")
