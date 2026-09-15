"""
Tests for POST /route.

WHY THIS EXISTS
    The engine suite proves the search is correct. These prove the *answer*
    survives the trip to a client: that the right objective is selected, that
    names are resolved, and above all that the three ways a journey can fail
    are distinguishable from one another over HTTP.

    That last one is the whole point. In 2021 unreachability was the literal
    9999999, compared against inside the Tkinter window at lines 868 and 876.
    A caller that forgot the check rendered it as a journey time. Here the
    cases are a 400, a 404 and a 200-with-a-reason, and they mean three
    different things.

NO 2021 EQUIVALENT
    There was no endpoint and no wire format. The search wrote into its own
    attributes and the window read them back off the same object.

CONSTRAINT
    Needs a real Postgres: the endpoint builds a Network from it. Skips when
    TEST_DATABASE_URL is unset; CI sets it explicitly.
"""

import os

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Interchange, Line, Segment, Station, StationLine, TransportMode
from app.services import status_poller

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="needs a real Postgres; set TEST_DATABASE_URL",
)


async def seed_two_line_network(db: AsyncSession) -> None:
    """A network where the objectives genuinely disagree.

        A --30-- B --30-- C     on red then blue, changing at B costs 20
        A ------300------ C     on green, one hop, no change

        step-free: A and C on green only. B has nothing accessible.

    Fastest:        30 + 20 + 30 = 80 seconds, one change.
    Fewest changes: 300 seconds, none.
    Step-free:      300 seconds on green - the only accessible way.

    Worked out on paper, like every expected value in the engine suite.
    """
    red, blue, green = (
        Line(code=code, name=code.title(), mode=TransportMode.TUBE, colour="#000000")
        for code in ("red", "blue", "green")
    )
    db.add_all([red, blue, green])
    await db.flush()

    a, b, c, orphan = (
        Station(
            naptan_id=naptan,
            name=f"{naptan} Underground Station",
            location=f"SRID=4326;POINT({lon} 51.5)",
        )
        for naptan, lon in (("A", -0.1), ("B", -0.2), ("C", -0.3), ("ORPHAN", -0.4))
    )
    db.add_all([a, b, c, orphan])
    await db.flush()

    db.add_all(
        [
            Segment(
                line_id=red.id,
                origin_station_id=a.id,
                destination_station_id=b.id,
                seconds=30,
            ),
            Segment(
                line_id=red.id,
                origin_station_id=b.id,
                destination_station_id=a.id,
                seconds=30,
            ),
            Segment(
                line_id=blue.id,
                origin_station_id=b.id,
                destination_station_id=c.id,
                seconds=30,
            ),
            Segment(
                line_id=blue.id,
                origin_station_id=c.id,
                destination_station_id=b.id,
                seconds=30,
            ),
            Segment(
                line_id=green.id,
                origin_station_id=a.id,
                destination_station_id=c.id,
                seconds=300,
            ),
            Segment(
                line_id=green.id,
                origin_station_id=c.id,
                destination_station_id=a.id,
                seconds=300,
            ),
            Interchange(
                station_id=b.id, from_line_id=red.id, to_line_id=blue.id, seconds=20
            ),
            Interchange(
                station_id=b.id, from_line_id=blue.id, to_line_id=red.id, seconds=20
            ),
            StationLine(station_id=a.id, line_id=green.id, step_free_to_platform=True),
            StationLine(station_id=c.id, line_id=green.id, step_free_to_platform=True),
            StationLine(station_id=a.id, line_id=red.id, step_free_to_platform=False),
            StationLine(station_id=b.id, line_id=red.id, step_free_to_platform=False),
            StationLine(
                station_id=orphan.id, line_id=red.id, step_free_to_platform=False
            ),
        ]
    )
    await db.flush()


