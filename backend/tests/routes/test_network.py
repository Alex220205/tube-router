"""
Tests for GET /lines and GET /network.

WHY THIS EXISTS
    The network payload is the one Phase 8 draws from, so the risk is not
    whether it returns data but whether the pieces line up: a segment naming
    a station id the stations list does not contain is a map with a line
    going nowhere, and nothing about the response shape would reveal it.

NO 2021 EQUIVALENT
    No endpoints, no map, and no way to ask a question about the network as a
    whole - which is why nobody noticed it was 70.5% connected.

CONSTRAINT
    Needs a real Postgres with PostGIS.
"""

import os

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Line, Segment, Station, StationLine, TransportMode

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is unset - these need a live Postgres with PostGIS",
)


async def seed_tiny_network(db: AsyncSession) -> None:
    """Two stations joined both ways on one line."""
    line = Line(
        code="victoria", name="Victoria", mode=TransportMode.TUBE, colour="#0098D4"
    )
    db.add(line)
    await db.flush()

    a = Station(
        naptan_id="A",
        name="Alpha Underground Station",
        location="SRID=4326;POINT(-0.1 51.5)",
    )
    b = Station(
        naptan_id="B",
        name="Beta Underground Station",
        location="SRID=4326;POINT(-0.2 51.6)",
    )
    db.add_all([a, b])
    await db.flush()

    db.add_all(
        [
            StationLine(station_id=a.id, line_id=line.id),
            StationLine(station_id=b.id, line_id=line.id),
            Segment(
                line_id=line.id,
                origin_station_id=a.id,
                destination_station_id=b.id,
                seconds=120,
            ),
            Segment(
                line_id=line.id,
                origin_station_id=b.id,
                destination_station_id=a.id,
                seconds=180,
            ),
        ]
    )
    await db.flush()


async def test_lines_carry_the_colour_the_map_draws_with(
    api: AsyncClient, db: AsyncSession
) -> None:
    # colour is NOT NULL and has no TfL API source - it comes from a
    # hardcoded map in the seed. If that ever breaks, the map renders in
    # whatever the default is and looks merely wrong rather than broken.
    await seed_tiny_network(db)

    lines = (await api.get("/lines")).json()

    assert lines[0]["colour"] == "#0098D4"
    # The enum's value, not its name: "tube", not "TUBE".
    assert lines[0]["mode"] == "tube"


async def test_every_segment_names_a_station_the_payload_contains(
    api: AsyncClient, db: AsyncSession
) -> None:
    # The failure this guards is a line drawn to nowhere. Segments carry ids
    # rather than nested stations, so the client joins them - and a dangling
    # id produces a map that is silently missing track.
    await seed_tiny_network(db)

    network = (await api.get("/network")).json()
    station_ids = {station["id"] for station in network["stations"]}

    assert network["segments"], "fixture should produce segments"
    for segment in network["segments"]:
        assert segment["origin_station_id"] in station_ids
        assert segment["destination_station_id"] in station_ids


async def test_the_network_keeps_both_directions_with_their_own_times(
    api: AsyncClient, db: AsyncSession
) -> None:
    # Segments are directional and the two directions genuinely differ -
    # Waterloo & City is 180 seconds one way and 240 the other in the real
    # data. Collapsing them would average away real asymmetry.
    await seed_tiny_network(db)

    segments = (await api.get("/network")).json()["segments"]

    assert sorted(s["seconds"] for s in segments) == [120, 180]
