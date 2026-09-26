"""Tests for the boundary between the database and the engine."""

import json
import os

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.models import (
    Interchange,
    Segment,
    Station,
    StationLine,
)
from app.services import graph_loader
from app.services.graph_loader import load_network
from tests.helpers import a_line, a_station, both_ways
from tube_engine import Route, RouteQuery, find_route

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="needs a real Postgres; set TEST_DATABASE_URL",
)


async def test_every_row_reaches_the_network(db: AsyncSession) -> None:
    """Every row reaches the network."""
    # Counted against the database rather than against a literal, so this keeps holding
    # as the seed grows. Silent partial loading is the failure this file exists for, and
    # a count is the cheapest way to see it.
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)
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
    """Identifiers are the ones that mean something outside."""
    # NaPTAN ids and TfL line codes, not the integer primary keys. Those are local to
    # this database, and a Route carrying them would need a second lookup before it
    # could be rendered or compared against anything.
    red = await a_line(db, "victoria")
    a = await a_station(db, "940GZZLUOXC", lon=-0.141, lat=51.515)
    b = await a_station(db, "940GZZLUGPK", lon=-0.142, lat=51.506)
    await both_ways(db, red, a, b, 120)

    network = await load_network(db)

    assert "940GZZLUOXC" in network
    assert network.lines_at("940GZZLUOXC") == frozenset({"victoria"})


async def test_coordinates_come_back_the_right_way_round(db: AsyncSession) -> None:
    """Coordinates come back the right way round."""
    # ST_X is longitude and ST_Y is latitude, which reads backwards to anyone thinking
    # "lat, lon". Swapping them puts London in the Indian Ocean and raises nothing, so
    # the values are asserted rather than their presence.
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1419, lat=51.5152)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)

    network = await load_network(db)
    oxford = network.station("A")

    assert oxford.lat == pytest.approx(51.5152)
    assert oxford.lon == pytest.approx(-0.1419)


async def test_step_free_platforms_are_loaded_per_station_and_line(
    db: AsyncSession,
) -> None:
    """Step-free platforms are loaded per station and line."""
    red = await a_line(db, "red")
    blue = await a_line(db, "blue")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)
    await both_ways(db, blue, a, b, 120)
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
    """An interchange becomes a priced change."""
    # Positive counterpart to the count test: the loaded graph must still be routable,
    # not merely the right size. A change costing its stored seconds is the thing the
    # whole (station, line) expansion exists for.
    red = await a_line(db, "red")
    blue = await a_line(db, "blue")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    c = await a_station(db, "C", lon=-0.3, lat=51.7)
    await both_ways(db, red, a, b, 60)
    await both_ways(db, blue, b, c, 60)
    db.add(
        Interchange(
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


# The seed asserts this against the database. This asserts it against the object the
# seed's work is turned into, which is the only place a loading bug could hide.
async def test_a_disconnected_station_is_visible_in_the_built_network(
    db: AsyncSession,
) -> None:
    """A station with no track loads as disconnected rather than vanishing."""
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    orphan = await a_station(db, "ORPHAN", lon=-0.3, lat=51.7)
    await both_ways(db, red, a, b, 120)
    db.add(
        StationLine(station_id=orphan.id, line_id=red.id, step_free_to_platform=False)
    )
    await db.flush()

    network = await load_network(db)

    # The station is present, so the engine says "disconnected" rather than denying a
    # station the database can see.
    assert "ORPHAN" in network
    assert network.edges_from("ORPHAN") == ()
    assert (
        find_route(network, RouteQuery(origin="A", destination="ORPHAN")).reason
        == "disconnected"
    )


async def test_the_loader_reads_and_never_writes(db: AsyncSession) -> None:
    """The loader reads and never writes."""
    # It takes a session, so it could write. Asserted because a loader that quietly
    # inserted or updated would corrupt the development database the first time someone
    # requested a route.
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)
    before = await db.scalar(select(func.count()).select_from(Station))

    await load_network(db)
    await load_network(db)

    assert await db.scalar(select(func.count()).select_from(Station)) == before
    assert not db.new and not db.dirty and not db.deleted


async def test_the_network_is_built_once_and_reused(db: AsyncSession) -> None:
    """The network is built once and reused."""
    # Asserted as identity, not equality: two equal graphs would still mean the work was
    # done twice.
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)

    first = await graph_loader.get_network(db)
    second = await graph_loader.get_network(db)

    assert first is second


