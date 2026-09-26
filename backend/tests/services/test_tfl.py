"""Tests for the TfL client."""

import io
import json
import zipfile
from pathlib import Path
from unittest import mock

import httpx
import pytest

from app.services.tfl import RATE_LIMIT_PAUSE, TfLClient, TfLError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tfl"


def fixture(name: str) -> object:
    """Load a recorded TfL response from the fixtures folder."""
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
        transport=httpx.MockTransport(handler),
    )


# --- happy paths -------------------------------------------------------------


async def test_tube_lines_returns_every_line() -> None:
    """tube_lines() returns every line."""
    payload = fixture("lines_tube.json")

    async with client_returning(lambda r: httpx.Response(200, json=payload)) as tfl:
        lines = await tfl.tube_lines()

    ids = {line["id"] for line in lines}
    assert len(lines) == 11
    assert "waterloo-city" in ids


async def test_route_sequence_preserves_station_order() -> None:
    """route_sequence() preserves station order."""
    # Order is the whole point of this endpoint: consecutive pairs become segments, so a
    # client that reordered them would silently produce a network with the wrong
    # adjacency.
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
    """The requested path is the one called."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the path asked for and answer with an empty object."""
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
    """The app key is sent when one is set."""
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the app key sent and answer with an empty list."""
        seen.append(request.url.params.get("app_key"))
        return httpx.Response(200, json=[])

    async with client_returning(handler, app_key="abc123") as tfl:
        await tfl.tube_lines()

    assert seen == ["abc123"]


async def test_app_key_is_omitted_entirely_when_blank() -> None:
    """The app key is omitted entirely when blank."""
    # Not sent as an empty string: TfL rejects app_key= as a malformed key, which would
    # break the project for anyone who has not got one - and every endpoint the seed
    # uses answers fine without.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the full URL and answer with an empty list."""
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    async with client_returning(handler, app_key="") as tfl:
        await tfl.tube_lines()

    assert "app_key" not in seen[0]


# --- failure paths -----------------------------------------------------------


async def test_a_server_error_is_retried_and_then_succeeds() -> None:
    """A server error is retried and then succeeds."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Fail twice with a 503, then answer."""
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"id": "victoria"}])

    async with client_returning(handler) as tfl:
        lines = await tfl.tube_lines()

    assert attempts["n"] == 3
    assert lines == [{"id": "victoria"}]


async def test_a_client_error_is_not_retried() -> None:
    """A client error is not retried."""
    # A 404 means the line id is wrong. Retrying is being wrong three times more slowly,
    # and it triples the load on someone else's server.
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Refuse every request with a 404."""
        attempts["n"] += 1
        return httpx.Response(404)

    async with client_returning(handler) as tfl:
        with pytest.raises(TfLError, match="will not change on a retry"):
            await tfl.route_sequence("not-a-line", "inbound")

    assert attempts["n"] == 1


async def test_rate_limiting_is_retried_even_though_it_is_a_4xx() -> None:
    """Rate limiting is retried even though it is a 4xx."""
    # The exception to "4xx will not change on a retry". A 429 does not mean the request
    # was wrong, it means it was too soon - waiting is the entire fix. This was found by
    # running the real seed: TfL allows 50 requests a minute without a key and a full
    # run makes about ninety, so it died a third of the way through on hammersmith-city.
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Rate-limit the first request, then answer."""
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=[{"id": "victoria"}])

    async with client_returning(handler) as tfl:
        lines = await tfl.tube_lines()

    assert attempts["n"] == 2
    assert lines == [{"id": "victoria"}]


