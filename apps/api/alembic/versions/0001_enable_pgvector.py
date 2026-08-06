"""Enable the pgvector extension.

Revision ID: 0001_enable_pgvector
Revises:
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0001_enable_pgvector"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable pgvector without creating any domain tables."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Return the baseline database to its pre-SKEL-002 state."""

    op.execute("DROP EXTENSION IF EXISTS vector")
