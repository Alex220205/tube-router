"""
Turns TfL's live line status into something the router and the page can use.

WHY THIS EXISTS
    Pure transforms, in the shape services/seed.py already uses: a payload in,
    frozen dataclasses out, no network and no database. That is what lets the
    awkward part of this phase - deciding which severities mean "do not route
    through here" - be tested against a captured fixture in milliseconds.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, Line.AddLinedatabase and Line.DeleteLinedatabase
    How:    lines.service_status was a TEXT column holding values like
            "Good Service" and "Severe Delays". On launch the application
            deleted every row in the table and reinserted it.
    Wrong:  A cache wearing a table's clothing. Live data with a lifetime of
            minutes was being written to the persistent store, and the store
            was being emptied on every start to keep it current - which is
            both the slowest way to cache something and the one that loses
            your real data if it half-fails.

WHAT CHANGED AND WHY
    Phase 1 dropped the column on purpose and docs/DECISIONS.md recorded that
    live status "arrives in Redis in Phase 7". This is where it went instead:
    polled into Redis with a TTL, never into Postgres.

WHAT'S NEW
    A stated policy on what a disruption means for routing. The old code
    displayed the string and did nothing else with it - status and the router
    never met, so a suspended line was something you read about after being
    routed down it.
"""

from dataclasses import dataclass
from typing import Any

# TfL's status severity is a 0-20 scale. These are the values that mean trains
# are not running, and they are the only ones that change a route.
#
# Everything above is a delay: real, worth showing on the page, and not a
# reason to silently rewrite someone's journey. Severe Delays often clears in
# twenty minutes, and rerouting a user around a line that is still running -
# without being asked - gives them a worse journey for a condition that may
# have gone by the time they reach the platform.
# Taken from /Line/Meta/Severity rather than from memory. The first version
# of this set was written from the values that had been seen in the wild, and
# it missed 11 and 16 entirely - a line reporting either would have been
# treated as running normally.
NOT_RUNNING = frozenset(
    {
        1,  # Closed
        2,  # Suspended
        3,  # Part Suspended
        4,  # Planned Closure
        5,  # Part Closure
        11,  # Part Closed
        16,  # Not Running
        20,  # Service Closed
    }
)

# Severities that shut only part of a line. For these, TfL's affectedStops
# says which part, and the router suppresses that stretch instead of the whole
# line. The rest of NOT_RUNNING means the line is gone entirely.
PARTIAL = frozenset({3, 5, 11})

# What TfL reports when nothing is wrong, and what an absent status is treated
# as. Optimistic on purpose: the failure to avoid is removing a line from the
# network because a status lookup came back empty.
GOOD_SERVICE = 10


# line_code: TfL's line id - "piccadilly". The same identifier the
#     engine uses for LineId, so no translation is needed anywhere.
# severity: TfL's 0-20 scale, kept as the number rather than a boolean.
#     A client may want to colour Minor Delays differently from Severe
#     Delays, and collapsing it here would throw that away for good.
# description: TfL's own words - "Severe Delays".
# reason: The sentence a user reads, where there is one. None on a line
#     with nothing wrong.
# affected_stops: NaPTAN ids of the stations a partial closure covers,
#     from TfL's affectedStops. Empty on a healthy line, and empty on a
#     whole-line closure too - there is no "part" to name when the whole
#     thing is shut, which is why `closed_entirely` tests both.
@dataclass(frozen=True)
class LineStatus:
    """What TfL currently says about one line."""

    line_code: str
    severity: int
    description: str
    reason: str | None
    affected_stops: frozenset[str] = frozenset()

    @property
    def running(self) -> bool:
        """Whether trains are moving on this line at all."""
        return self.severity not in NOT_RUNNING

    # A Part Closure with a list of affected stops suppresses only that
    # stretch. The same severity with no stops has to be treated as the
    # whole line: TfL said trains are not running and declined to say
    # where, and guessing "probably fine" would route someone onto it.
    @property
    def closed_entirely(self) -> bool:
        """Whether the whole line is gone, rather than one stretch of it."""
        return not self.running and not (
            self.severity in PARTIAL and self.affected_stops
        )


# A line can carry several lineStatuses at once - part of it suspended while
# the rest runs normally. The worst one wins, because a route planner that
# took the cheerful half of a split status would send someone to a closed
# platform.
#
# payload: The decoded JSON array. Anything unexpected is skipped rather
#     than raised on: this runs in a background poller, and one malformed
#     line must not cost us the other ten.
#
# One entry per line that could be read, ordered by line code so a
# re-poll produces a comparable list and "has anything changed" is a
# simple equality check.
def statuses_from_payload(payload: Any) -> list[LineStatus]:
    """Read /Line/Mode/tube/Status into one LineStatus per line."""
    if not isinstance(payload, list):
        return []

    statuses: list[LineStatus] = []
    for line in payload:
        if not isinstance(line, dict):
            continue
        code = line.get("id")
        if not isinstance(code, str) or not code:
            continue

        entries = [s for s in line.get("lineStatuses") or [] if isinstance(s, dict)]
        if not entries:
            continue

        # Lowest severity number is the most serious, on TfL's scale.
        worst = min(entries, key=lambda s: _severity(s))
        statuses.append(
            LineStatus(
                line_code=code,
                severity=_severity(worst),
                description=str(
                    worst.get("statusSeverityDescription") or "Unknown"
                ).strip(),
                reason=_reason(worst),
                affected_stops=_affected_stops(worst),
            )
        )

    return sorted(statuses, key=lambda s: s.line_code)


# Line codes, ready to pass to Network.without_lines(). Empty on a good
# day, which is most days.
def not_running(statuses: list[LineStatus]) -> frozenset[str]:
    """The lines a route must avoid because trains are not moving on them."""
    return frozenset(s.line_code for s in statuses if s.closed_entirely)


# Line code to NaPTAN ids, ready for Network.without_closed_sections.
# Only lines that are partly closed AND told us where appear here;
# everything else is either running or handled by not_running.
def closed_sections(statuses: list[LineStatus]) -> dict[str, frozenset[str]]:
    """The stretch of each partly closed line that has no trains on it."""
    return {
        s.line_code: s.affected_stops
        for s in statuses
        if not s.running and not s.closed_entirely
    }


# Empty is the safe answer at every step: a stop list we cannot read leaves
# the line wholly suppressed rather than partly, which is the error that
# refuses a journey rather than the one that sends someone to a shut
# platform.
def _affected_stops(entry: dict[str, Any]) -> frozenset[str]:
    """NaPTAN ids from disruption.affectedStops, or empty if TfL said nothing."""
    disruption = entry.get("disruption")
    if not isinstance(disruption, dict):
        return frozenset()

    stops = disruption.get("affectedStops")
    if not isinstance(stops, list):
        return frozenset()

    return frozenset(
        stop["naptanId"]
        for stop in stops
        if isinstance(stop, dict) and isinstance(stop.get("naptanId"), str)
    )


# An unreadable or missing severity is treated as running. TfL can add a
# code at any time, and a number we do not recognise must not quietly delete
# a line from the network - the failure that would strand someone is the
# optimistic one being wrong, not the pessimistic one.
def _severity(entry: dict[str, Any]) -> int:
    """TfL's severity number, defaulting to Good Service."""
    value = entry.get("statusSeverity")
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return GOOD_SERVICE
    try:
        return int(value)
    except (TypeError, ValueError):
        return GOOD_SERVICE


def _reason(entry: dict[str, Any]) -> str | None:
    """The human sentence, tidied. None when there is nothing to say."""
    raw = entry.get("reason")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text or None
