"""
Tests for the Redis wrapper.

WHY THIS EXISTS
    core/cache.py swallows every Redis failure and reports a miss. That is a
    deliberate decision and a dangerous-looking one, so it needs proving
    rather than asserting: the whole justification is that a caller still
    gets a correct answer, and a swallowed exception that did *not* produce a
    correct answer would be exactly the silent failure this project argues
    against everywhere else.

    The rest of the suite runs with REDIS_URL pointed at a dead port, so it
    exercises the degraded path constantly. What it never checks is that the
    degradation is deliberate rather than accidental.

NO 2021 EQUIVALENT
    There was no cache. The old project kept live line status in a persistent
    SQLite table and deleted every row on launch to reinsert it - a cache
    wearing a table's clothing, in the one place a cache did not belong.

CONSTRAINT
    Needs no Redis. Two of these require it to be *absent*, which conftest
    guarantees by pointing REDIS_URL at 127.0.0.1:1.
"""

import pytest

from app.core import cache


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    """Drop the memoised client so each test builds its own."""
    cache._client = None


async def test_an_unreachable_redis_reads_as_a_miss() -> None:
    """An unreachable Redis reads as a miss."""
    # The property every endpoint depends on. If this raised instead, the
    # service would stop working the moment Redis did - which is strictly
    # worse than having no cache at all.
    assert await cache.read_json("anything") is None


async def test_an_unreachable_redis_does_not_fail_a_write() -> None:
    """An unreachable Redis does not fail a write."""
    # Writes are best effort for the same reason. A request that succeeded
    # must not then fail while trying to remember its own answer.
    await cache.write_json("anything", {"a": 1}, ttl_seconds=60)
    await cache.delete("anything")


async def test_content_that_is_not_json_is_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Content that is not JSON is treated as absent."""

    # Something else wrote the key, or an older deploy wrote it in a different
    # shape. Falling back to the source is right; raising would take the
    # service down over a cache entry nobody owns.
    class Stub:
        """A Redis that returns something that is not JSON."""

        async def get(self, key: str) -> str:
            """Return a value that cannot be parsed."""
            return "{not json"

    monkeypatch.setattr(cache, "_client", Stub())

    assert await cache.read_json("k") is None


# An unreachable Redis is an operational condition the caller recovers from.
# A value that cannot be JSON-encoded is a bug in the calling code, and
# hiding it would mean the cache silently never worked - the write appears
# to succeed, every read misses, and the only symptom is that it is slow.
async def test_a_payload_that_cannot_be_serialised_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one failure that is *not* swallowed, and the reason matters."""

    class Stub:
        """A Redis that fails the test if anything reaches it."""

        async def set(self, key: str, value: str, ex: int) -> None:
            """Fail, because serialising should have raised first."""
            raise AssertionError("should not be reached")

    monkeypatch.setattr(cache, "_client", Stub())

    with pytest.raises(TypeError):
        await cache.write_json("k", {"bad": object()}, ttl_seconds=60)


async def test_the_client_is_built_once_per_process() -> None:
    """The client is built once per process."""
    # Connection pools are expensive and per-request clients leak them. Same
    # reasoning as the database engine being module level.
    assert cache.get_client() is cache.get_client()
