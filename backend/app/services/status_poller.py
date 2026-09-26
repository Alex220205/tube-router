"""The background task that keeps live line status current."""

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

from app.core import cache
from app.core.config import get_settings
from app.services.status import LineStatus, statuses_from_payload
from app.services.tfl import TfLClient, TfLError

# Where the current picture lives, and where a change is announced. Versioned like the
# network cache key, so a deploy that changes the shape below treats an older entry as
# absent rather than unpacking it wrongly.
STATUS_KEY = "tube-router:status:v2"
STATUS_CHANNEL = "tube-router:status:v2"

# Comfortably longer than the poll interval, so the key only expires if the poller has
# actually stopped. An entry that outlives a dead poller is worse than no entry: the
# page would show a confident status from an hour ago.
STATUS_TTL_SECONDS = 300

# How long to wait after a failed poll before trying again. Shorter than the normal
# interval because a failure is usually transient, and long enough that a sustained TfL
# outage is not hammered.
RETRY_AFTER_SECONDS = 15.0


# The lines and when they were fetched. `as_of` is what lets a client say "status from
# four minutes ago" rather than implying it is current, which matters precisely when the
# poller has stopped and nobody knows.
def to_payload(statuses: list[LineStatus]) -> dict[str, Any]:
    """The JSON shape stored in Redis and pushed over the WebSocket."""
    return {
        "as_of": datetime.now(UTC).isoformat(),
        "lines": [
            {
                "line_code": s.line_code,
                "severity": s.severity,
                "description": s.description,
                "reason": s.reason,
                "running": s.running,
                "affected_stops": sorted(s.affected_stops),
            }
            for s in statuses
        ],
    }


# The statuses, or None if TfL could not be reached or said nothing usable. None means
# "no news" - the previous entry in Redis is left alone rather than being replaced with
# an empty list, because an empty list would read as "every line is fine" to anything
# that saw it.
async def poll_once(tfl: TfLClient) -> list[LineStatus] | None:
    """Fetch, parse and store one round of status."""
    try:
        payload = await tfl.line_status()
    except (TimeoutError, TfLError, OSError):
        return None

    statuses = statuses_from_payload(payload)
    if not statuses:
        return None

    await cache.write_json(STATUS_KEY, to_payload(statuses), STATUS_TTL_SECONDS)
    return statuses


# Returns how long to wait before the next poll, and what to compare the next result
# against. Both come back together because a failed poll must not overwrite the last
# good statuses.
async def _poll_and_publish(
    tfl: TfLClient,
    previous: list[LineStatus] | None,
    poll_seconds: float,
) -> tuple[float, list[LineStatus] | None]:
    """One turn of the poll loop: fetch, publish on a change, say when to return."""
    try:
        statuses = await poll_once(tfl)

        if statuses is None:
            return RETRY_AFTER_SECONDS, previous
        if statuses != previous:
            # Only on a change. The comparison works because statuses_from_payload sorts
            # by line code, so an unchanged network produces an equal list rather than a
            # reordered one.
            await cache.publish(STATUS_CHANNEL, to_payload(statuses))
            return poll_seconds, statuses
        return poll_seconds, previous

    except asyncio.CancelledError:
        # Shutdown. Re-raised so the task actually ends rather than being swallowed by
        # the catch-all below and looping forever.
        raise
    except Exception:
        # Deliberately broad: this runs in a background task with no caller to propagate
        # to, so anything uncaught here kills it permanently and silently.
        return RETRY_AFTER_SECONDS, previous


# Every failure is contained. TfL being down, slow, or serving HTML must not end this
# task, because a task that dies takes live status with it and leaves no trace on the
# page - the status simply stops changing, which looks exactly like a quiet day on the
# Underground.
async def run(stop: asyncio.Event | None = None) -> None:
    """Poll until told to stop. Started from the application's lifespan."""
    settings = get_settings()
    stop = stop or asyncio.Event()
    previous: list[LineStatus] | None = None

    # One client for the life of the task, not one per poll. Building it costs about
    # 150ms in SSL setup, which would otherwise be paid every minute for nothing - and
    # the request throttle is per-client state, so a fresh client each time would
    # quietly reset the spacing TfL's rate limit depends on.
    async with TfLClient(
        base_url=settings.tfl_base_url,
        app_key=settings.tfl_app_key,
        timeout_seconds=settings.tfl_timeout_seconds,
        max_attempts=settings.tfl_max_attempts,
        min_request_interval_seconds=settings.tfl_min_request_interval_seconds,
    ) as tfl:
        while not stop.is_set():
            delay, previous = await _poll_and_publish(
                tfl, previous, settings.tfl_status_poll_seconds
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)


# The stored payload, or an empty one when the poller has not run yet or Redis is
# unreachable. Empty rather than an error: "I do not know yet" is a truthful answer to a
# well-formed question, and a client can render it as "status unavailable" instead of a
# failure.
async def current() -> dict[str, Any]:
    """The last known status, for GET /status and a new WebSocket client."""
    stored = await cache.read_json(STATUS_KEY)
    if isinstance(stored, dict) and isinstance(stored.get("lines"), list):
        return stored
    return {"as_of": None, "lines": []}


# The lines a route must avoid. Empty when the poller has not run yet, when Redis is
# unreachable, or on a good day - and all three are the same answer on purpose. An
# unknown status must not remove lines from the network, because the failure that
# strands someone is refusing a journey that was perfectly possible.
async def not_running_lines() -> frozenset[str]:
    """Line codes with no trains on them, from the last known status."""
    return frozenset(
        code for code, stops in (await _suppressions()).items() if not stops
    )


# Line code to NaPTAN ids, for Network.without_closed_sections. Lines that are wholly
# shut are not here - they come back from not_running_lines instead, and the two sets
# never overlap.
async def closed_sections() -> dict[str, frozenset[str]]:
    """The shut stretch of each partly closed line, from the last known status."""
    return {code: stops for code, stops in (await _suppressions()).items() if stops}


# An empty set of stops means the whole line. Both callers above read this so the split
# between "all of it" and "part of it" is decided once.
async def _suppressions() -> dict[str, frozenset[str]]:
    """Every line with no trains, mapped to the stops that are shut."""
    stored = await current()
    lines = stored.get("lines")
    if not isinstance(lines, list):
        return {}

    out: dict[str, frozenset[str]] = {}
    for line in lines:
        if not isinstance(line, dict) or line.get("running") is not False:
            continue
        code = line.get("line_code")
        if not isinstance(code, str):
            continue
        stops = line.get("affected_stops")
        out[code] = (
            frozenset(s for s in stops if isinstance(s, str))
            if isinstance(stops, list)
            else frozenset()
        )
    return out
