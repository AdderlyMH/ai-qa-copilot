"""Record the model provider on persisted analysis runs.

Revision ID: 0021_analysis_run_provider
Revises: 0020_review_packet_binding
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0021_analysis_run_provider"
down_revision: str | None = "0020_review_packet_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the provider; every pre-existing run was an OpenAI B1/v1 run."""

    with op.batch_alter_table("analysis_runs") as batch:
        batch.add_column(
            sa.Column(
                "provider",
                sa.String(length=32),
                nullable=False,
                server_default="openai",
            )
        )
        batch.create_check_constraint(
            "ck_analysis_runs_provider_allowed",
            "provider IN ('openai', 'anthropic')",
        )


def downgrade() -> None:
    """Refuse to discard provider provenance for non-OpenAI runs."""

    used = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM analysis_runs WHERE provider <> 'openai'")
    )
    if used:
        raise RuntimeError(
            "Cannot downgrade analysis-run provider while non-OpenAI runs exist"
        )

    with op.batch_alter_table("analysis_runs") as batch:
        batch.drop_constraint("ck_analysis_runs_provider_allowed", type_="check")
        batch.drop_column("provider")
