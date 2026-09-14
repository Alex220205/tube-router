"""
Tests for the boundary between the database and the engine.

WHY THIS EXISTS
    graph_loader is the one module that touches both sides, so a mistake in it
    is invisible from either. The engine suite cannot catch it — it never sees
    a database — and the endpoint tests would only notice if the resulting
    route were wrong in a way a human recognised.

    The failure mode that matters is silent partial loading. Drop a table's
    worth of segments and you still get a Network, still get routes, and the
    routes are simply worse. That is precisely what the 2021 database did:
    docs/AUDIT.md found 29.5% of stations unreachable, and the application
    never reported it because nothing ever asked.

NO 2021 EQUIVALENT
    There was no boundary. Traversal.Create_graph opened its own cursor, so
    loading and routing were one function and neither could be tested apart
    from the other.

CONSTRAINT
    Needs a real Postgres. Skips when TEST_DATABASE_URL is unset, so the
    suite still runs on a laptop with nothing started; CI sets it explicitly.
"""

import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Interchange as InterchangeRow
from app.models import Line as LineRow
from app.models import Segment, Station, StationLine, TransportMode
from app.services.graph_loader import load_network
from tube_engine import Route, RouteQuery, find_route

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="needs a real Postgres; set TEST_DATABASE_URL",
)


async def build_line(db: AsyncSession, code: str) -> LineRow:
    line = LineRow(
        code=code, name=code.title(), mode=TransportMode.TUBE, colour="#000000"
    )
    db.add(line)
    await db.flush()
    return line


async def build_station(
    db: AsyncSession, naptan: str, lon: float, lat: float
) -> Station:
    station = Station(
        naptan_id=naptan,
        name=f"{naptan} Station",
        location=f"SRID=4326;POINT({lon} {lat})",
    )
    db.add(station)
    await db.flush()
    return station


async def connect(
    db: AsyncSession, line: LineRow, origin: Station, destination: Station, seconds: int
) -> None:
    db.add_all(
        [
            Segment(
                line_id=line.id,
                origin_station_id=origin.id,
                destination_station_id=destination.id,
                seconds=seconds,
            ),
            Segment(
                line_id=line.id,
                origin_station_id=destination.id,
                destination_station_id=origin.id,
                seconds=seconds,
            ),
        ]
    )
    await db.flush()


async def test_every_row_reaches_the_network(db: AsyncSession) -> None:
    # Counted against the database rather than against a literal, so this
    # keeps holding as the seed grows. Silent partial loading is the failure
    # this file exists for, and a count is the cheapest way to see it.
    red = await build_line(db, "red")
    a = await build_station(db, "A", -0.1, 51.5)
    b = await build_station(db, "B", -0.2, 51.6)
    await connect(db, red, a, b, 120)
    db.add_all(
        [
            StationLine(station_id=a.id, line_id=red.id, step_free_to_platform=True),
            StationLine(station_id=b.id, line_id=red.id, step_free_to_platform=False),
        ]
    )
    await db.flush()

    network = await load_network(db)

    stations = await db.scalar(select(func.count()).select_from(Station))
    segments = await db.scalar(select(func.count()).select_from(Segment))
    assert len(network) == stations
    assert sum(len(network.edges_from(s)) for s in ("A", "B")) == segments


async def test_identifiers_are_the_ones_that_mean_something_outside(
    db: AsyncSession,
) -> None:
    # NaPTAN ids and TfL line codes, not the integer primary keys. Those are
    # local to this database, and a Route carrying them would need a second
    # lookup before it could be rendered or compared against anything.
    red = await build_line(db, "victoria")
    a = await build_station(db, "940GZZLUOXC", -0.141, 51.515)
    b = await build_station(db, "940GZZLUGPK", -0.142, 51.506)
    await connect(db, red, a, b, 120)

    network = await load_network(db)

    assert "940GZZLUOXC" in network
    assert network.lines_at("940GZZLUOXC") == frozenset({"victoria"})


async def test_coordinates_come_back_the_right_way_round(db: AsyncSession) -> None:
    # ST_X is longitude and ST_Y is latitude, which reads backwards to anyone
    # thinking "lat, lon". Swapping them puts London in the Indian Ocean and
    # raises nothing, so the values are asserted rather than their presence.
    red = await build_line(db, "red")
    a = await build_station(db, "A", -0.1419, 51.5152)
    b = await build_station(db, "B", -0.2, 51.6)
    await connect(db, red, a, b, 120)

    network = await load_network(db)
    oxford = network.station("A")

    assert oxford.lat == pytest.approx(51.5152)
    assert oxford.lon == pytest.approx(-0.1419)


