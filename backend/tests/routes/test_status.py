"""
Tests for the status poller and GET /status.

WHY THIS EXISTS
    The poller is the only part of this project that runs with no caller, and
    that changes what a failure means. There is no user watching it and no
    request to return a 500 to, so a task that dies takes live status with it
    and leaves nothing on the page to say so - the status simply stops
    changing, which looks exactly like a quiet day on the Underground.

    Every test here is about that: it keeps going, it does not overwrite good
    data with nothing, and it does not shout when nothing has happened.

NO 2021 EQUIVALENT
    The old project read status once at launch into a SQLite column and never
    refreshed it. There was no poller to test and no endpoint to call.

CONSTRAINT
    No TfL, no database. Redis is absent, because conftest points REDIS_URL at
    a dead port for the whole suite - which means these also prove the
    endpoint answers correctly with no cache at all.
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.services import status_poller
from app.services.status import statuses_from_payload
from app.services.tfl import TfLClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tfl"


def payload() -> list[dict]:
    """The recorded TfL line status response."""
    return json.loads((FIXTURES / "line_status.json").read_text(encoding="utf-8"))


def client_returning(handler: object) -> TfLClient:
    """A TfL client wired to a MockTransport, as test_tfl.py does."""
    return TfLClient(
        base_url="https://tfl.test",
        timeout_seconds=0.5,
        max_attempts=1,
        transport=httpx.MockTransport(handler),
    )


# This is the state for the first minute after every restart. A 503 would
# make the frontend render an error over a condition that resolves itself,
# and would say the service is broken while it is working correctly - the
# same reasoning that made an empty station search a 200 in Phase 3.
async def test_status_before_the_poller_has_run_is_a_200_not_an_error(
    client: AsyncClient,
) -> None:
    """Empty, with a null timestamp, rather than a 503."""
    response = await client.get("/status")

    assert response.status_code == 200
    assert response.json() == {"as_of": None, "lines": []}


async def test_a_poll_stores_what_tfl_said(monkeypatch: pytest.MonkeyPatch) -> None:
    """A poll stores what TfL said."""
    stored: dict[str, object] = {}

    async def fake_write(key: str, value: object, ttl_seconds: int) -> None:
        """Keep what would have been written to Redis."""
        stored[key] = value

    monkeypatch.setattr(status_poller.cache, "write_json", fake_write)

    async with client_returning(lambda r: httpx.Response(200, json=payload())) as tfl:
        statuses = await status_poller.poll_once(tfl)

    assert statuses is not None
    assert len(statuses) == 11
    written = stored[status_poller.STATUS_KEY]
    assert isinstance(written, dict)
    assert written["as_of"] is not None
    assert len(written["lines"]) == 11


# An unreachable TfL must not overwrite Redis with an empty list. An empty
# list reads as "every line is fine" to anything that sees it, so the failure
# mode would be a page confidently reporting Good Service across a network
# with two lines suspended.
async def test_a_failed_poll_leaves_the_last_good_status_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one that matters most, and the easy thing to get wrong."""
    wrote = False

    async def fake_write(key: str, value: object, ttl_seconds: int) -> None:
        """Note that a write happened, which it should not."""
        nonlocal wrote
        wrote = True

    monkeypatch.setattr(status_poller.cache, "write_json", fake_write)

    def refuse(request: httpx.Request) -> httpx.Response:
        """Fail every request as though TfL were unreachable."""
        raise httpx.ConnectError("no route to host")

    async with client_returning(refuse) as tfl:
        assert await status_poller.poll_once(tfl) is None

    assert wrote is False


async def test_a_payload_with_nothing_usable_is_also_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A payload with nothing usable is also left alone."""

    # TfL serves HTML during maintenance and occasionally an empty array. Both
    # parse to no statuses, and neither is a reason to forget what we knew.
    async def fake_write(key: str, value: object, ttl_seconds: int) -> None:
        """Fail the test, because an empty status must not be written."""
        raise AssertionError("should not write an empty status")

    monkeypatch.setattr(status_poller.cache, "write_json", fake_write)

    async with client_returning(lambda r: httpx.Response(200, json=[])) as tfl:
        assert await status_poller.poll_once(tfl) is None


# If an exception escaped `run`, the poller would stop permanently and the
# only symptom would be status that never changes again.
async def test_the_loop_survives_a_failing_poll_and_tries_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task that dies is invisible, which is why this is asserted."""
    calls = 0
    stop = asyncio.Event()

    async def exploding(tfl: object) -> None:
        """Raise on every poll, and stop the loop on the third."""
        # Counts, then ends the loop itself on the third call. Driven by the
        # loop rather than by a sleep racing it: "more than one call happened
        # in 150ms" passes alone and fails on a loaded machine, which is issue
        # #12 in different words.
        nonlocal calls
        calls += 1
        if calls >= 3:
            stop.set()
        raise RuntimeError("something nobody anticipated")

    monkeypatch.setattr(status_poller, "poll_once", exploding)
    monkeypatch.setattr(status_poller, "RETRY_AFTER_SECONDS", 0.0)

    # If the exception escaped `run`, stop is never set and this times out -
    # the failure being guarded against, reported as a failure.
    await asyncio.wait_for(status_poller.run(stop), timeout=10)

    assert calls == 3


async def test_an_unchanged_picture_is_not_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unchanged picture is not published."""
    # Sixty polls an hour with a push each would wake every connected browser
    # sixty times to say nothing happened, and a client that learns to ignore
    # the channel is worse than no channel.
    published: list[object] = []

    async def fake_publish(channel: str, value: object) -> None:
        """Keep every publish so the test can count them."""
        published.append(value)

    same = statuses_from_payload(payload())
    polls = 0
    stop = asyncio.Event()

    async def unchanging(tfl: object) -> object:
        """Return the same statuses every time, and stop after four polls."""
        nonlocal polls
        polls += 1
        if polls >= 4:
            stop.set()
        return same

    monkeypatch.setattr(status_poller.cache, "publish", fake_publish)
    monkeypatch.setattr(status_poller, "poll_once", unchanging)
    monkeypatch.setattr(get_settings(), "tfl_status_poll_seconds", 0.0, raising=False)

    await asyncio.wait_for(status_poller.run(stop), timeout=10)

    # Four identical polls, one push: on the first sighting and never again.
    assert polls == 4
    assert len(published) == 1


async def test_status_reports_what_the_cache_holds(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /status reports what the cache holds."""
    # The positive counterpart to the empty case: when the poller has run, the
    # endpoint serves what it stored rather than an empty shell.
    stored = status_poller.to_payload(statuses_from_payload(payload()))

    async def fake_read(key: str) -> object:
        """Return the stored status whatever key is asked for."""
        return stored

    monkeypatch.setattr(status_poller.cache, "read_json", fake_read)

    body = (await client.get("/status")).json()

    assert body["as_of"] == stored["as_of"]
    assert len(body["lines"]) == 11
    piccadilly = next(x for x in body["lines"] if x["line_code"] == "piccadilly")
    assert piccadilly["description"] == "Severe Delays"
    # Delayed, but running - so nothing will be routed around it.
    assert piccadilly["running"] is True
