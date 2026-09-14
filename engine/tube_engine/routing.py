"""
The search. Dijkstra over (station, line) pairs, with a real priority queue.

WHY THIS EXISTS
    This is the file the whole project is an argument about. Everything else
    exists so that this can be pure, fast and tested.

WHAT THE 2021 VERSION DID
    Where:  database[works].py lines 530-585, Traversal.shortest_path
    How:    Line 530 announced "dijkstras algorithm which uses priortiy queue
            data structure". Lines 540-546 then scan every remaining node
            linearly to find the minimum, with no queue of any kind. Line 532
            set `unseenNodes = self.graph`, line 557 popped from it, and line
            533 used `infinity = 9999999` as the unreachable marker.
    Wrong:  Four things.
            1. The comment at 530 was false. There is no heap; the scan at
               540-546 is O(V) per step, making the search O(V^2).
            2. Line 532 aliased the graph rather than copying it, so the pop
               at 557 emptied `self.graph`. Every search destroyed the graph
               it was searching.
            3. The nodes were stations, so a node did not know which line you
               arrived on. Changing line was free and uncounted, and "fewest
               changes" was unanswerable.
            4. The 9999999 sentinel escaped into the interface, compared at
               lines 868 and 876 to decide what to draw.

WHAT CHANGED AND WHY
    heapq, so the next node is popped in log time rather than found by
    scanning — which makes the comment at line 530 true for the first time.

    Nodes are (station, line) pairs, so a change is an edge with a cost. That
    is what fixes (3), and it is what Phase 5 builds fewest-changes on without
    rewriting anything here.

    Nothing is mutated except this function's own locals. The Network is
    read-only throughout, which fixes (2) by construction.

    Route | NoRoute replaces the sentinel, fixing (4).

WHAT'S NEW
    Leg reconstruction. The old code walked predecessors backwards into a flat
    list of names at lines 562-571 and had no way to say where you change,
    because a station node does not record the line you were on.

CONSTRAINT
    engine/ imports nothing web-related and nothing database-related.
    Enforced by tests/test_imports.py.
"""

import heapq

from .network import Network
from .query import Objective, RouteQuery
from .result import (
    DISCONNECTED,
    UNKNOWN_DESTINATION,
    UNKNOWN_ORIGIN,
    Leg,
    NoRoute,
    Route,
)
from .types import Edge, Interchange, LineId, StationId

# A node in the search graph: standing at a station, on a particular line.
Node = tuple[StationId, LineId]

# How a node was reached: the node before it, and whether the step was a ride
# or a change. The flag is what lets legs be split without re-deriving it.
Arrival = tuple[Node, bool]


def find_route(network: Network, query: RouteQuery) -> Route | NoRoute:
    """Find the best route between two stations.

    Args:
        network: The graph to search. Not modified — the search keeps its own
            distance and predecessor tables and never writes to the network.
        query: Origin, destination and objective.

    Returns:
        A Route, or a NoRoute carrying the reason. Never a sentinel value:
        there is no number here that could be mistaken for a journey time.
    """
    if query.origin not in network:
        return NoRoute(UNKNOWN_ORIGIN)
    if query.destination not in network:
        return NoRoute(UNKNOWN_DESTINATION)

    # Standing where you wanted to be. An empty Route rather than an error,
    # for the same reason an empty station search is a 200 and not a 404: it
    # is a correct answer to a reasonable question.
    if query.origin == query.destination:
        return Route()

    if query.objective is not Objective.FASTEST:  # pragma: no cover
        # Unreachable while Objective has one member. Kept so that adding
        # FEWEST_CHANGES in Phase 5 fails loudly here rather than silently
        # returning the fastest route under a different name.
        raise NotImplementedError(f"objective {query.objective} arrives in Phase 5")

    came_from = _search(network, query.origin, query.destination)
    if came_from is None:
        return NoRoute(DISCONNECTED)

    return _build_route(network, query.origin, came_from)


