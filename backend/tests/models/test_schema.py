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
    These need a real Postgres with PostGIS - they assert what the database
    does, which cannot be faked with a stub. They skip when TEST_DATABASE_URL
    is unset so the rest of the suite still runs with nothing installed.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Interchange,
    Segment,
    Station,
    StationComplex,
    StationLine,
)
from tests.helpers import a_line, a_station

# Declared here rather than imported from conftest: tests/ is not a package,
# so `from .conftest import ...` would not resolve, and pytest's own import of
# conftest does not make its names importable.
pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is unset - these need a live Postgres with PostGIS",
)


async def test_migrations_apply_and_record_a_version(db: AsyncSession) -> None:
    """Migrations apply and record a version."""
    # The `db` fixture only exists once `alembic upgrade head` has succeeded,
    # so reaching this line is most of the assertion. The rest confirms
    # Alembic stamped the database rather than silently doing nothing.
    result = await db.execute(text("SELECT version_num FROM alembic_version"))

    assert result.scalar_one()


async def test_postgis_extension_is_installed(db: AsyncSession) -> None:
    """The PostGIS extension is installed."""
    result = await db.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'postgis'")
    )

    assert result.scalar_one_or_none() == "postgis"


async def test_a_geography_point_round_trips(db: AsyncSession) -> None:
    """A geography point round trips."""
    # Oxford Circus. Written as WGS84 lon/lat and read back as lon/lat, which
    # is the pair of conversions a station row will go through on every seed
    # and every query. 4326 is the SRID for WGS84 - the system GPS uses.
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


# --- Helpers -----------------------------------------------------------------
#
# Each constraint test needs a couple of valid parent rows before it can insert
# the invalid one. These build them, flushing rather than committing so the
# fixture's rollback still discards everything.


def point(lon: float, lat: float) -> str:
    """A WGS84 point in the form the geography column accepts."""
    return f"SRID=4326;POINT({lon} {lat})"


# --- lines -------------------------------------------------------------------


async def test_duplicate_line_code_is_rejected(db: AsyncSession) -> None:
    """A duplicate line code is rejected."""
    # The 2021 `lines` table had no unique constraint on anything but its
    # primary key, so two rows could claim to be the Victoria line.
    await a_line(db, code="victoria")

    with pytest.raises(IntegrityError):
        await a_line(db, code="victoria")


# --- stations ----------------------------------------------------------------


async def test_duplicate_naptan_id_is_rejected(db: AsyncSession) -> None:
    """A duplicate NaPTAN id is rejected."""
    # The audit found 83 duplicated station names across 198 rows because
    # nothing stopped them. NaPTAN is the identity now, and it is unique.
    await a_station(db, naptan_id="940GZZLUOXC")

    with pytest.raises(IntegrityError):
        await a_station(db, naptan_id="940GZZLUOXC", name="A different name")


async def test_station_without_a_location_is_rejected(db: AsyncSession) -> None:
    """A station without a location is rejected."""
    # The single largest gap in the 2021 data: no coordinates existed at all,
    # because the table meant to hold them was malformed and empty. A station
    # the map cannot draw is not a station this project can use.
    db.add(Station(naptan_id="940GZZLUVIC", name="Victoria", location=None))

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_station_can_belong_to_a_complex(db: AsyncSession) -> None:
    """A station can belong to a complex."""
    # Not a rejection test. Bank and Monument are one interchange under two
    # names, and this is the relationship that lets them be modelled as such.
    complex_ = StationComplex(name="Bank and Monument", tfl_hub_id="HUBBAN")
    db.add(complex_)
    await db.flush()

    bank = Station(
        naptan_id="940GZZLUBNK",
        name="Bank Underground Station",
        location=point(-0.088, 51.513),
        complex_id=complex_.id,
    )
    db.add(bank)
    await db.flush()

    assert bank.complex_id == complex_.id


async def test_duplicate_tfl_hub_id_is_rejected(db: AsyncSession) -> None:
    """A duplicate TfL hub id is rejected."""
    db.add(StationComplex(name="Bank and Monument", tfl_hub_id="HUBBAN"))
    await db.flush()

    db.add(StationComplex(name="Something else", tfl_hub_id="HUBBAN"))
    with pytest.raises(IntegrityError):
        await db.flush()


