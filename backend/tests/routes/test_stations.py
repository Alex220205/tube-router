"""
Tests for the station endpoints.

WHY THIS EXISTS
    These are the first endpoints that read real data, so the risks are about
    the shape of an answer rather than whether a query runs: does an empty
    result look like success or like an error, does a bad id fail before
    touching the database, does the geography column come back as usable
    numbers.

NO 2021 EQUIVALENT
    There were no endpoints and no tests. The interface queried SQLite
    directly, so the only possible client was the desktop window.

CONSTRAINT
    Needs a real Postgres with PostGIS. Skips when TEST_DATABASE_URL is unset.
"""

import os

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Line, Station, StationLine, TransportMode

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is unset - these need a live Postgres with PostGIS",
)


async def seed_two_stations(db: AsyncSession) -> dict[str, int]:
    """A miniature network: two stations, one line, one of them step-free."""
    line = Line(
        code="victoria", name="Victoria", mode=TransportMode.TUBE, colour="#0098D4"
    )
    db.add(line)
    await db.flush()

    oxford = Station(
        naptan_id="940GZZLUOXC",
        name="Oxford Circus Underground Station",
        location="SRID=4326;POINT(-0.141903 51.515224)",
    )
    pimlico = Station(
        naptan_id="940GZZLUPCO",
        name="Pimlico Underground Station",
        location="SRID=4326;POINT(-0.133761 51.489097)",
    )
    db.add_all([oxford, pimlico])
    await db.flush()

    db.add_all(
        [
            StationLine(
                station_id=oxford.id, line_id=line.id, step_free_to_platform=True
            ),
            StationLine(
                station_id=pimlico.id, line_id=line.id, step_free_to_platform=False
            ),
        ]
    )
    await db.flush()
    return {"oxford": oxford.id, "pimlico": pimlico.id}


async def test_search_matches_a_substring_not_just_a_prefix(
    api: AsyncClient, db: AsyncSession
) -> None:
    # Names are stored verbatim, suffix included, so "Oxford Circus
    # Underground Station" has to be findable by typing a word from the
    # middle. A prefix match would find nothing for "circus".
    await seed_two_stations(db)

    response = await api.get("/stations", params={"q": "circus"})

    assert response.status_code == 200
    assert [s["name"] for s in response.json()] == ["Oxford Circus Underground Station"]


async def test_search_returns_coordinates_the_right_way_round(
    api: AsyncClient, db: AsyncSession
) -> None:
    # ST_X is longitude and ST_Y is latitude, which reads backwards to anyone
    # thinking in "lat, lon". Swapping them puts London in the Indian Ocean
    # and raises nothing at all.
    await seed_two_stations(db)

    station = (await api.get("/stations", params={"q": "oxford"})).json()[0]

    assert station["lat"] == pytest.approx(51.515224)
    assert station["lon"] == pytest.approx(-0.141903)


async def test_a_search_matching_nothing_is_an_empty_list_not_a_404(
    api: AsyncClient, db: AsyncSession
) -> None:
    # "No stations called zzz" is a successful answer to a reasonable
    # question. A 404 would make the frontend render an error for someone
    # halfway through typing.
    await seed_two_stations(db)

    response = await api.get("/stations", params={"q": "zzzzz"})

    assert response.status_code == 200
    assert response.json() == []


async def test_a_blank_query_returns_everything(
    api: AsyncClient, db: AsyncSession
) -> None:
    # The search box's first render is empty. Erroring there would be noise.
    await seed_two_stations(db)

    assert len((await api.get("/stations")).json()) == 2


async def test_a_station_carries_its_lines_and_accessibility(
    api: AsyncClient, db: AsyncSession
) -> None:
    ids = await seed_two_stations(db)

    station = (await api.get(f"/stations/{ids['oxford']}")).json()

    assert station["name"] == "Oxford Circus Underground Station"
    assert [line["code"] for line in station["lines"]] == ["victoria"]
    # Step-free is per (station, line), which is why it is nested here rather
    # than sitting on the station.
    assert station["lines"][0]["step_free_to_platform"] is True


async def test_an_unknown_station_is_a_404(api: AsyncClient, db: AsyncSession) -> None:
    await seed_two_stations(db)

    response = await api.get("/stations/999999")

    assert response.status_code == 404
    assert "999999" in response.json()["detail"]


@pytest.mark.parametrize("station_id", [0, -1])
async def test_a_non_positive_id_is_a_400_not_a_404(
    api: AsyncClient, db: AsyncSession, station_id: int
) -> None:
    # The request is malformed, not pointing at something absent, and a 404
    # would misdescribe it. It also fails before touching the database,
    # because no query can match a negative id.
    response = await api.get(f"/stations/{station_id}")

    assert response.status_code == 400
