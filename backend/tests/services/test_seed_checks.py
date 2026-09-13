"""
Tests for the post-seed checks.

WHY THIS EXISTS
    A check that cannot fail is worse than no check, because it is trusted.
    Every test here builds a database that is deliberately broken in one
    specific way and asserts the corresponding check notices — and then
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

from app.models import Line, Segment, Station, StationLine, TransportMode
from app.services import seed_checks

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is unset — these need a live Postgres with PostGIS",
)


async def build_line(db: AsyncSession, code: str) -> Line:
    line = Line(code=code, name=code.title(), mode=TransportMode.TUBE, colour="#000000")
    db.add(line)
    await db.flush()
    return line


async def build_station(db: AsyncSession, naptan: str) -> Station:
    station = Station(
        naptan_id=naptan, name=naptan, location="SRID=4326;POINT(-0.1 51.5)"
    )
    db.add(station)
    await db.flush()
    return station


async def connect(
    db: AsyncSession, line: Line, origin: Station, destination: Station
) -> None:
    """Join two stations in both directions, as the real seed does."""
    db.add_all(
        [
            Segment(
                line_id=line.id,
                origin_station_id=origin.id,
                destination_station_id=destination.id,
                seconds=120,
            ),
            Segment(
                line_id=line.id,
                origin_station_id=destination.id,
                destination_station_id=origin.id,
                seconds=120,
            ),
        ]
    )
    await db.flush()


async def result_for(db: AsyncSession, name: str) -> seed_checks.CheckResult:
    results = await seed_checks.run_all(db)
    return next(result for result in results if result.name == name)


# --- connectivity ------------------------------------------------------------


async def test_a_split_network_fails_the_connectivity_check(db: AsyncSession) -> None:
    # Two pairs of stations with no track between them: the 2021 situation in
    # miniature, where the Epping and West Ruislip branches sat disconnected
    # from the rest of the Central line.
    line = await build_line(db, "central")
    a, b, c, d = [await build_station(db, n) for n in ("A", "B", "C", "D")]
    for station in (a, b, c, d):
        db.add(StationLine(station_id=station.id, line_id=line.id))
    await connect(db, line, a, b)
    await connect(db, line, c, d)
    await db.flush()

    check = await result_for(db, "the graph is one connected piece")

    assert check.passed is False
    # The detail names the scale of the problem, so a regression is obvious
    # rather than merely failing.
    assert "2/4" in check.detail


async def test_a_joined_network_passes(db: AsyncSession) -> None:
    line = await build_line(db, "central")
    a, b, c = [await build_station(db, n) for n in ("A", "B", "C")]
    for station in (a, b, c):
        db.add(StationLine(station_id=station.id, line_id=line.id))
    await connect(db, line, a, b)
    await connect(db, line, b, c)
    await db.flush()

    check = await result_for(db, "the graph is one connected piece")

    assert check.passed is True
    assert "3/3" in check.detail


async def test_a_station_reachable_only_across_lines_still_counts(
    db: AsyncSession,
) -> None:
    # An interchange station holds the network together even though the two
    # lines never share a segment. Treating the graph as undirected and
    # line-agnostic is what makes that work.
    victoria = await build_line(db, "victoria")
    central = await build_line(db, "central")
    a, shared, c = [await build_station(db, n) for n in ("A", "SHARED", "C")]
    db.add_all(
        [
            StationLine(station_id=a.id, line_id=victoria.id),
            StationLine(station_id=shared.id, line_id=victoria.id),
            StationLine(station_id=shared.id, line_id=central.id),
            StationLine(station_id=c.id, line_id=central.id),
        ]
    )
    await connect(db, victoria, a, shared)
    await connect(db, central, shared, c)
    await db.flush()

    assert (await result_for(db, "the graph is one connected piece")).passed is True


# --- the other checks --------------------------------------------------------


async def test_a_line_with_no_track_is_caught(db: AsyncSession) -> None:
    # London Overground in the 2021 database: a row in `lines`, 85 stations,
    # and zero connections.
    line = await build_line(db, "victoria")
    ghost = await build_line(db, "overground-with-no-track")
    a, b = [await build_station(db, n) for n in ("A", "B")]
    db.add_all(
        [
            StationLine(station_id=a.id, line_id=line.id),
            StationLine(station_id=b.id, line_id=line.id),
        ]
    )
    await connect(db, line, a, b)
    await db.flush()

    check = await result_for(db, "every line has at least one segment")

    assert check.passed is False
    assert "1 lines with no track" in check.detail
    assert ghost.id is not None


async def test_a_station_serving_no_line_is_caught(db: AsyncSession) -> None:
    # 120 of the 486 rows in the 2021 stations table had no connections at
    # all — the entire Overground import.
    line = await build_line(db, "victoria")
    a, b = [await build_station(db, n) for n in ("A", "B")]
    await build_station(db, "ORPHAN")
    db.add_all(
        [
            StationLine(station_id=a.id, line_id=line.id),
            StationLine(station_id=b.id, line_id=line.id),
        ]
    )
    await connect(db, line, a, b)
    await db.flush()

    check = await result_for(db, "every station is on a line")

    assert check.passed is False
    assert "1 stations serve no line" in check.detail


async def test_an_empty_database_does_not_report_a_healthy_graph(
    db: AsyncSession,
) -> None:
    # The failure mode that matters most: a seed that wrote nothing must not
    # be able to claim everything is reachable, which is trivially true of
    # zero stations.
    check = await result_for(db, "the graph is one connected piece")

    assert check.passed is False
    assert "no stations" in check.detail
