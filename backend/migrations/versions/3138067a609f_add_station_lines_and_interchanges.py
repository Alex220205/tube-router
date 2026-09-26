"""add station lines and interchanges

Revision ID: 3138067a609f
Revises: 16840f36f5fa
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3138067a609f"
down_revision: str | Sequence[str] | None = "16840f36f5fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interchanges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("from_line_id", sa.Integer(), nullable=False),
        sa.Column("to_line_id", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column(
            "step_free",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_line_id <> to_line_id", name=op.f("ck_interchanges_lines_differ")
        ),
        sa.CheckConstraint(
            "seconds > 0", name=op.f("ck_interchanges_seconds_positive")
        ),
        sa.ForeignKeyConstraint(
            ["from_line_id"],
            ["lines.id"],
            name=op.f("fk_interchanges_from_line_id_lines"),
        ),
        sa.ForeignKeyConstraint(
            ["station_id"],
            ["stations.id"],
            name=op.f("fk_interchanges_station_id_stations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_line_id"], ["lines.id"], name=op.f("fk_interchanges_to_line_id_lines")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interchanges")),
        sa.UniqueConstraint(
            "station_id",
            "from_line_id",
            "to_line_id",
            name=op.f("uq_interchanges_station_id_from_line_id_to_line_id"),
        ),
    )
    op.create_index(
        "ix_interchanges_station_id", "interchanges", ["station_id"], unique=False
    )
    op.create_table(
        "station_lines",
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("line_id", sa.Integer(), nullable=False),
        sa.Column(
            "step_free_to_platform",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            ["lines.id"],
            name=op.f("fk_station_lines_line_id_lines"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["station_id"],
            ["stations.id"],
            name=op.f("fk_station_lines_station_id_stations"),
            ondelete="CASCADE",
        ),
        # Composite primary key: a station serves a line once or not at all, which
        # removes the need for a separate unique constraint.
        sa.PrimaryKeyConstraint("station_id", "line_id", name=op.f("pk_station_lines")),
    )


def downgrade() -> None:
    op.drop_table("station_lines")
    op.drop_index("ix_interchanges_station_id", table_name="interchanges")
    op.drop_table("interchanges")
