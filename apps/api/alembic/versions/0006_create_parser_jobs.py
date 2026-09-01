"""Create opaque parser-queue records.

Revision ID: 0006_create_parser_jobs
Revises: 0005_create_document_intakes
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_create_parser_jobs"
down_revision: str | None = "0005_create_document_intakes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist opaque IDs for the dedicated parser-worker consumer."""

    op.create_table(
        "parser_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_intake_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state = 'queued'", name="ck_parser_jobs_state_queued"),
        sa.ForeignKeyConstraint(
            ["document_intake_id"],
            ["document_intakes.id"],
            name="fk_parser_jobs_document_intake",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_parser_jobs"),
        sa.UniqueConstraint(
            "document_intake_id", name="uq_parser_jobs_document_intake"
        ),
    )


def downgrade() -> None:
    """Remove opaque jobs before their quarantined intake records."""

    op.drop_table("parser_jobs")
