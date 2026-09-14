"""
What comes back: a Route, or a NoRoute saying why not.

WHY THIS EXISTS
    The return type is the single most important design decision in the
    engine, and it is a reaction to a specific bug.

WHAT THE 2021 VERSION DID
    Where:  database[works].py line 533, and lines 868 and 876 in
            GUI.Find_shortest_path
    How:    Unreachability was signalled with `infinity = 9999999`. The
            distance table was filled with it at line 536, and line 573
            compared against it to decide whether a path existed.
    Wrong:  The number escaped. Line 868 reads

                if Shortest.show_Shortest_path() == 9999999:

            and line 876 compares against it again — inside the user
            interface. A magic number invented by the search had become part
            of the contract between the algorithm and the window, and any
            code that forgot to check it would render 9999999 as a journey
            time.

            There was a method for this, if_path_unreachable at line 583, and
            it returns a string that line 569 calls and discards.

WHAT CHANGED AND WHY
    find_route returns Route | NoRoute. There is no sentinel, so there is no
    number to leak: a caller that ignores the distinction gets a type error
    from its own tooling rather than a plausible-looking journey time of two
    and a half months.

WHAT'S NEW
    Leg. The old result was a flat list of station names — Track_path, built
    by walking predecessors backwards at lines 562-571 — with no record of
    which line each hop was on, so it could not tell you where to change. A
    line on a map does not tell you that either; the leg list is the actual
    answer.

CONSTRAINT
    engine/ imports nothing web-related and nothing database-related.
"""

from dataclasses import dataclass

from .types import LineId, StationId


@dataclass(frozen=True)
class Leg:
    """An unbroken run on one line.

    Attributes:
        line: The line ridden.
        stations: Every station passed through, in order, including both ends.
            A leg of one hop has two entries.
        seconds: Time on this line. Excludes the change that follows it —
            interchange time belongs to the route total, not to either leg,
            because it is spent walking rather than travelling.
    """

    line: LineId
    stations: tuple[StationId, ...]
    seconds: int


@dataclass(frozen=True)
class Route:
    """A journey that exists.

    Attributes:
        legs: One per unbroken run on a line. Empty when origin equals
            destination, which is a real answer rather than an error.
        total_seconds: Riding plus changing. The sum of the legs alone would
            understate any journey involving a change, which is exactly the
            error a station-only graph makes.
        changes: How many times you change line. Always len(legs) - 1 for a
            non-empty route, and kept as a field because it is the thing
            callers actually want to show.
        step_free: True when every edge and interchange used is step-free.
            Reporting it is not the same as routing on it — routing on it is
            Phase 5.
    """

    legs: tuple[Leg, ...] = ()
    total_seconds: int = 0
    changes: int = 0
    step_free: bool = True


@dataclass(frozen=True)
class NoRoute:
    """No journey exists, and why.

    A reason rather than a bare failure, because the three cases want
    different words in front of a user: a station that does not exist is a
    different problem from two that are not connected.

    Attributes:
        reason: One of "unknown_origin", "unknown_destination",
            "disconnected".
    """

    reason: str


# Every reason NoRoute can carry, so a caller can exhaust them and a typo in
# one is a name error here rather than a string nobody matches.
UNKNOWN_ORIGIN = "unknown_origin"
UNKNOWN_DESTINATION = "unknown_destination"
DISCONNECTED = "disconnected"

REASONS: frozenset[str] = frozenset({UNKNOWN_ORIGIN, UNKNOWN_DESTINATION, DISCONNECTED})
