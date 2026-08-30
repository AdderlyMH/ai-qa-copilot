"""Create quarantine-first document intake records.

Revision ID: 0005_create_document_intakes
Revises: 0004_create_document_provenance
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_create_document_intakes"
down_revision: str | None = "0004_create_document_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist private quarantine candidates and sanitized preflight rejections."""

    op.create_table(
        "document_intakes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("quarantine_key", sa.String(length=512), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("declared_content_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("rejection_code", sa.String(length=96), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(original_filename)) > 0",
            name="ck_document_intakes_filename_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(declared_content_type)) > 0",
            name="ck_document_intakes_content_type_not_blank",
        ),
        sa.CheckConstraint(
            "byte_size >= 0", name="ck_document_intakes_size_nonnegative"
        ),
        sa.CheckConstraint(
            "(state = 'quarantined' AND document_id IS NOT NULL "
            "AND document_version_id IS NOT NULL AND quarantine_key IS NOT NULL "
            "AND content_sha256 IS NOT NULL AND rejection_code IS NULL) OR "
            "(state = 'rejected' AND document_id IS NULL "
            "AND document_version_id IS NULL AND quarantine_key IS NULL "
            "AND content_sha256 IS NULL AND rejection_code IS NOT NULL)",
            name="ck_document_intakes_state_projection",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_document_intakes_project"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_document_intakes_document"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_document_intakes_document_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_intakes"),
        sa.UniqueConstraint("document_version_id", name="uq_document_intakes_version"),
        sa.UniqueConstraint(
            "quarantine_key", name="uq_document_intakes_quarantine_key"
        ),
    )
    op.create_index(
        "ix_document_intakes_project_state_created_at",
        "document_intakes",
        ["project_id", "state", "created_at"],
    )
    op.create_index(
        "ix_document_intakes_project_content_hash",
        "document_intakes",
        ["project_id", "content_sha256"],
    )


def downgrade() -> None:
    """Remove the intake projection before the underlying provenance tables."""

    op.drop_index(
        "ix_document_intakes_project_content_hash", table_name="document_intakes"
    )
    op.drop_index(
        "ix_document_intakes_project_state_created_at", table_name="document_intakes"
    )
    op.drop_table("document_intakes")