async def test_retry_after_is_honoured_when_tfl_sends_one() -> None:
    """Retry-After is honoured when TfL sends one."""
    # Sleeping for our own backoff when the server has said how long to wait means
    # either waiting too long or being rate limited again immediately.
    slept: list[float] = []

    async def record(seconds: float) -> None:
        """Note the pause asked for instead of sleeping."""
        slept.append(seconds)

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Ask for a seven second pause once, then answer."""
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json=[])

    with mock.patch("app.services.tfl.asyncio.sleep", record):
        async with client_returning(handler) as tfl:
            await tfl.tube_lines()

    assert slept == [7.0]


async def test_a_malformed_retry_after_falls_back_to_a_sane_pause() -> None:
    """A malformed Retry-After falls back to a sane pause."""
    slept: list[float] = []

    async def record(seconds: float) -> None:
        """Note the pause asked for instead of sleeping."""
        slept.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        """Rate-limit every request with a Retry-After nobody can parse."""
        return httpx.Response(429, headers={"Retry-After": "in a bit"})

    with mock.patch("app.services.tfl.asyncio.sleep", record):
        async with client_returning(handler, max_attempts=2) as tfl:
            with pytest.raises(TfLError, match="failed after 2 attempts"):
                await tfl.tube_lines()

    assert slept == [RATE_LIMIT_PAUSE]


async def test_requests_are_spaced_when_an_interval_is_set() -> None:
    """Requests are spaced when an interval is set."""
    # The throttle is what stops the 429 happening at all. Without it the retry above is
    # the only thing between the seed and a failed run.
    slept: list[float] = []

    async def record(seconds: float) -> None:
        """Note the pause asked for instead of sleeping."""
        slept.append(seconds)

    async with TfLClient(
        base_url="https://tfl.test",
        min_request_interval_seconds=1.3,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])),
    ) as tfl:
        with mock.patch("app.services.tfl.asyncio.sleep", record):
            await tfl.tube_lines()
            await tfl.tube_lines()

    # The first request goes immediately; the second waits out the interval.
    assert len(slept) == 1
    assert 0 < slept[0] <= 1.3


async def test_no_throttling_by_default() -> None:
    """No throttling by default."""
    # Tests and any future caller with a key should not pay for a limit they are not
    # subject to.
    slept: list[float] = []

    async def record(seconds: float) -> None:
        """Note the pause asked for instead of sleeping."""
        slept.append(seconds)

    async with client_returning(lambda r: httpx.Response(200, json=[])) as tfl:
        with mock.patch("app.services.tfl.asyncio.sleep", record):
            await tfl.tube_lines()
            await tfl.tube_lines()

    assert slept == []


async def test_a_timeout_is_retried_then_raises() -> None:
    """A timeout is retried then raises."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Time out on every attempt."""
        attempts["n"] += 1
        raise httpx.ConnectTimeout("timed out")

    async with client_returning(handler, max_attempts=2) as tfl:
        with pytest.raises(TfLError, match="failed after 2 attempts"):
            await tfl.tube_lines()

    assert attempts["n"] == 2


async def test_a_non_json_body_is_an_error_not_a_crash() -> None:
    """A non-JSON body is an error, not a crash."""

    # TfL occasionally answers 200 with an HTML error page in front of a maintenance
    # window. Without this the seed dies on a JSONDecodeError several frames from the
    # cause.
    def handler(request: httpx.Request) -> httpx.Response:
        """Answer 200 with an HTML maintenance page."""
        return httpx.Response(200, text="<html>maintenance</html>")

    async with client_returning(handler) as tfl:
        with pytest.raises(TfLError, match="not JSON"):
            await tfl.tube_lines()


# --- the station data archive ------------------------------------------------


def _zip_of(files: dict[str, str]) -> bytes:
    """Build an in-memory ZIP holding the given files."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return buffer.getvalue()


async def test_station_data_reads_the_two_csvs_it_needs() -> None:
    """station_data() reads the two CSVs it needs."""
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
        station_data = await tfl.station_data()

    assert station_data.platform_services[0]["StopAreaNaptanCode"] == "940GZZLUGPK"
    assert station_data.platform_services[0]["DesignatedLevelAccessPoint"] == "TRUE"
    assert station_data.step_free_interchanges[0]["DistanceInMetres"] == "220"


async def test_station_data_strips_the_byte_order_mark() -> None:
    """station_data() strips the byte order mark."""
    # TfL writes a BOM. Without utf-8-sig the first column name comes back as
    # "﻿PlatformUniqueId" and every lookup of it returns None - which presents as
    # missing data rather than as an encoding problem, and is therefore the kind of bug
    # that gets debugged in the wrong place.
    payload = _zip_of(
        {
            "PlatformServices.csv": "﻿PlatformUniqueId,Line\nX,victoria\n",
            "StepFreeIntechangeInfo.csv": "FromPlatformUniqueId\nY\n",
        }
    )

    async with client_returning(lambda r: httpx.Response(200, content=payload)) as tfl:
        station_data = await tfl.station_data()

    assert "PlatformUniqueId" in station_data.platform_services[0]


async def test_a_corrupt_archive_is_reported_clearly() -> None:
    """A corrupt archive is reported clearly."""
    async with client_returning(
        lambda r: httpx.Response(200, content=b"not a zip file")
    ) as tfl:
        with pytest.raises(TfLError, match="unreadable"):
            await tfl.station_data()


async def test_line_status_calls_the_status_endpoint() -> None:
    """line_status() calls the status endpoint."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the path and answer with the recorded status."""
        seen.append(request.url.path)
        return httpx.Response(200, json=fixture("line_status.json"))

    async with client_returning(handler) as tfl:
        statuses = await tfl.line_status()

    assert seen == ["/Line/Mode/tube/Status"]
    assert len(statuses) == 11


async def test_line_status_is_retried_like_every_other_call() -> None:
    """line_status() is retried like every other call."""
    # It reuses _get_json, so the throttle, the 429 handling and the retry all apply.
    # Asserted rather than assumed, because a poller that gave up on the first 5xx would
    # go stale silently - there is no user watching a request fail, which is exactly
    # what makes it worth testing.
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Fail once with a 503, then answer with the recorded status."""
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=fixture("line_status.json"))

    async with client_returning(handler) as tfl:
        statuses = await tfl.line_status()

    assert attempts == 2
    assert len(statuses) == 11
