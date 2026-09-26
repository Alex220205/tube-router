"""What comes back: a Route, or a NoRoute saying why not."""

from dataclasses import dataclass

from .types import LineId, StationId


@dataclass(frozen=True)
class Leg:
    """An unbroken run on one line."""

    line: LineId
    stations: tuple[StationId, ...]
    seconds: int


@dataclass(frozen=True)
class Route:
    """A journey that exists."""

    legs: tuple[Leg, ...] = ()
    total_seconds: int = 0
    changes: int = 0
    step_free: bool = True


# A reason rather than a bare failure, because the three cases want different words in
# front of a user: a station that does not exist is a different problem from two that
# are not connected.
@dataclass(frozen=True)
class NoRoute:
    """No journey exists, and why."""

    reason: str


# Every reason NoRoute can carry, so a caller can exhaust them and a typo in one is a
# name error here rather than a string nobody matches.
UNKNOWN_ORIGIN = "unknown_origin"
UNKNOWN_DESTINATION = "unknown_destination"
DISCONNECTED = "disconnected"

REASONS: frozenset[str] = frozenset({UNKNOWN_ORIGIN, UNKNOWN_DESTINATION, DISCONNECTED})
