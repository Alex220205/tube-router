"""
Tests for the TfL client.

WHY THIS EXISTS
    The client is the only part of the seed that can fail for reasons outside
    this project — a timeout, a 503, a redirect, a body that is not JSON. The
    interesting behaviour is entirely in how it reacts to those, and none of
    it is observable by calling the real API and hoping for the best.

    Every test drives an httpx.MockTransport, so the retry and error paths
    are exercised deterministically and CI never depends on TfL being up. A
    red build should mean this repository is broken, not that someone else's
    server is having a bad afternoon.

NO 2021 EQUIVALENT
    The old project called TfL with no timeout, no retry and no tests.
"""

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from app.services.tfl import TfLClient, TfLError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tfl"


def fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def client_returning(
    handler: object, *, max_attempts: int = 3, app_key: str = ""
) -> TfLClient:
    """A client wired to a MockTransport instead of the network."""
    return TfLClient(
        base_url="https://tfl.test",
        app_key=app_key,
        timeout_seconds=0.5,
        max_attempts=max_attempts,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


# --- happy paths -------------------------------------------------------------


async def test_tube_lines_returns_every_line() -> None:
    payload = fixture("lines_tube.json")

    async with client_returning(lambda r: httpx.Response(200, json=payload)) as tfl:
        lines = await tfl.tube_lines()

    ids = {line["id"] for line in lines}
    assert len(lines) == 11
    # The one the 2021 database was missing entirely.
    assert "waterloo-city" in ids


async def test_route_sequence_preserves_station_order() -> None:
    # Order is the whole point of this endpoint: consecutive pairs become
    # segments, so a client that reordered them would silently produce a
    # network with the wrong adjacency.
    payload = fixture("route_sequence_victoria_inbound.json")

    async with client_returning(lambda r: httpx.Response(200, json=payload)) as tfl:
        sequence = await tfl.route_sequence("victoria", "inbound")

    stops = sequence["stopPointSequences"][0]["stopPoint"]
    assert [s["name"] for s in stops][:3] == [
        "Walthamstow Central Underground Station",
        "Blackhorse Road Underground Station",
        "Tottenham Hale Underground Station",
    ]


async def test_the_requested_path_is_the_one_called() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={})

    async with client_returning(handler) as tfl:
        await tfl.route_sequence("central", "outbound")
        await tfl.timetable("victoria", "940GZZLUWWL")

    assert seen == [
        "/Line/central/Route/Sequence/outbound",
        "/Line/victoria/Timetable/940GZZLUWWL",
    ]


# --- the app key -------------------------------------------------------------


async def test_app_key_is_sent_when_set() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("app_key"))
        return httpx.Response(200, json=[])

    async with client_returning(handler, app_key="abc123") as tfl:
        await tfl.tube_lines()

    assert seen == ["abc123"]


async def test_app_key_is_omitted_entirely_when_blank() -> None:
    # Not sent as an empty string: TfL rejects app_key= as a malformed key,
    # which would break the project for anyone who has not got one — and
    # every endpoint the seed uses answers fine without.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    async with client_returning(handler, app_key="") as tfl:
        await tfl.tube_lines()

    assert "app_key" not in seen[0]


# --- failure paths -----------------------------------------------------------


async def test_a_server_error_is_retried_and_then_succeeds() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"id": "victoria"}])

    async with client_returning(handler) as tfl:
        lines = await tfl.tube_lines()

    assert attempts["n"] == 3
    assert lines == [{"id": "victoria"}]


async def test_a_client_error_is_not_retried() -> None:
    # A 404 means the line id is wrong. Retrying is being wrong three times
    # more slowly, and it triples the load on someone else's server.
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(404)

    async with client_returning(handler) as tfl:
        with pytest.raises(TfLError, match="will not change on a retry"):
            await tfl.route_sequence("not-a-line", "inbound")

    assert attempts["n"] == 1


async def test_a_timeout_is_retried_then_raises() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectTimeout("timed out")

    async with client_returning(handler, max_attempts=2) as tfl:
        with pytest.raises(TfLError, match="failed after 2 attempts"):
            await tfl.tube_lines()

    assert attempts["n"] == 2


async def test_a_non_json_body_is_an_error_not_a_crash() -> None:
    # TfL occasionally answers 200 with an HTML error page in front of a
    # maintenance window. Without this the seed dies on a JSONDecodeError
    # several frames from the cause.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    async with client_returning(handler) as tfl:
        with pytest.raises(TfLError, match="not JSON"):
            await tfl.tube_lines()


# --- the station data archive ------------------------------------------------


def _zip_of(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return buffer.getvalue()


async def test_station_data_reads_the_two_csvs_it_needs() -> None:
    payload = _zip_of(
        {
            "PlatformServices.csv": (
                "PlatformUniqueId,StopAreaNaptanCode,Line,DesignatedLevelAccessPoint\n"
                "940GZZLUGPK-Plat03-NB-victoria,940GZZLUGPK,victoria,TRUE\n"
            ),
            "StepFreeIntechangeInfo.csv": (
                "FromPlatformUniqueId,ToPlatformUniqueId,DistanceInMetres\n"
                "A-Plat01-NB-victoria,A-Plat02-SB-central,220\n"
            ),
            # Nine other files the seed does not read.
            "Toilets.csv": "StationUniqueId\n910GACTONML\n",
        }
    )

    async with client_returning(lambda r: httpx.Response(200, content=payload)) as tfl:
        data = await tfl.station_data()

    assert data.platform_services[0]["StopAreaNaptanCode"] == "940GZZLUGPK"
    assert data.platform_services[0]["DesignatedLevelAccessPoint"] == "TRUE"
    assert data.step_free_interchanges[0]["DistanceInMetres"] == "220"


async def test_station_data_strips_the_byte_order_mark() -> None:
    # TfL writes a BOM. Without utf-8-sig the first column name comes back as
    # "﻿PlatformUniqueId" and every lookup of it returns None — which
    # presents as missing data rather than as an encoding problem, and is
    # therefore the kind of bug that gets debugged in the wrong place.
    payload = _zip_of(
        {
            "PlatformServices.csv": "﻿PlatformUniqueId,Line\nX,victoria\n",
            "StepFreeIntechangeInfo.csv": "FromPlatformUniqueId\nY\n",
        }
    )

    async with client_returning(lambda r: httpx.Response(200, content=payload)) as tfl:
        data = await tfl.station_data()

    assert "PlatformUniqueId" in data.platform_services[0]


async def test_a_corrupt_archive_is_reported_clearly() -> None:
    async with client_returning(
        lambda r: httpx.Response(200, content=b"not a zip file")
    ) as tfl:
        with pytest.raises(TfLError, match="unreadable"):
            await tfl.station_data()