# --- segments ----------------------------------------------------------------


async def test_segment_pointing_at_a_missing_station_is_rejected(
    db: AsyncSession,
) -> None:
    """A segment pointing at a missing station is rejected."""
    # SQLite declared these foreign keys and did not enforce them, because the
    # application never set PRAGMA foreign_keys = ON. Postgres always does.
    line = await a_line(db)
    origin = await a_station(db, naptan_id="940GZZLUOXC")

    db.add(
        Segment(
            line_id=line.id,
            origin_station_id=origin.id,
            destination_station_id=999_999,
            seconds=120,
        )
    )

    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.parametrize("seconds", [0, -60])
async def test_segment_with_a_non_positive_duration_is_rejected(
    db: AsyncSession, seconds: int
) -> None:
    """A segment with a non-positive duration is rejected."""
    # The audit found 12 links stored as zero minutes - Embankment to Charing
    # Cross on both the Bakerloo and the Northern among them. A zero-weight
    # edge tells the router the journey is free, which is worse than a missing
    # edge because it produces a confident wrong answer.
    line = await a_line(db)
    origin = await a_station(db, naptan_id="940GZZLUEMB")
    destination = await a_station(db, naptan_id="940GZZLUCHX")

    db.add(
        Segment(
            line_id=line.id,
            origin_station_id=origin.id,
            destination_station_id=destination.id,
            seconds=seconds,
        )
    )

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_segment_from_a_station_to_itself_is_rejected(db: AsyncSession) -> None:
    """A segment from a station to itself is rejected."""
    line = await a_line(db)
    station = await a_station(db, naptan_id="940GZZLUOXC")

    db.add(
        Segment(
            line_id=line.id,
            origin_station_id=station.id,
            destination_station_id=station.id,
            seconds=120,
        )
    )

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_duplicate_segment_on_the_same_line_is_rejected(db: AsyncSession) -> None:
    """A duplicate segment on the same line is rejected."""
    line = await a_line(db)
    origin = await a_station(db, naptan_id="940GZZLUOXC")
    destination = await a_station(db, naptan_id="940GZZLUGPK")

    for _ in range(2):
        db.add(
            Segment(
                line_id=line.id,
                origin_station_id=origin.id,
                destination_station_id=destination.id,
                seconds=120,
            )
        )

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_the_same_link_on_two_lines_is_allowed(db: AsyncSession) -> None:
    """The same link on two lines is allowed."""
    # The mirror of the test above, and the reason the unique constraint
    # includes line_id. Shepherd's Bush Market to Wood Lane is a real link on
    # both the Circle and the Hammersmith & City - the audit found it twice,
    # once per line. Uniqueness on (origin, destination) alone would make the
    # real network unrepresentable.
    circle = await a_line(db, code="circle")
    hammersmith = await a_line(db, code="hammersmith-city")
    origin = await a_station(db, naptan_id="940GZZLUSBM")
    destination = await a_station(db, naptan_id="940GZZLUWLA")

    for line in (circle, hammersmith):
        db.add(
            Segment(
                line_id=line.id,
                origin_station_id=origin.id,
                destination_station_id=destination.id,
                seconds=60,
            )
        )
    await db.flush()

    count = await db.execute(text("SELECT count(*) FROM segments"))
    assert count.scalar_one() == 2


# --- station_lines -----------------------------------------------------------


