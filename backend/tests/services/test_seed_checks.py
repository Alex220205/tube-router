"""
Tests for the post-seed checks.

WHY THIS EXISTS
    A check that cannot fail is worse than no check, because it is trusted.
    Every test here builds a database that is deliberately broken in one
    specific way and asserts the corresponding check notices - and then
    builds the fixed version and asserts it stops complaining.

    The connectivity check earns this most. It passed on the first real seed
    with 272/272 stations, and a check that has only ever returned PASS has
    not been shown to work. Run against the 2021 data it would report
    244/346; the test below manufactures that situation deliberately.

NO 2021 EQUIVALENT
    The old project verified nothing after writing, which is why its database
    was 70.5% connected for five years without anyone knowing.

CONSTRAINT
    Needs a real Postgres: these assert on queries, not on Python.
"""

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StationLine
from app.services import seed_checks
from tests.helpers import a_line, a_station, both_ways

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is unset - these need a live Postgres with PostGIS",
)


async def result_for(db: AsyncSession, name: str) -> seed_checks.CheckResult:
    """Run every check and return the one with this name."""
    results = await seed_checks.run_all(db)
    return next(result for result in results if result.name == name)


# --- connectivity ------------------------------------------------------------


async def test_a_split_network_fails_the_connectivity_check(db: AsyncSession) -> None:
    """A split network fails the connectivity check."""
    # Two pairs of stations with no track between them: the 2021 situation in
    # miniature, where the Epping and West Ruislip branches sat disconnected
    # from the rest of the Central line.
    line = await a_line(db, "central")
    a = await a_station(db, "A")
    b = await a_station(db, "B")
    c = await a_station(db, "C")
    d = await a_station(db, "D")
    for station in (a, b, c, d):
        db.add(StationLine(station_id=station.id, line_id=line.id))
    await both_ways(db, line, a, b)
    await both_ways(db, line, c, d)
    await db.flush()

    check = await result_for(db, "the graph is one connected piece")

    assert check.passed is False
    # The detail names the scale of the problem, so a regression is obvious
    # rather than merely failing.
    assert "2/4" in check.detail


async def test_a_joined_network_passes(db: AsyncSession) -> None:
    """A joined network passes."""
    line = await a_line(db, "central")
    a = await a_station(db, "A")
    b = await a_station(db, "B")
    c = await a_station(db, "C")
    for station in (a, b, c):
        db.add(StationLine(station_id=station.id, line_id=line.id))
    await both_ways(db, line, a, b)
    await both_ways(db, line, b, c)
    await db.flush()

    check = await result_for(db, "the graph is one connected piece")

    assert check.passed is True
    assert "3/3" in check.detail


async def test_a_station_reachable_only_across_lines_still_counts(
    db: AsyncSession,
) -> None:
    """A station reachable only across lines still counts."""
    # An interchange station holds the network together even though the two
    # lines never share a segment. Treating the graph as undirected and
    # line-agnostic is what makes that work.
    victoria = await a_line(db, "victoria")
    central = await a_line(db, "central")
    a = await a_station(db, "A")
    shared = await a_station(db, "SHARED")
    c = await a_station(db, "C")
    db.add_all(
        [
            StationLine(station_id=a.id, line_id=victoria.id),
            StationLine(station_id=shared.id, line_id=victoria.id),
            StationLine(station_id=shared.id, line_id=central.id),
            StationLine(station_id=c.id, line_id=central.id),
        ]
    )
    await both_ways(db, victoria, a, shared)
    await both_ways(db, central, shared, c)
    await db.flush()

    assert (await result_for(db, "the graph is one connected piece")).passed is True


# --- the other checks --------------------------------------------------------


async def test_a_line_with_no_track_is_caught(db: AsyncSession) -> None:
    """A line with no track is caught."""
    # London Overground in the 2021 database: a row in `lines`, 85 stations,
    # and zero connections.
    line = await a_line(db, "victoria")
    ghost = await a_line(db, "overground-with-no-track")
    a = await a_station(db, "A")
    b = await a_station(db, "B")
    db.add_all(
        [
            StationLine(station_id=a.id, line_id=line.id),
            StationLine(station_id=b.id, line_id=line.id),
        ]
    )
    await both_ways(db, line, a, b)
    await db.flush()

    check = await result_for(db, "every line has at least one segment")

    assert check.passed is False
    assert "1 lines with no track" in check.detail
    assert ghost.id is not None


async def test_a_station_serving_no_line_is_caught(db: AsyncSession) -> None:
    """A station serving no line is caught."""
    # 120 of the 486 rows in the 2021 stations table had no connections at
    # all - the entire Overground import.
    line = await a_line(db, "victoria")
    a = await a_station(db, "A")
    b = await a_station(db, "B")
    await a_station(db, "ORPHAN")
    db.add_all(
        [
            StationLine(station_id=a.id, line_id=line.id),
            StationLine(station_id=b.id, line_id=line.id),
        ]
    )
    await both_ways(db, line, a, b)
    await db.flush()

    check = await result_for(db, "every station is on a line")

    assert check.passed is False
    assert "1 stations serve no line" in check.detail


async def test_an_empty_database_does_not_report_a_healthy_graph(
    db: AsyncSession,
) -> None:
    """An empty database does not report a healthy graph."""
    # The failure mode that matters most: a seed that wrote nothing must not
    # be able to claim everything is reachable, which is trivially true of
    # zero stations.
    check = await result_for(db, "the graph is one connected piece")

    assert check.passed is False
    assert "no stations" in check.detail
