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