def _search(
    network: Network, origin: StationId, destination: StationId
) -> tuple[dict[Node, Arrival], Node] | None:
    """Dijkstra from every line at the origin to the first line at the target.

    Args:
        network: The graph. Read only.
        origin: Where to start.
        destination: Where to stop.

    Returns:
        The predecessor table and the node the search finished on, or None if
        the destination cannot be reached.
    """
    # Standing at the origin you are not yet on any line, so every line
    # serving it is a valid starting node at zero cost. This avoids inventing
    # a virtual "on no line" node and the special cases that would come with
    # it.
    starts = network.lines_at(origin)
    if not starts:
        return None

    best: dict[Node, int] = {}
    came_from: dict[Node, Arrival] = {}

    # (cost, station, line) rather than (cost, node). Tuples compare element
    # by element, and on a tie heapq would otherwise try to order the node
    # tuples themselves — which works but makes the ordering depend on station
    # ids. Naming the fields keeps ties deterministic and the intent visible.
    heap: list[tuple[int, StationId, LineId]] = []
    for line in sorted(starts):
        best[(origin, line)] = 0
        heapq.heappush(heap, (0, origin, line))

    while heap:
        cost, station_id, line = heapq.heappop(heap)
        node: Node = (station_id, line)

        # heapq has no decrease-key, so a node can be pushed more than once
        # with different costs. The first pop is the cheapest; later ones are
        # stale and skipping them is what keeps this O(E log V).
        if cost > best.get(node, cost):
            continue

        if station_id == destination:
            return came_from, node

        # Riding one stop stays on the same line.
        for edge in network.edges_from(station_id):
            if edge.line != line:
                continue
            _relax(
                heap,
                best,
                came_from,
                node,
                (edge.destination, line),
                cost + edge.seconds,
                False,
            )

        # Changing line stays at the same station and costs walking time.
        for interchange in network.interchanges_at(station_id):
            if interchange.from_line != line:
                continue
            _relax(
                heap,
                best,
                came_from,
                node,
                (station_id, interchange.to_line),
                cost + interchange.seconds,
                True,
            )

    return None


def _relax(
    heap: list[tuple[int, StationId, LineId]],
    best: dict[Node, int],
    came_from: dict[Node, Arrival],
    current: Node,
    neighbour: Node,
    cost: int,
    is_change: bool,
) -> None:
    """Record a cheaper way to reach a neighbour, if this is one."""
    if cost >= best.get(neighbour, cost + 1):
        return
    best[neighbour] = cost
    came_from[neighbour] = (current, is_change)
    heapq.heappush(heap, (cost, neighbour[0], neighbour[1]))


def _build_route(
    network: Network, origin: StationId, finished: tuple[dict[Node, Arrival], Node]
) -> Route:
    """Turn the predecessor table into legs, a total and a change count.

    Args:
        network: The graph, for looking edges back up.
        origin: Where the journey started.
        finished: The predecessor table and the node the search ended on.

    Returns:
        The assembled Route.
    """
    came_from, node = finished

    # Walk back to the start, collecting each step and whether it was a
    # change. Reversed at the end rather than inserting at the front, which
    # the 2021 code did at line 564 — O(n^2) on a list, though at tube scale
    # that was never the problem with it.
    steps: list[tuple[Node, Node, bool]] = []
    while node in came_from:
        previous, was_change = came_from[node]
        steps.append((previous, node, was_change))
        node = previous
    steps.reverse()

    legs: list[Leg] = []
    stations: list[StationId] = [origin]
    line: LineId | None = None
    leg_seconds = 0
    total_seconds = 0
    step_free = True

    for (from_station, from_line), (to_station, to_line), was_change in steps:
        if was_change:
            # The change happens where we are standing, so the leg that was
            # in progress ends here.
            interchange = _find_interchange(network, from_station, from_line, to_line)
            total_seconds += interchange.seconds
            step_free = step_free and interchange.step_free
            # Only close a leg that actually went somewhere. Changing line at
            # the origin without riding first cannot be optimal — every line
            # at the origin is already seeded at zero — but a leg of one
            # station and no seconds would be nonsense if it ever happened,
            # and silently emitting one is how a route grows a phantom hop.
            if len(stations) > 1:
                legs.append(
                    Leg(line=from_line, stations=tuple(stations), seconds=leg_seconds)
                )
            stations = [to_station]
            leg_seconds = 0
            line = to_line
            continue

        edge = _find_edge(network, from_station, to_station, from_line)
        total_seconds += edge.seconds
        leg_seconds += edge.seconds
        step_free = step_free and edge.step_free
        stations.append(to_station)
        line = from_line

    if line is not None:
        legs.append(Leg(line=line, stations=tuple(stations), seconds=leg_seconds))

    return Route(
        legs=tuple(legs),
        total_seconds=total_seconds,
        # A journey with two legs involved one change. Derived rather than
        # counted separately, so the two can never disagree.
        changes=max(len(legs) - 1, 0),
        step_free=step_free,
    )


def _find_edge(
    network: Network, origin: StationId, destination: StationId, line: LineId
) -> Edge:
    """The edge the search used for one hop.

    Raises:
        LookupError: If no such edge exists, which would mean the predecessor
            table disagrees with the graph — a bug in this file rather than
            bad input.
    """
    for edge in network.edges_from(origin):
        if edge.destination == destination and edge.line == line:
            return edge
    raise LookupError(f"no {line} edge from {origin} to {destination}")


def _find_interchange(
    network: Network, station_id: StationId, from_line: LineId, to_line: LineId
) -> Interchange:
    """The interchange the search used for one change.

    Raises:
        LookupError: As above — an inconsistency between the search and the
            graph, not a missing route.
    """
    for interchange in network.interchanges_at(station_id):
        if interchange.from_line == from_line and interchange.to_line == to_line:
            return interchange
    raise LookupError(f"no interchange at {station_id} from {from_line} to {to_line}")