async def test_forgetting_makes_the_next_request_rebuild(db: AsyncSession) -> None:
    """Forgetting makes the next request rebuild."""
    # Sharing one immutable graph is only safe if there is a way to replace it after a
    # reseed. Without this the service would serve the old network until someone
    # restarted the process.
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)

    first = await graph_loader.get_network(db)
    graph_loader.forget()
    second = await graph_loader.get_network(db)

    assert first is not second
    assert len(first) == len(second)


async def test_rows_survive_a_round_trip_through_json(db: AsyncSession) -> None:
    """Rows survive a round trip through JSON."""
    # read_rows output goes into Redis, so it has to be JSON-safe. A value that is not -
    # a Decimal from a numeric column, say - would make every write fail and the cache
    # would silently never work, showing up only as unexplained slowness.
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1419, lat=51.5152)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)
    db.add(StationLine(station_id=a.id, line_id=red.id, step_free_to_platform=True))
    await db.flush()

    rows = await graph_loader.read_rows(db)
    restored = graph_loader.network_from_rows(json.loads(json.dumps(rows)))

    direct = graph_loader.network_from_rows(rows)
    assert len(restored) == len(direct)
    assert restored.step_free_at("A", "red") is True
    assert restored.station("A").lat == pytest.approx(51.5152)


# A reseed changes the data under a running API, and the API has to notice without a
# restart.
async def test_a_bumped_generation_is_noticed_without_a_restart(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bumped generation is noticed without a restart."""
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)

    generation = 1
    monkeypatch.setattr(cache, "read_generation", lambda: _returns(generation))
    first = await graph_loader.get_network(db)
    assert (
        find_route(first, RouteQuery(origin="A", destination="B")).total_seconds == 120
    )

    # The data changes, exactly as a reseed would change it.
    await db.execute(update(Segment).values(seconds=9999))
    generation = 2
    # Past the check interval, so the next call actually asks.
    monkeypatch.setattr(graph_loader, "_checked_at", 0.0)

    second = await graph_loader.get_network(db)

    assert second is not first
    assert (
        find_route(second, RouteQuery(origin="A", destination="B")).total_seconds
        == 9999
    )


async def test_an_unchanged_generation_does_not_rebuild(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unchanged generation does not rebuild."""
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)

    monkeypatch.setattr(cache, "read_generation", lambda: _returns(7))
    first = await graph_loader.get_network(db)
    monkeypatch.setattr(graph_loader, "_checked_at", 0.0)

    assert await graph_loader.get_network(db) is first


async def test_an_unreachable_redis_keeps_the_graph_it_has(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable Redis keeps the graph it has."""
    # read_generation returns None when Redis cannot be reached, and None is not a
    # mismatch. Treating it as one would rebuild the whole graph on every request for as
    # long as Redis was down - a degraded dependency turned into an outage, which is
    # precisely what core/cache.py exists to prevent.
    red = await a_line(db, "red")
    a = await a_station(db, "A", lon=-0.1, lat=51.5)
    b = await a_station(db, "B", lon=-0.2, lat=51.6)
    await both_ways(db, red, a, b, 120)

    monkeypatch.setattr(cache, "read_generation", lambda: _returns(None))
    first = await graph_loader.get_network(db)
    monkeypatch.setattr(graph_loader, "_checked_at", 0.0)

    assert await graph_loader.get_network(db) is first


async def _returns(value: int | None) -> int | None:
    """An already-answered coroutine, for monkeypatching an async function."""
    return value
