"""Turns TfL's live line status into something the router and the page can use."""

from dataclasses import dataclass
from typing import Any

# TfL's status severity is a 0-20 scale. These are the values that mean trains are not
# running, and they are the only ones that change a route.
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

# Severities that shut only part of a line. For these, TfL's affectedStops says which
# part, and the router suppresses that stretch instead of the whole line. The rest of
# NOT_RUNNING means the line is gone entirely.
PARTIAL = frozenset({3, 5, 11})

# What TfL reports when nothing is wrong, and what an absent status is treated as.
# Optimistic on purpose: the failure to avoid is removing a line from the network
# because a status lookup came back empty.
GOOD_SERVICE = 10


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

    # A Part Closure with a list of affected stops suppresses only that stretch. The
    # same severity with no stops has to be treated as the whole line: TfL said trains
    # are not running and declined to say where, and guessing "probably fine" would
    # route someone onto it.
    @property
    def closed_entirely(self) -> bool:
        """Whether the whole line is gone, rather than one stretch of it."""
        return not self.running and not (
            self.severity in PARTIAL and self.affected_stops
        )


# A line can carry several lineStatuses at once - part of it suspended while the rest
# runs normally. The worst one wins, because a route planner that took the cheerful half
# of a split status would send someone to a closed platform.
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


# Line codes, ready to pass to Network.without_lines(). Empty on a good day, which is
# most days.
def not_running(statuses: list[LineStatus]) -> frozenset[str]:
    """The lines a route must avoid because trains are not moving on them."""
    return frozenset(s.line_code for s in statuses if s.closed_entirely)


# Line code to NaPTAN ids, ready for Network.without_closed_sections. Only lines that
# are partly closed AND told us where appear here; everything else is either running or
# handled by not_running.
def closed_sections(statuses: list[LineStatus]) -> dict[str, frozenset[str]]:
    """The stretch of each partly closed line that has no trains on it."""
    return {
        s.line_code: s.affected_stops
        for s in statuses
        if not s.running and not s.closed_entirely
    }


# Empty is the safe answer at every step: a stop list we cannot read leaves the line
# wholly suppressed rather than partly, which is the error that refuses a journey rather
# than the one that sends someone to a shut platform.
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


# An unreadable or missing severity is treated as running. TfL can add a code at any
# time, and a number we do not recognise must not quietly delete a line from the network
# - the failure that would strand someone is the optimistic one being wrong, not the
# pessimistic one.
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
