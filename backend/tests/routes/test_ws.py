"""
Tests for the live status WebSocket.

WHY THIS EXISTS
    Two separate claims, and they fail in different ways.

    The socket sends the current picture the moment it connects. Without that
    a client arriving on a quiet day sits blank until the next change - which
    could be an hour - and a blank page is indistinguishable from a broken
    connection.

    And the push travels through **Redis**, not through a list of sockets in
    this process. An in-process broadcast works perfectly with one worker and
    silently fails with two, so the thing worth testing is precisely the part
    that a single-process test would not notice.

NO 2021 EQUIVALENT
    A Tkinter window reading SQLite in its own process. Nothing to push to,
    nothing to push from.

CONSTRAINT
    The first four run anywhere, against a fake subscription - they are about
    the endpoint's behaviour, and skipping them when Redis is absent would
    leave the socket untested on most machines.

    The last one needs a real Redis and skips without TEST_REDIS_URL, the same
    bargain the database tests make. It is the only one that proves the
    pub/sub wiring rather than the code around it.
"""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import cache
from app.core.config import get_settings
from app.main import app
from app.services import status_poller

SAMPLE = {
    "as_of": "2026-09-15T12:00:00+00:00",
    "lines": [
        {
            "line_code": "piccadilly",
            "severity": 6,
            "description": "Severe Delays",
            "reason": "piccadilly: severe delays",
            "running": True,
        }
    ],
}

CHANGED = {
    "as_of": "2026-09-15T12:05:00+00:00",
    "lines": [
        {
            "line_code": "piccadilly",
            "severity": 2,
            "description": "Suspended",
            "reason": "piccadilly: suspended",
            "running": False,
        }
    ],
}


# TestClient runs the lifespan, and the real one creates a background task
# that talks to api.tfl.gov.uk. A test suite must not depend on someone
# else's server - the rule test_tfl.py states outright.
@pytest.fixture(autouse=True)
def _no_real_poller(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the application's lifespan from starting a poller against TfL."""

    async def noop(stop: object = None) -> None:
        """Stand in for the poller and do nothing."""
        return

    monkeypatch.setattr(status_poller, "run", noop)


def fake_subscription(*messages: Any) -> object:
    """Stand in for cache.subscription, yielding a fixed list then ending."""

    @asynccontextmanager
    async def subscription(channel: str) -> AsyncIterator[AsyncIterator[Any]]:
        """Yield an iterator over the prepared messages, as Redis would."""

        async def messages_iter() -> AsyncIterator[Any]:
            """Yield each prepared message in turn."""
            for message in messages:
                yield message

        yield messages_iter()

    return subscription


def test_a_new_client_is_sent_the_current_picture_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new client is sent the current picture immediately."""

    # Before any subscription traffic. A client connecting during a quiet
    # spell would otherwise show nothing until the next change.
    async def current() -> dict:
        """Return the sample status."""
        return SAMPLE

    monkeypatch.setattr(status_poller, "current", current)
    monkeypatch.setattr(cache, "subscription", fake_subscription())

    with TestClient(app) as client, client.websocket_connect("/ws/status") as ws:
        assert ws.receive_json() == SAMPLE


def test_a_published_change_reaches_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A published change reaches the client."""

    async def current() -> dict:
        """Return the sample status."""
        return SAMPLE

    monkeypatch.setattr(status_poller, "current", current)
    monkeypatch.setattr(cache, "subscription", fake_subscription(CHANGED))

    with TestClient(app) as client, client.websocket_connect("/ws/status") as ws:
        assert ws.receive_json() == SAMPLE
        assert ws.receive_json() == CHANGED


def test_an_unknown_status_still_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown status still connects."""

    # The first minute after a restart. The socket must open and say "I do not
    # know yet" rather than refusing the connection - a page that cannot
    # connect looks broken, while an empty status is honest.
    async def nothing_known() -> dict:
        """Return a status that knows nothing yet."""
        return {"as_of": None, "lines": []}

    monkeypatch.setattr(status_poller, "current", nothing_known)
    monkeypatch.setattr(cache, "subscription", fake_subscription())

    with TestClient(app) as client, client.websocket_connect("/ws/status") as ws:
        assert ws.receive_json() == {"as_of": None, "lines": []}


# core/cache.py absorbs Redis failures everywhere else; this is the one
# place that holds a connection open across one, so it gets its own test.
def test_an_unreachable_redis_does_not_break_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client keeps what it was given rather than seeing an error."""

    async def current() -> dict:
        """Return the sample status."""
        return SAMPLE

    @asynccontextmanager
    async def exploding(channel: str) -> AsyncIterator[AsyncIterator[Any]]:
        """Fail to subscribe, as an unreachable Redis would."""
        raise OSError("redis is not there")
        yield  # pragma: no cover - unreachable, satisfies the generator shape

    monkeypatch.setattr(status_poller, "current", current)
    monkeypatch.setattr(cache, "subscription", exploding)

    with TestClient(app) as client, client.websocket_connect("/ws/status") as ws:
        # The current picture still arrives, and the socket closes cleanly
        # afterwards instead of raising into the client.
        assert ws.receive_json() == SAMPLE


# The only test that proves the pub/sub wiring rather than the code.
#
# Two sockets, one publish, both receive it. That is the multi-worker claim
# Redis is there to support: the poller runs in one process and a browser
# may be connected to another, so an in-process broadcast would pass every
# other test in this file and fail in production.
#
# Skips without TEST_REDIS_URL, the same bargain the database tests make -
# and CI sets it, because a silently skipped test that never runs anywhere
# is worse than no test.
@pytest.mark.skipif(
    not os.environ.get("TEST_REDIS_URL"),
    reason="needs a real Redis; set TEST_REDIS_URL",
)
def test_two_clients_both_receive_one_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two sockets each receive a single publish through a real Redis."""
    # get_settings is cached, so setting the variable is not enough on its own
    # - the dead port conftest installs for the whole suite would still be
    # what get_client reads. Both caches have to go.
    monkeypatch.setenv("REDIS_URL", os.environ["TEST_REDIS_URL"])
    get_settings.cache_clear()
    cache._client = None

    async def current() -> dict:
        """Return the sample status."""
        return SAMPLE

    monkeypatch.setattr(status_poller, "current", current)

    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/status") as first,
        client.websocket_connect("/ws/status") as second,
    ):
        assert first.receive_json() == SAMPLE
        assert second.receive_json() == SAMPLE

        import redis

        publisher = redis.from_url(os.environ["TEST_REDIS_URL"])
        publisher.publish(status_poller.STATUS_CHANNEL, json.dumps(CHANGED))
        publisher.close()

        assert first.receive_json() == CHANGED
        assert second.receive_json() == CHANGED

    # Put the suite back where it found it: a live client and live settings
    # would leak into every later test, which all expect Redis to be absent.
    cache._client = None
    get_settings.cache_clear()