async def test_duplicate_station_line_pair_is_rejected(db: AsyncSession) -> None:
    """A duplicate station and line pair is rejected."""
    # The composite primary key. A station serves a line once or not at all.
    line = await a_line(db)
    station = await a_station(db, naptan_id="940GZZLUOXC")

    db.add(StationLine(station_id=station.id, line_id=line.id))
    await db.flush()

    db.add(StationLine(station_id=station.id, line_id=line.id))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_station_can_serve_several_lines(db: AsyncSession) -> None:
    """A station can serve several lines."""
    # The case the 2021 schema could not express without duplicating the
    # station row. Oxford Circus is on three lines; here that is three rows in
    # a join table and one station.
    station = await a_station(db, naptan_id="940GZZLUOXC", name="Oxford Circus")
    for code in ("bakerloo", "central", "victoria"):
        line = await a_line(db, code=code)
        db.add(StationLine(station_id=station.id, line_id=line.id))
    await db.flush()

    result = await db.execute(
        text("SELECT count(*) FROM station_lines WHERE station_id = :sid"),
        {"sid": station.id},
    )
    assert result.scalar_one() == 3


async def test_step_free_defaults_to_false_on_a_raw_insert(db: AsyncSession) -> None:
    """Step-free defaults to false on a raw insert."""
    # The server default, not the ORM one. A seed script doing bulk inserts
    # bypasses the Python-side default entirely, and "absence of evidence is
    # not step-free" has to hold on that path too.
    line = await a_line(db)
    station = await a_station(db, naptan_id="940GZZLUOXC")

    await db.execute(
        text("INSERT INTO station_lines (station_id, line_id) VALUES (:s, :l)"),
        {"s": station.id, "l": line.id},
    )

    result = await db.execute(text("SELECT step_free_to_platform FROM station_lines"))
    assert result.scalar_one() is False


# --- interchanges ------------------------------------------------------------


async def test_duplicate_interchange_is_rejected(db: AsyncSession) -> None:
    """A duplicate interchange is rejected."""
    station = await a_station(db, naptan_id="940GZZLUBNK")
    northern = await a_line(db, code="northern")
    central = await a_line(db, code="central")

    for _ in range(2):
        db.add(
            Interchange(
                station_id=station.id,
                from_line_id=northern.id,
                to_line_id=central.id,
                seconds=180,
            )
        )

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_interchange_between_a_line_and_itself_is_rejected(
    db: AsyncSession,
) -> None:
    """An interchange between a line and itself is rejected."""
    station = await a_station(db, naptan_id="940GZZLUBNK")
    northern = await a_line(db, code="northern")

    db.add(
        Interchange(
            station_id=station.id,
            from_line_id=northern.id,
            to_line_id=northern.id,
            seconds=180,
        )
    )

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_interchange_with_a_non_positive_duration_is_rejected(
    db: AsyncSession,
) -> None:
    """An interchange with a non-positive duration is rejected."""
    station = await a_station(db, naptan_id="940GZZLUBNK")
    northern = await a_line(db, code="northern")
    central = await a_line(db, code="central")

    db.add(
        Interchange(
            station_id=station.id,
            from_line_id=northern.id,
            to_line_id=central.id,
            seconds=0,
        )
    )

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_interchange_is_directional(db: AsyncSession) -> None:
    """An interchange is directional."""
    # Northern to Central at Bank is not necessarily the same walk as Central
    # to Northern - different platforms, sometimes a different passage. Both
    # directions must be storable, with different costs.
    station = await a_station(db, naptan_id="940GZZLUBNK")
    northern = await a_line(db, code="northern")
    central = await a_line(db, code="central")

    db.add(
        Interchange(
            station_id=station.id,
            from_line_id=northern.id,
            to_line_id=central.id,
            seconds=240,
        )
    )
    db.add(
        Interchange(
            station_id=station.id,
            from_line_id=central.id,
            to_line_id=northern.id,
            seconds=200,
        )
    )
    await db.flush()

    result = await db.execute(text("SELECT count(*) FROM interchanges"))
    assert result.scalar_one() == 2


# --- enum --------------------------------------------------------------------


async def test_an_unknown_transport_mode_is_rejected(db: AsyncSession) -> None:
    """An unknown transport mode is rejected."""
    # The enum is a real Postgres type, so a typo is a database error rather
    # than a row nobody notices until routing behaves oddly.
    with pytest.raises(DBAPIError):
        await db.execute(
            text(
                "INSERT INTO lines (code, name, mode, colour) "
                "VALUES ('monorail', 'Monorail', 'monorail', '#000000')"
            )
        )
