"""
What a caller asks for: an origin, a destination and an objective.

WHY THIS EXISTS
    One object rather than a widening list of arguments. find_route takes a
    network and a query, so Phase 5 added "avoid these lines" by changing this
    file rather than every call site — which is exactly the cost the shape was
    chosen to avoid.

WHAT THE 2021 VERSION DID
    Where:  database[works].py lines 460-470, Traversal.__init__
    How:    Start_station and End_station were attributes set on the object
            that also held the graph, the distance table and the result. One
            object was the question, the working memory and the answer.
    Wrong:  Because the question and the working memory shared an object, a
            second search reused the first one's state — and since line 532
            aliased the graph and line 557 emptied it, the second search had
            nothing left to traverse.

WHAT CHANGED AND WHY
    A query is a frozen value. It carries no state, is safe to reuse, and can
    be compared — which is what lets the regression test in test_routing.py
    run the same query twice and assert both answers match.

WHAT'S NEW
    Objective. The old code had one behaviour and no name for it.

CONSTRAINT
    engine/ imports nothing web-related and nothing database-related.
"""

from dataclasses import dataclass
from enum import Enum

from .types import LineId, StationId


class Objective(Enum):
    """What the caller is optimising for.

    Each member arrived in the phase that implemented it. Shipping one that
    raised NotImplementedError would advertise something that does not work,
    and a caller has no way to tell the two apart until it fails.

    STEP_FREE is not a third algorithm. It is the fastest search run against
    Network.step_free_only(), because three copies of Dijkstra would be three
    places for the same bug to be fixed separately.
    """

    FASTEST = "fastest"
    FEWEST_CHANGES = "fewest_changes"
    STEP_FREE = "step_free"


@dataclass(frozen=True)
class RouteQuery:
    """A journey to plan.

    Attributes:
        origin: Where the journey starts.
        destination: Where it ends. May equal origin, which is answered with
            an empty Route rather than an error.
        objective: What to optimise for.
        avoid_lines: Lines the route may not use. Honoured by
            Network.without_lines(), which is why the field arrives in the
            same phase as that method rather than earlier — a field that looks
            configurable and is silently ignored is a mistake this project
            already made once with LOG_LEVEL and recorded in
            docs/DECISIONS.md.

            A frozenset rather than a set so the query stays hashable, which
            is what lets Phase 6 use it as a cache key.
    """

    origin: StationId
    destination: StationId
    objective: Objective = Objective.FASTEST
    avoid_lines: frozenset[LineId] = frozenset()
