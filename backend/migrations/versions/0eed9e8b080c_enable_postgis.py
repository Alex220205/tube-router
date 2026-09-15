"""enable postgis

Revision ID: 0eed9e8b080c
Revises:
Create Date: 2026-09-12

The first migration, and it creates no tables. It enables the PostGIS
extension, which every later migration depends on: stations.location is
geography(Point, 4326) and that type does not exist until this has run.

Why an extension rather than two float columns. Coordinates as floats make
"stations within 500 metres" a full table scan with haversine arithmetic in
Python. As geography they are an indexed spatial query, and the GiST index in
the next migration is what makes it one.

The 2021 database had no coordinates at all. docs/AUDIT.md records why: the
table meant to hold them was created with the commas missing, so SQLite
parsed it as a single column, raised no error, and left it empty for five
years.

Downgrade drops the extension. It will fail if anything still depends on it,
which is correct - a downgrade that silently discards spatial columns would
be worse than one that refuses.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0eed9e8b080c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS because the postgis/postgis image may already have enabled
    # it in the template database, and a migration that fails on a correctly
    # configured server is not much of a migration.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS postgis")
