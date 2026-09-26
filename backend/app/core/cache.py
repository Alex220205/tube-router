"""Redis, wrapped so that losing it slows the service rather than stopping it."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings

# Redis is on the same network as the API, so a healthy round trip is well under a
# millisecond. These are generous for that and still fail fast when it is simply not
# there.
CONNECT_TIMEOUT_SECONDS = 0.25
READ_TIMEOUT_SECONDS = 0.5

_client: redis.Redis | None = None


# Built lazily rather than at import so that importing `app` does not require Redis to
# exist - which is what lets the test suite and Alembic run without it.
def get_client() -> redis.Redis:
    """The shared Redis client, created once per process."""
    global _client
    if _client is None:
        _client = redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            # Short on purpose. This is a latency optimisation, so a Redis that cannot
            # answer quickly is not helping - and the default waits long enough for an
            # unreachable host that the "cache" becomes slower than the database it was
            # meant to save.
            socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
            socket_timeout=READ_TIMEOUT_SECONDS,
        )
    return _client


# The decoded value, or None on a miss, on unreadable content, or if Redis cannot be
# reached at all. The caller cannot tell these apart and should not need to - every one
# of them means "go to the source".
async def read_json(key: str) -> Any | None:
    """Read a JSON value."""
    try:
        raw = await get_client().get(key)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Something else wrote this key, or wrote it in an older shape. Treat it as
        # absent rather than crashing a request over a cache entry.
        return None


async def write_json(key: str, value: Any, ttl_seconds: int) -> None:
    """Store a JSON value, best effort."""
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


GENERATION_KEY = "tube-router:generation"


# The integer, 0 if the key has never been set, or None if Redis could not be reached.
# None and 0 are deliberately different: "no answer" must not be mistaken for
# "generation zero", or an unreachable Redis would look like a signal to rebuild on
# every single request.
async def read_generation() -> int | None:
    """The current graph generation."""
    try:
        raw = await get_client().get(GENERATION_KEY)
    except Exception:
        return None
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        # Something else owns this key, or wrote a non-integer into it. Treat it as
        # unknown rather than crashing a route request over it.
        return None


# INCR rather than read-modify-write, so two seeds running at once cannot produce the
# same number and leave one of them invisible.
async def bump_generation() -> int | None:
    """Mark every built graph stale. Called by the seed after it commits."""
    try:
        return int(await get_client().incr(GENERATION_KEY))
    except Exception:
        return None


# Redis rather than an in-process list of connected sockets, because the API can run
# more than one worker and a message published by the worker holding the poller has to
# reach clients connected to the others.


# A failure here means connected clients keep their last view until the next push rather
# than the service breaking, which is the same trade every other function in this module
# makes.
async def publish(channel: str, value: Any) -> None:
    """Announce a change to every subscriber, best effort."""
    try:
        await get_client().publish(channel, json.dumps(value))
    except (TypeError, ValueError):
        raise
    except Exception:
        return


# The pub/sub object gets its own connection, so closing it is not optional: a WebSocket
# that disconnects without unsubscribing leaks a connection per client, and the leak
# only shows up under the load it was built for.
@asynccontextmanager
async def subscription(channel: str) -> AsyncIterator[AsyncIterator[Any]]:
    """Subscribe to a channel and yield decoded messages until the caller stops."""
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
