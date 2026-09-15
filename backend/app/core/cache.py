"""
Redis, wrapped so that losing it slows the service rather than stopping it.

WHY THIS EXISTS
    One place that knows the connection lives here for the same reason
    SessionDep does: `core/` depends on nothing else in `app/`, so everything
    may depend on it. Phase 6 caches the rows the routing graph is built
    from; Phase 7 adds live line status on top of the same client.

    Every function here swallows Redis failures and reports a miss. That is
    deliberate, and it is *not* the "silent failure" this project argues
    against elsewhere. The distinction is whether the caller still gets a
    correct answer: a migration that silently does not apply leaves a
    database that is wrong, whereas a cache miss produces exactly the right
    result, more slowly, from the source. A cache that can take the service
    down with it is worse than no cache.

NO 2021 EQUIVALENT
    The old project stored live line status in a persistent SQLite table and
    deleted every row on launch to reinsert it - a cache wearing a table's
    clothing. There was no cache, and nothing that needed one, because the
    graph was rebuilt from SQL on every search anyway.

WHAT'S NEW
    Nothing here is required for correctness. The service answers every
    request identically with Redis stopped, which is the property the
    swallowed exceptions buy and the reason they are acceptable.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings

# Redis is on the same network as the API, so a healthy round trip is well
# under a millisecond. These are generous for that and still fail fast when
# it is simply not there.
CONNECT_TIMEOUT_SECONDS = 0.25
READ_TIMEOUT_SECONDS = 0.5

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    """The shared Redis client, created once per process.

    Built lazily rather than at import so that importing `app` does not
    require Redis to exist - which is what lets the test suite and Alembic
    run without it.
    """
    global _client
    if _client is None:
        _client = redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            # Short on purpose. This is a latency optimisation, so a Redis
            # that cannot answer quickly is not helping - and the default
            # waits long enough for an unreachable host that the "cache"
            # becomes slower than the database it was meant to save.
            #
            # Measured: with the default, eight endpoint tests against a
            # Redis that does not resolve took 54 seconds instead of 20.
            socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
            socket_timeout=READ_TIMEOUT_SECONDS,
        )
    return _client


async def read_json(key: str) -> Any | None:
    """Read a JSON value.

    Args:
        key: Cache key.

    Returns:
        The decoded value, or None on a miss, on unreadable content, or if
        Redis cannot be reached at all. The caller cannot tell these apart
        and should not need to - every one of them means "go to the source".
    """
    try:
        raw = await get_client().get(key)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Something else wrote this key, or wrote it in an older shape. Treat
        # it as absent rather than crashing a request over a cache entry.
        return None


async def write_json(key: str, value: Any, ttl_seconds: int) -> None:
    """Store a JSON value, best effort.

    Args:
        key: Cache key.
        value: Anything json.dumps can handle.
        ttl_seconds: Expiry. Always set - an entry that never expires is one
            that has to be invalidated correctly forever, and getting that
            wrong serves stale data indefinitely.
    """
    try:
        await get_client().set(key, json.dumps(value), ex=ttl_seconds)
    except (TypeError, ValueError):
        # A programming error in the caller's payload, not a Redis problem.
        raise
    except Exception:
        return


async def delete(key: str) -> None:
    """Drop a key, best effort. Used by the seed to invalidate after writing."""
    try:
        await get_client().delete(key)
    except Exception:
        return


async def close() -> None:
    """Release the connection pool. Called from the application's lifespan."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# --- the generation key ------------------------------------------------------
#
# One integer that says "the graph you built is out of date". The seed bumps
# it; graph_loader compares it against the generation its current graph was
# built at. Phase 6 shipped without this and the seed's invalidation did
# nothing for a running process - see docs/ISSUES.md #9.

GENERATION_KEY = "tube-router:generation"


async def read_generation() -> int | None:
    """The current graph generation.

    Returns:
        The integer, 0 if the key has never been set, or None if Redis could
        not be reached. None and 0 are deliberately different: "no answer" must
        not be mistaken for "generation zero", or an unreachable Redis would
        look like a signal to rebuild on every single request.
    """
    try:
        raw = await get_client().get(GENERATION_KEY)
    except Exception:
        return None
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        # Something else owns this key, or wrote a non-integer into it. Treat
        # it as unknown rather than crashing a route request over it.
        return None


async def bump_generation() -> int | None:
    """Mark every built graph stale. Called by the seed after it commits.

    Returns:
        The new generation, or None if Redis could not be reached.

    INCR rather than read-modify-write, so two seeds running at once cannot
    produce the same number and leave one of them invisible.
    """
    try:
        return int(await get_client().incr(GENERATION_KEY))
    except Exception:
        return None


# --- pub/sub -----------------------------------------------------------------
#
# Redis rather than an in-process list of connected sockets, because the API
# can run more than one worker and a message published by the worker holding
# the poller has to reach clients connected to the others. An in-process
# broadcast works perfectly on one process and silently fails on two, which is
# the kind of thing that is only discovered in production.


async def publish(channel: str, value: Any) -> None:
    """Announce a change to every subscriber, best effort.

    Args:
        channel: Channel name.
        value: Anything json.dumps can handle.

    A failure here means connected clients keep their last view until the next
    push rather than the service breaking, which is the same trade every other
    function in this module makes.
    """
    try:
        await get_client().publish(channel, json.dumps(value))
    except (TypeError, ValueError):
        raise
    except Exception:
        return


@asynccontextmanager
async def subscription(channel: str) -> AsyncIterator[AsyncIterator[Any]]:
    """Subscribe to a channel and yield decoded messages until the caller stops.

    Args:
        channel: Channel name.

    Yields:
        An async iterator of decoded JSON payloads. Messages that are not JSON
        are skipped rather than ending the subscription - one bad publish from
        somewhere else must not disconnect every listener.

    The pub/sub object gets its own connection, so closing it is not optional:
    a WebSocket that disconnects without unsubscribing leaks a connection per
    client, and the leak only shows up under the load it was built for.
    """
    client = get_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    try:
        yield _messages(pubsub)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


async def _messages(pubsub: Any) -> AsyncIterator[Any]:
    """Decoded payloads from a subscribed pubsub, one at a time."""
    async for message in pubsub.listen():
        if message.get("type") != "message":
            # Subscribe confirmations and pings. Real, and not for the caller.
            continue
        try:
            yield json.loads(message["data"])
        except (TypeError, ValueError):
            continue
