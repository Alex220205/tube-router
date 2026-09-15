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
NOT_RUNNING = frozenset(
    {
        1,  # Closed
        2,  # Suspended
        3,  # Part Suspended
        4,  # Planned Closure
        5,  # Part Closure
        20,  # Service Closed
    }
)

# What TfL reports when nothing is wrong, and what an absent status is treated
# as. Optimistic on purpose: the failure to avoid is removing a line from the
# network because a status lookup came back empty.
GOOD_SERVICE = 10


@dataclass(frozen=True)
class LineStatus:
    """What TfL currently says about one line.

    Attributes:
        line_code: TfL's line id - "piccadilly". The same identifier the
            engine uses for LineId, so no translation is needed anywhere.
        severity: TfL's 0-20 scale, kept as the number rather than a boolean.
            A client may want to colour Minor Delays differently from Severe
            Delays, and collapsing it here would throw that away for good.
        description: TfL's own words - "Severe Delays".
        reason: The sentence a user reads, where there is one. None on a line
            with nothing wrong.
    """

    line_code: str
    severity: int
    description: str
    reason: str | None

    @property
    def running(self) -> bool:
        """Whether trains are moving on this line at all."""
        return self.severity not in NOT_RUNNING


def statuses_from_payload(payload: Any) -> list[LineStatus]:
    """Read /Line/Mode/tube/Status into one LineStatus per line.

    A line can carry several lineStatuses at once - part of it suspended while
    the rest runs normally. The worst one wins, because a route planner that
    took the cheerful half of a split status would send someone to a closed
    platform.

    Args:
        payload: The decoded JSON array. Anything unexpected is skipped rather
            than raised on: this runs in a background poller, and one malformed
            line must not cost us the other ten.

    Returns:
        One entry per line that could be read, ordered by line code so a
        re-poll produces a comparable list and "has anything changed" is a
        simple equality check.
    """
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
            )
        )

    return sorted(statuses, key=lambda s: s.line_code)


def not_running(statuses: list[LineStatus]) -> frozenset[str]:
    """The lines a route must avoid because trains are not moving on them.

    Args:
        statuses: Output of statuses_from_payload.

    Returns:
        Line codes, ready to pass to Network.without_lines(). Empty on a good
        day, which is most days.
    """
    return frozenset(s.line_code for s in statuses if not s.running)


def _severity(entry: dict[str, Any]) -> int:
    """TfL's severity number, defaulting to Good Service.

    An unreadable or missing severity is treated as running. TfL can add a
    code at any time, and a number we do not recognise must not quietly delete
    a line from the network - the failure that would strand someone is the
    optimistic one being wrong, not the pessimistic one.
    """
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
