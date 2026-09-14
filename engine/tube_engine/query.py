"""
What a caller asks for: an origin, a destination and an objective.

WHY THIS EXISTS
    One object rather than a widening list of arguments. find_route takes a
    network and a query, and adding "avoid these lines" in Phase 5 changes
    this file rather than every call site.

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

from .types import StationId


class Objective(Enum):
    """What the caller is optimising for.

    Only FASTEST exists in Phase 4. FEWEST_CHANGES and STEP_FREE arrive in
    Phase 5 with the code that implements them.

    Shipping a member that raises NotImplementedError would be advertising
    something that does not work, and a caller has no way to tell the two
    apart until it fails. Adding an enum member later is additive and breaks
    nothing; removing one is not.
    """

    FASTEST = "fastest"


@dataclass(frozen=True)
class RouteQuery:
    """A journey to plan.

    There is deliberately no `avoid_lines` field yet. It arrives in Phase 5
    together with Network.without_lines(), which is what would honour it — a
    field that looks configurable and is silently ignored is a mistake this
    project already made once with LOG_LEVEL and recorded in
    docs/DECISIONS.md.

    Attributes:
        origin: Where the journey starts.
        destination: Where it ends. May equal origin, which is answered with
            an empty Route rather than an error.
        objective: What to optimise for.
    """

    origin: StationId
    destination: StationId
    objective: Objective = Objective.FASTEST
