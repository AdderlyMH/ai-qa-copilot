"""Add parser claims without replaying previously claimed work on rollback."""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "0017_parser_job_claims"
down_revision: str | None = "0016_evaluation_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS = [
    [
        "(state = 'queued' AND claim_token IS NULL AND claimed_at IS NULL AND claim_expires_at IS NULL AND completed_at IS NULL AND failure_code IS NULL) OR (state = 'claimed' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL AND completed_at IS NULL AND failure_code IS NULL) OR (state = 'accepted' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) OR (state IN ('rejected', 'failed') AND claim_token IS NOT NULL AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NOT NULL)",
        "ck_parser_jobs_lifecycle",
    ],
    [
        "claimed_at IS NULL OR (claimed_at >= created_at AND claim_expires_at > claimed_at AND (completed_at IS NULL OR completed_at >= claimed_at))",
        "ck_parser_jobs_timestamps",
    ],
    [
        "failure_code IS NULL OR (state = 'rejected' AND failure_code = 'PARSER_DOCUMENT_REJECTED') OR (state = 'failed' AND failure_code IN ('PARSER_WORKER_FAILED', 'PARSER_CLAIM_EXPIRED'))",
        "ck_parser_jobs_failure_code",
    ],
]


def upgrade() -> None:
    with op.batch_alter_table("parser_jobs") as batch:
        batch.add_column(sa.Column("claim_token", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("failure_code", sa.String(96), nullable=True))
        batch.drop_constraint("ck_parser_jobs_state_queued", type_="check")
        for expression, name in _CHECKS:
            batch.create_check_constraint(name, expression)


def downgrade() -> None:
    # Reopening a consumed claim would permit parser replay after re-upgrade.
    used = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM parser_jobs WHERE state <> 'queued'")
    )
    if used:
        raise RuntimeError(
            "Cannot downgrade parser claims while previously claimed jobs exist"
        )
    with op.batch_alter_table("parser_jobs") as batch:
        for _, name in reversed(_CHECKS):
            batch.drop_constraint(name, type_="check")
        for name in (
            "failure_code",
            "completed_at",
            "claim_expires_at",
            "claimed_at",
            "claim_token",
        ):
            batch.drop_column(name)
        batch.create_check_constraint("ck_parser_jobs_state_queued", "state = 'queued'")
