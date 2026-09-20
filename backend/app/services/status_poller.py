"""
The background task that keeps live line status current.

WHY THIS EXISTS
    A page load must not wait on someone else's server. TfL answers this
    endpoint in a few hundred milliseconds on a good day and not at all on a
    bad one, and putting that in the request path would make every visitor pay
    for it - so one task fetches on a timer and everything else reads Redis.

    It is also the only piece of this project that runs without a caller. That
    changes what "handle the error" means: there is no user watching it fail
    and no request to return a 500 to, so a failure that is not contained here
    is a failure nobody ever sees.

NO 2021 EQUIVALENT
    The old project fetched status on launch, wrote it into a SQLite column,
    and never refreshed it. "Live" meant "as of whenever you started the
    program" - so the status shown could be hours old, and there was nothing
    to poll with because the data had nowhere to go but the persistent store.

WHAT'S NEW
    Publishing on change rather than on every poll. Sixty polls an hour with a
    push each would wake every connected browser sixty times to tell it that
    nothing has happened, and a client that learns to ignore the channel is
    worse than no channel.
"""

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

from app.core import cache
from app.core.config import get_settings
from app.services.status import LineStatus, statuses_from_payload
from app.services.tfl import TfLClient, TfLError

# Where the current picture lives, and where a change is announced. Versioned
# like the network cache key, so a deploy that changes the shape below treats
# an older entry as absent rather than unpacking it wrongly.
#
# **v2 because the shape changed**: entries now carry affected_stops, and a v1
# entry has no such key. Read as v2 it looks like a line that is not running
# with nothing closed on it, which the router correctly treats as the whole
# line being shut - so a stale entry does not merely go unused, it silently
# reverts partial closures to whole-line avoidance.
#
# That is not hypothetical. A stray uvicorn left running from an unrelated
# test kept polling with the old code and overwriting v1 every sixty seconds,
# and the API alternated between correct and wrong answers depending on which
# poller wrote last. Versioning the key is what makes two versions of this
# service coexist without fighting, which is the whole reason the convention
# exists.
STATUS_KEY = "tube-router:status:v2"
STATUS_CHANNEL = "tube-router:status:v2"

# Comfortably longer than the poll interval, so the key only expires if the
# poller has actually stopped. An entry that outlives a dead poller is worse
# than no entry: the page would show a confident status from an hour ago.
STATUS_TTL_SECONDS = 300

# How long to wait after a failed poll before trying again. Shorter than the
# normal interval because a failure is usually transient, and long enough that
# a sustained TfL outage is not hammered.
RETRY_AFTER_SECONDS = 15.0


def to_payload(statuses: list[LineStatus]) -> dict[str, Any]:
    """The JSON shape stored in Redis and pushed over the WebSocket.

    Args:
        statuses: Output of statuses_from_payload.

    Returns:
        The lines and when they were fetched. `as_of` is what lets a client
        say "status from four minutes ago" rather than implying it is current,
        which matters precisely when the poller has stopped and nobody knows.
    """
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


async def poll_once(tfl: TfLClient) -> list[LineStatus] | None:
    """Fetch, parse and store one round of status.

    Args:
        tfl: An open client.

    Returns:
        The statuses, or None if TfL could not be reached or said nothing
        usable. None means "no news" - the previous entry in Redis is left
        alone rather than being replaced with an empty list, because an empty
        list would read as "every line is fine" to anything that saw it.
    """
    try:
        payload = await tfl.line_status()
    except (TimeoutError, TfLError, OSError):
        return None

    statuses = statuses_from_payload(payload)
    if not statuses:
        return None

    await cache.write_json(STATUS_KEY, to_payload(statuses), STATUS_TTL_SECONDS)
    return statuses


async def run(stop: asyncio.Event | None = None) -> None:
    """Poll until told to stop. Started from the application's lifespan.

    Args:
        stop: Set to end the loop. Tests pass one; the application relies on
            task cancellation instead.

    Every failure is contained. TfL being down, slow, or serving HTML must not
    end this task, because a task that dies takes live status with it and
    leaves no trace on the page - the status simply stops changing, which
    looks exactly like a quiet day on the Underground.
    """
    settings = get_settings()
    stop = stop or asyncio.Event()
    previous: list[LineStatus] | None = None

    # One client for the life of the task, not one per poll. Building it costs
    # about 150ms in SSL setup, which would otherwise be paid every minute for
    # nothing - and the request throttle is per-client state, so a fresh client
    # each time would quietly reset the spacing TfL's rate limit depends on.
    async with TfLClient(
        base_url=settings.tfl_base_url,
        app_key=settings.tfl_app_key,
        timeout_seconds=settings.tfl_timeout_seconds,
        max_attempts=settings.tfl_max_attempts,
        min_request_interval_seconds=settings.tfl_min_request_interval_seconds,
    ) as tfl:
        while not stop.is_set():
            delay = settings.tfl_status_poll_seconds
            try:
                statuses = await poll_once(tfl)

                if statuses is None:
                    delay = RETRY_AFTER_SECONDS
                elif statuses != previous:
                    # Only on a change. The comparison works because
                    # statuses_from_payload sorts by line code, so an unchanged
                    # network produces an equal list rather than a reordered one.
                    await cache.publish(STATUS_CHANNEL, to_payload(statuses))
                    previous = statuses

            except asyncio.CancelledError:
                # Shutdown. Re-raised so the task actually ends rather than
                # being swallowed by the catch-all below and looping forever.
                raise
            except Exception:
                # Deliberately broad, and the reason is the module docstring:
                # there is no caller to propagate to. Anything uncaught here
                # kills the task permanently and silently.
                delay = RETRY_AFTER_SECONDS

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)


async def current() -> dict[str, Any]:
    """The last known status, for GET /status and a new WebSocket client.

    Returns:
        The stored payload, or an empty one when the poller has not run yet or
        Redis is unreachable. Empty rather than an error: "I do not know yet"
        is a truthful answer to a well-formed question, and a client can render
        it as "status unavailable" instead of a failure.
    """
    stored = await cache.read_json(STATUS_KEY)
    if isinstance(stored, dict) and isinstance(stored.get("lines"), list):
        return stored
    return {"as_of": None, "lines": []}


async def not_running_lines() -> frozenset[str]:
    """Line codes with no trains on them, from the last known status.

    Returns:
        The lines a route must avoid. Empty when the poller has not run yet,
        when Redis is unreachable, or on a good day - and all three are the
        same answer on purpose. An unknown status must not remove lines from
        the network, because the failure that strands someone is refusing a
        journey that was perfectly possible.
    """
    return frozenset(
        code for code, stops in (await _suppressions()).items() if not stops
    )


async def closed_sections() -> dict[str, frozenset[str]]:
    """The shut stretch of each partly closed line, from the last known status.

    Returns:
        Line code to NaPTAN ids, for Network.without_closed_sections. Lines
        that are wholly shut are not here - they come back from
        not_running_lines instead, and the two sets never overlap.
    """
    return {code: stops for code, stops in (await _suppressions()).items() if stops}


async def _suppressions() -> dict[str, frozenset[str]]:
    """Every line with no trains, mapped to the stops that are shut.

    An empty set of stops means the whole line. Both callers above read this
    so the split between "all of it" and "part of it" is decided once.

    Empty overall when the poller has not run, when Redis is unreachable, or
    on a good day, and all three are the same answer on purpose: an unknown
    status must not remove lines from the network, because the failure that
    strands someone is refusing a journey that was perfectly possible.
    """
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