async def test_step_free_platforms_are_loaded_per_station_and_line(
    db: AsyncSession,
) -> None:
    # The grain that made Phase 6 rewrite the model. A station step-free on one
    # line and not another has to arrive as two different answers, or the
    # engine is back to flattening it and being wrong about one of them.
    red = await build_line(db, "red")
    blue = await build_line(db, "blue")
    a = await build_station(db, "A", -0.1, 51.5)
    b = await build_station(db, "B", -0.2, 51.6)
    await connect(db, red, a, b, 120)
    await connect(db, blue, a, b, 120)
    db.add_all(
        [
            StationLine(station_id=a.id, line_id=red.id, step_free_to_platform=True),
            StationLine(station_id=a.id, line_id=blue.id, step_free_to_platform=False),
        ]
    )
    await db.flush()

    network = await load_network(db)

    assert network.step_free_at("A", "red") is True
    assert network.step_free_at("A", "blue") is False
    assert network.step_free_lines_at("A") == frozenset({"red"})


async def test_an_interchange_becomes_a_priced_change(db: AsyncSession) -> None:
    # Positive counterpart to the count test: the loaded graph must still be
    # routable, not merely the right size. A change costing its stored seconds
    # is the thing the whole (station, line) expansion exists for.
    red = await build_line(db, "red")
    blue = await build_line(db, "blue")
    a = await build_station(db, "A", -0.1, 51.5)
    b = await build_station(db, "B", -0.2, 51.6)
    c = await build_station(db, "C", -0.3, 51.7)
    await connect(db, red, a, b, 60)
    await connect(db, blue, b, c, 60)
    db.add(
        InterchangeRow(
            station_id=b.id, from_line_id=red.id, to_line_id=blue.id, seconds=90
        )
    )
    await db.flush()

    network = await load_network(db)
    result = find_route(network, RouteQuery(origin="A", destination="C"))

    assert isinstance(result, Route)
    # 60 riding + 90 changing + 60 riding. A station-only graph answers 120.
    assert result.total_seconds == 210
    assert result.changes == 1


async def test_a_disconnected_station_is_visible_in_the_built_network(
    db: AsyncSession,
) -> None:
    """The check docs/AUDIT.md calls the most valuable, one layer up.

    The 2021 graph had 29.5% of its stations unreachable and the application
    never noticed, because nothing ever asked. A loader that dropped a table's
    worth of segments would produce exactly that: a Network of the right size,
    serving routes, quietly missing a third of the network.

    The seed asserts this against the database. This asserts it against the
    object the seed's work is turned into, which is the only place a loading
    bug could hide.
    """
    red = await build_line(db, "red")
    a = await build_station(db, "A", -0.1, 51.5)
    b = await build_station(db, "B", -0.2, 51.6)
    orphan = await build_station(db, "ORPHAN", -0.3, 51.7)
    await connect(db, red, a, b, 120)
    db.add(
        StationLine(station_id=orphan.id, line_id=red.id, step_free_to_platform=False)
    )
    await db.flush()

    network = await load_network(db)

    # The station is present, so the engine says "disconnected" rather than
    # denying a station the database can see.
    assert "ORPHAN" in network
    assert network.edges_from("ORPHAN") == ()
    assert (
        find_route(network, RouteQuery(origin="A", destination="ORPHAN")).reason
        == "disconnected"
    )


async def test_the_loader_reads_and_never_writes(db: AsyncSession) -> None:
    # It takes a session, so it could write. Asserted because a loader that
    # quietly inserted or updated would corrupt the development database the
    # first time someone requested a route.
    red = await build_line(db, "red")
    a = await build_station(db, "A", -0.1, 51.5)
    b = await build_station(db, "B", -0.2, 51.6)
    await connect(db, red, a, b, 120)
    before = await db.scalar(select(func.count()).select_from(Station))

    await load_network(db)
    await load_network(db)

    assert await db.scalar(select(func.count()).select_from(Station)) == before
    assert not db.new and not db.dirty and not db.deleted
