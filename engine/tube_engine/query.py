"""What a caller asks for: an origin, a destination and an objective."""

from dataclasses import dataclass
from enum import Enum

from .types import LineId, StationId


# Only objectives that are implemented are members. One that raised
# NotImplementedError would advertise something that does not work, and a caller has no
# way to tell the two apart until it fails.
class Objective(Enum):
    """What the caller is optimising for."""

    FASTEST = "fastest"
    FEWEST_CHANGES = "fewest_changes"
    STEP_FREE = "step_free"


@dataclass(frozen=True)
class RouteQuery:
    """A journey to plan."""

    origin: StationId
    destination: StationId
    objective: Objective = Objective.FASTEST
    avoid_lines: frozenset[LineId] = frozenset()
