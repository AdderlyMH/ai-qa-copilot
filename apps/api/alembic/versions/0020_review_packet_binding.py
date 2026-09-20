"""Bind v1 reviewer-packet provenance without changing legacy labels."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0020_review_packet_binding"
down_revision: str | None = "0019_execution_job_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAPTURE_SCHEMA_VERSION = "evaluation-review-capture/v1"


def upgrade() -> None:
    """Add versioned packet bindings for newly captured review evidence."""

    with op.batch_alter_table("evaluation_review_labels") as batch:
        batch.add_column(
            sa.Column(
                "review_capture_schema_version", sa.String(length=64), nullable=True
            )
        )
        batch.add_column(
            sa.Column("review_packet_sha256", sa.String(length=64), nullable=True)
        )
        batch.create_check_constraint(
            "ck_evaluation_review_labels_capture_schema_allowed",
            "review_capture_schema_version IS NULL OR "
            f"review_capture_schema_version = '{_CAPTURE_SCHEMA_VERSION}'",
        )
        batch.create_check_constraint(
            "ck_evaluation_review_labels_packet_sha256_length",
            "review_packet_sha256 IS NULL OR length(review_packet_sha256) = 64",
        )
        batch.create_check_constraint(
            "ck_evaluation_review_labels_capture_role_binding",
            "review_capture_schema_version IS NULL OR "
            "("
            "(role = 'primary' "
            "AND candidate_output_sha256 IS NOT NULL "
            "AND review_packet_sha256 IS NOT NULL) OR "
            "(role = 'independent' "
            "AND candidate_output_sha256 IS NULL "
            "AND review_packet_sha256 IS NOT NULL) OR "
            "(role = 'adjudicated' "
            "AND candidate_output_sha256 IS NULL "
            "AND review_packet_sha256 IS NULL)"
            ")",
        )


def downgrade() -> None:
    """Refuse to discard reviewer-packet evidence."""

    used = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM evaluation_review_labels "
            "WHERE review_capture_schema_version IS NOT NULL "
            "OR review_packet_sha256 IS NOT NULL"
        )
    )
    if used:
        raise RuntimeError(
            "Cannot downgrade review-packet binding while capture evidence exists"
        )

    with op.batch_alter_table("evaluation_review_labels") as batch:
        batch.drop_constraint(
            "ck_evaluation_review_labels_capture_role_binding",
            type_="check",
        )
        batch.drop_constraint(
            "ck_evaluation_review_labels_packet_sha256_length",
            type_="check",
        )
        batch.drop_constraint(
            "ck_evaluation_review_labels_capture_schema_allowed",
            type_="check",
        )
        batch.drop_column("review_packet_sha256")
        batch.drop_column("review_capture_schema_version")
