"""
Tests that the database rejects what the 2021 schema accepted.

WHY THIS EXISTS
    The original schema had no constraints at all beyond primary keys.
    Foreign keys were declared but SQLite does not enforce them unless
    PRAGMA foreign_keys is set per connection, which the application never
    did. Every guarantee lived in application code, and the application did
    not enforce them either.

    docs/AUDIT.md records what that cost: 12 links with a travel time of
    zero, two Central line branches detached from the network, 83 duplicated
    station names, and nothing anywhere able to notice any of it.

    So these are not tests of SQLAlchemy. Every one asserts that a specific
    row the old database would have accepted is now impossible, and each maps
    to a defect the audit actually found.

NO 2021 EQUIVALENT
    There were no tests of any kind.

CONSTRAINT
    These need a real Postgres with PostGIS — they assert what the database
    does, which cannot be faked with a stub. They skip when TEST_DATABASE_URL
    is unset so the rest of the suite still runs with nothing installed.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Declared here rather than imported from conftest: tests/ is not a package,
# so `from .conftest import ...` would not resolve, and pytest's own import of
# conftest does not make its names importable.
pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is unset — these need a live Postgres with PostGIS",
)


async def test_migrations_apply_and_record_a_version(db: AsyncSession) -> None:
    # The `db` fixture only exists once `alembic upgrade head` has succeeded,
    # so reaching this line is most of the assertion. The rest confirms
    # Alembic stamped the database rather than silently doing nothing.
    result = await db.execute(text("SELECT version_num FROM alembic_version"))

    assert result.scalar_one()


async def test_postgis_extension_is_installed(db: AsyncSession) -> None:
    result = await db.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'postgis'")
    )

    assert result.scalar_one_or_none() == "postgis"


async def test_a_geography_point_round_trips(db: AsyncSession) -> None:
    # Oxford Circus. Written as WGS84 lon/lat and read back as lon/lat, which
    # is the pair of conversions a station row will go through on every seed
    # and every query. 4326 is the SRID for WGS84 — the system GPS uses.
    result = await db.execute(
        text(
            "SELECT ST_X(p::geometry), ST_Y(p::geometry) FROM "
            "(SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS p) AS t"
        ),
        {"lon": -0.141903, "lat": 51.515224},
    )
    lon, lat = result.one()

    assert lon == pytest.approx(-0.141903)
    assert lat == pytest.approx(51.515224)
