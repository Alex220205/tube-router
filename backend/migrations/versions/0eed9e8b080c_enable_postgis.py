"""enable postgis

Revision ID: 0eed9e8b080c
Revises:
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0eed9e8b080c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS because the postgis/postgis image may already have enabled it in the
    # template database, and a migration that fails on a correctly configured server is
    # not much of a migration.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS postgis")