async def plan(api: AsyncClient, **body: object) -> dict:
    response = await api.post(
        "/route", json={"origin": "A", "destination": "C", **body}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_route_comes_back_with_named_stations(
    api: AsyncClient, db: AsyncSession
) -> None:
    # The engine speaks NaPTAN ids because it must not care what anything is
    # called. A client needs "Green Park", and resolving that is the route
    # module's job - so it is asserted here rather than assumed.
    await seed_two_line_network(db)

    body = await plan(api)

    assert body["found"] is True
    assert body["total_seconds"] == 80
    assert body["changes"] == 1
    assert body["legs"][0]["stations"][0] == {
        "id": "A",
        "name": "A Underground Station",
    }


async def test_the_three_objectives_return_genuinely_different_answers(
    api: AsyncClient, db: AsyncSession
) -> None:
    # The test that proves the objective is actually being passed through. If
    # the endpoint ignored it and always asked for the fastest, every other
    # test in this file would still pass.
    await seed_two_line_network(db)

    fastest = await plan(api, objective="fastest")
    fewest = await plan(api, objective="fewest_changes")
    step_free = await plan(api, objective="step_free")

    assert (fastest["total_seconds"], fastest["changes"]) == (80, 1)
    assert (fewest["total_seconds"], fewest["changes"]) == (300, 0)
    assert step_free["total_seconds"] == 300
    assert step_free["step_free"] is True
    # And the fastest route is honestly reported as not accessible.
    assert fastest["step_free"] is False


async def test_avoiding_a_line_changes_the_answer(
    api: AsyncClient, db: AsyncSession
) -> None:
    # The mechanism Phase 7 routes around suspended lines with.
    await seed_two_line_network(db)

    body = await plan(api, avoid_lines=["blue"])

    assert body["found"] is True
    assert body["total_seconds"] == 300
    assert [leg["line"] for leg in body["legs"]] == ["green"]


async def test_two_real_stations_with_no_route_is_a_200_with_a_reason(
    api: AsyncClient, db: AsyncSession
) -> None:
    """**The one that matters.**

    ORPHAN exists and has no track. That is a successful answer to a
    well-formed question, so it is a 200 carrying a reason - not a 404, which
    would tell the client its request was wrong, and not a 500, which would
    claim the service is broken while it is working correctly.

    It is also the case 2021 signalled with 9999999.
    """
    await seed_two_line_network(db)

    response = await api.post("/route", json={"origin": "A", "destination": "ORPHAN"})

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert body["reason"] == "disconnected"
    assert body["legs"] == []


async def test_an_unknown_station_is_a_404_naming_which_one(
    api: AsyncClient, db: AsyncSession
) -> None:
    # "One of your stations does not exist" is not a useful thing to tell
    # someone, and it is the easy version to write.
    await seed_two_line_network(db)

    missing_origin = await api.post(
        "/route", json={"origin": "NOWHERE", "destination": "C"}
    )
    missing_destination = await api.post(
        "/route", json={"origin": "A", "destination": "NOWHERE"}
    )

    assert missing_origin.status_code == 404
    assert "NOWHERE" in missing_origin.json()["detail"]
    assert missing_destination.status_code == 404
    assert "NOWHERE" in missing_destination.json()["detail"]


async def test_an_unknown_objective_is_a_400_listing_the_real_ones(
    api: AsyncClient, db: AsyncSession
) -> None:
    # A malformed request rather than a missing resource, and the guard runs
    # before the network is built because no graph is needed to know that
    # "quickest" is not an objective.
    await seed_two_line_network(db)

    response = await api.post(
        "/route", json={"origin": "A", "destination": "C", "objective": "quickest"}
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "quickest" in detail
    assert "fewest_changes" in detail


async def test_a_missing_field_is_a_422_from_the_schema(
    api: AsyncClient, db: AsyncSession
) -> None:
    # Pydantic's job, asserted so that loosening the schema is a failing test
    # rather than a silently accepted empty origin.
    await seed_two_line_network(db)

    assert (await api.post("/route", json={"origin": "A"})).status_code == 422
    assert (
        await api.post("/route", json={"origin": "", "destination": "C"})
    ).status_code == 422


async def test_origin_equal_to_destination_is_an_empty_route_not_an_error(
    api: AsyncClient, db: AsyncSession
) -> None:
    # "You are already there" - the same reasoning that made an empty station
    # search a 200 in Phase 3.
    await seed_two_line_network(db)

    body = await plan(api, destination="A")

    assert body["found"] is True
    assert body["total_seconds"] == 0
    assert body["legs"] == []


def status_of(*entries: tuple[str, int, str, bool]) -> dict:
    """A stored status payload, in the shape the poller writes."""
    return {
        "as_of": "2026-09-15T12:00:00+00:00",
        "lines": [
            {
                "line_code": code,
                "severity": severity,
                "description": description,
                "reason": f"{code}: {description.lower()}",
                "running": running,
            }
            for code, severity, description, running in entries
        ],
    }


async def suspend(monkeypatch: pytest.MonkeyPatch, *lines: str) -> None:
    """Make the last known status report these lines as not running.

    Patches status_poller.current rather than cache.read_json. The cache
    module is shared - graph_loader reads the network rows through the same
    function - so patching it globally hands the loader a status payload and
    it fails with KeyError: 'stations'. Patching the seam the route actually
    uses leaves the loader alone and still exercises not_running_lines.
    """

    async def fake() -> dict:
        return status_of(*((code, 2, "Suspended", False) for code in lines))

    monkeypatch.setattr(status_poller, "current", fake)


async def test_a_suspended_line_changes_the_route(
    api: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline test of Phase 7.

    Fastest is 80 seconds via red then blue. Suspend the blue line and the
    only remaining way to C is the 300-second green one. Nothing about the
    request changes - the answer changes because the network did.
    """
    await seed_two_line_network(db)
    before = await plan(api)
    assert before["total_seconds"] == 80

    await suspend(monkeypatch, "blue")
    after = await plan(api)

    assert after["found"] is True
    assert after["total_seconds"] == 300
    assert [leg["line"] for leg in after["legs"]] == ["green"]


async def test_the_answer_says_which_line_it_avoided(
    api: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A journey that silently takes a strange path is indistinguishable from a
    # bug. A user who cannot see why has been given an answer they cannot
    # check, which is the 9999999 problem wearing better clothes.
    await seed_two_line_network(db)
    await suspend(monkeypatch, "blue")

    body = await plan(api)

    assert body["avoided_for_disruption"] == ["blue"]
    # And it is absent when nothing is wrong, rather than always present.
    monkeypatch.undo()
    assert (await plan(api))["avoided_for_disruption"] == []


async def test_a_delay_does_not_change_the_route(
    api: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counterweight, and the one that stops the rule quietly widening.

    Severe Delays is the severity it is most tempting to avoid. Doing so would
    reroute every Piccadilly journey in London over a condition that is often
    gone within the hour, and the user would never know why their trip got
    longer.
    """
    await seed_two_line_network(db)

    async def delayed() -> dict:
        return status_of(("blue", 6, "Severe Delays", True))

    monkeypatch.setattr(status_poller, "current", delayed)

    body = await plan(api)

    assert body["total_seconds"] == 80
    assert body["avoided_for_disruption"] == []


async def test_a_suspension_that_cuts_the_destination_off_is_not_a_500(
    api: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Suspend both ways to C and there is no journey at all. That is still a
    # well-formed question with a negative answer, and the avoided list is
    # what separates "nowhere to go" from "nowhere to go while these are shut".
    await seed_two_line_network(db)
    await suspend(monkeypatch, "blue", "green")

    response = await api.post("/route", json={"origin": "A", "destination": "C"})

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert body["reason"] == "disconnected"
    assert body["avoided_for_disruption"] == ["blue", "green"]


async def test_an_unknown_status_never_removes_a_line(
    api: AsyncClient, db: AsyncSession
) -> None:
    # conftest points REDIS_URL at a dead port, so this runs with no status at
    # all - the state for the first minute after every restart. An unknown
    # status must not refuse a journey that is perfectly possible.
    await seed_two_line_network(db)

    body = await plan(api)

    assert body["total_seconds"] == 80
    assert body["avoided_for_disruption"] == []
