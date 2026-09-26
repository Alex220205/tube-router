"""The search."""

import heapq
from collections.abc import Callable
from dataclasses import dataclass

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

# How a node was reached: the node before it, and whether the step was a ride or a
# change. The flag is what lets legs be split without re-deriving it.
Arrival = tuple[Node, bool]

# What the search minimises. A tuple rather than an int so that one traversal serves
# every objective: heapq compares element by element, so (1, 900) beats (2, 400) and (1,
# 400) beats (1, 900). That ordering is the entire implementation of both "fewest
# changes, ties broken on time" and its mirror.
Cost = tuple[int, ...]


@dataclass(frozen=True)
class _CostModel:
    """How an objective measures a journey."""

    start: Cost
    advance: Callable[[Cost, int, bool], Cost]


# The second element is a tie-break, not a preference: it only ever decides between
# routes of identical duration.
def _by_time(cost: Cost, seconds: int, is_change: bool) -> Cost:
    """Minimise journey time, then changes."""
    return (cost[0] + seconds, cost[1] + int(is_change))


# Both components only ever increase, which is what keeps this valid Dijkstra: the
# algorithm needs a cost that never decreases as a path grows, or the first pop of a
# node stops being its true optimum. A component that could decrease would break the
# search silently, returning plausible wrong routes rather than raising.
def _by_changes(cost: Cost, seconds: int, is_change: bool) -> Cost:
    """Minimise changes first, then time."""
    return (cost[0] + int(is_change), cost[1] + seconds)


# STEP_FREE is deliberately the same model as FASTEST. It is not a third algorithm - it
# is this search run against Network.step_free_only(), which is why adding it cost a
# dictionary entry rather than a function.
_COST_MODELS: dict[Objective, _CostModel] = {
    Objective.FASTEST: _CostModel(start=(0, 0), advance=_by_time),
    Objective.STEP_FREE: _CostModel(start=(0, 0), advance=_by_time),
    Objective.FEWEST_CHANGES: _CostModel(start=(0, 0), advance=_by_changes),
}


# A Route, or a NoRoute carrying the reason. Never a sentinel value: there is no number
# here that could be mistaken for a journey time.
def find_route(network: Network, query: RouteQuery) -> Route | NoRoute:
    """Find the best route between two stations."""
    if query.origin not in network:
        return NoRoute(UNKNOWN_ORIGIN)
    if query.destination not in network:
        return NoRoute(UNKNOWN_DESTINATION)

    # Standing where you wanted to be. An empty Route rather than an error, for the same
    # reason an empty station search is a 200 and not a 404: it is a correct answer to a
    # reasonable question.
    if query.origin == query.destination:
        return Route()

    model = _COST_MODELS.get(query.objective)
    if model is None:  # pragma: no cover
        # Unreachable while every Objective member has a model. Kept so that a fourth
        # objective fails loudly here rather than silently returning the fastest route
        # under a different name.
        raise NotImplementedError(f"no cost model for {query.objective}")

    searchable = network.without_lines(query.avoid_lines)
    step_free = query.objective is Objective.STEP_FREE
    if step_free:
        searchable = searchable.step_free_only()

    # A step-free journey has to begin on a platform you can reach and end on one you
    # can leave. The changes between are already filtered out of the graph; these two
    # ends are the part only the search knows about, because only it knows which
    # platform you arrive on.
    if step_free:
        starts = searchable.step_free_lines_at(query.origin)

        def accept(station_id: StationId, line: LineId) -> bool:
            """Arrival counts only on a step-free platform at the destination."""
            return station_id == query.destination and searchable.step_free_at(
                station_id, line
            )
    else:
        starts = searchable.lines_at(query.origin)

        def accept(station_id: StationId, line: LineId) -> bool:
            """Arrival counts on any platform at the destination."""
            return station_id == query.destination

    found = _search(searchable, query.origin, starts, accept, model)
    if found is None:
        return NoRoute(DISCONNECTED)

    # The filtered network, not the original: _build_route looks edges back up to price
    # them, and it must see the same graph the search walked.
    return _build_route(searchable, query.origin, found)


# One traversal for every objective. Only three things differ: where it may begin, what
# counts as arriving, and how a journey is measured. "Fewest changes" is not a different
# way of walking the graph - it is the same walk measured differently, and step-free is
# the same walk begun and ended in fewer places.
def _search(
    network: Network,
    origin: StationId,
    starts: frozenset[LineId],
    accept: Callable[[StationId, LineId], bool],
    model: _CostModel,
) -> tuple[dict[Node, Arrival], Node] | None:
    """Dijkstra from a set of starting platforms to the first accepted one."""
    if not starts:
        return None

    best: dict[Node, Cost] = {}
    came_from: dict[Node, Arrival] = {}

    # (cost, station, line) rather than (cost, node). Tuples compare element by element,
    # and on a tie heapq would otherwise try to order the node tuples themselves - which
    # works but makes the ordering depend on station ids. Naming the fields keeps ties
    # deterministic and the intent visible.
    heap: list[tuple[Cost, StationId, LineId]] = []
    for line in sorted(starts):
        best[(origin, line)] = model.start
        heapq.heappush(heap, (model.start, origin, line))

    while heap:
        cost, station_id, line = heapq.heappop(heap)
        node: Node = (station_id, line)

        # heapq has no decrease-key, so a node can be pushed more than once with
        # different costs. The first pop is the cheapest; later ones are stale and
        # skipping them is what keeps this O(E log V).
        if cost > best.get(node, cost):
            continue

        if accept(station_id, line):
            return came_from, node

        _expand(network, heap, best, came_from, node, cost, model)

    return None


# The two ways to leave a node, which is the whole of what a journey can do: ride one
# stop on the line you are on, or change line where you stand.
def _expand(
    network: Network,
    heap: list[tuple[Cost, StationId, LineId]],
    best: dict[Node, Cost],
    came_from: dict[Node, Arrival],
    node: Node,
    cost: Cost,
    model: _CostModel,
) -> None:
    """Offer every neighbour of a node to the search at its cost from here."""
    station_id, line = node

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
            model.advance(cost, edge.seconds, False),
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
            model.advance(cost, interchange.seconds, True),
            True,
        )


def _relax(
    heap: list[tuple[Cost, StationId, LineId]],
    best: dict[Node, Cost],
    came_from: dict[Node, Arrival],
    current: Node,
    neighbour: Node,
    cost: Cost,
    is_change: bool,
) -> None:
    """Record a cheaper way to reach a neighbour, if this is one."""
    # Checked against None rather than a sentinel default: there is no value that is
    # "worse than anything" for a tuple, and inventing one would be a magic value.
    previous = best.get(neighbour)
    if previous is not None and cost >= previous:
        return
    best[neighbour] = cost
    came_from[neighbour] = (current, is_change)
    heapq.heappush(heap, (cost, neighbour[0], neighbour[1]))


def _walk_back(
    came_from: dict[Node, Arrival], node: Node
) -> list[tuple[Node, Node, bool]]:
    """Every step from the origin to this node, and whether each was a change."""
    steps: list[tuple[Node, Node, bool]] = []
    while node in came_from:
        previous, was_change = came_from[node]
        steps.append((previous, node, was_change))
        node = previous
    steps.reverse()
    return steps


def _build_route(
    network: Network, origin: StationId, finished: tuple[dict[Node, Arrival], Node]
) -> Route:
    """Turn the predecessor table into legs, a total and a change count."""
    came_from, node = finished
    steps = _walk_back(came_from, node)

    legs: list[Leg] = []
    stations: list[StationId] = [origin]
    line: LineId | None = None
    leg_seconds = 0
    total_seconds = 0
    step_free = True

    for (from_station, from_line), (to_station, to_line), was_change in steps:
        if was_change:
            # The change happens where we are standing, so the leg that was in progress
            # ends here.
            interchange = _find_interchange(network, from_station, from_line, to_line)
            total_seconds += interchange.seconds
            step_free = step_free and interchange.step_free
            # Only close a leg that actually went somewhere.
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
        stations.append(to_station)
        line = from_line

    if line is not None:
        legs.append(Leg(line=line, stations=tuple(stations), seconds=leg_seconds))

    return Route(
        legs=tuple(legs),
        total_seconds=total_seconds,
        # A journey with two legs involved one change. Derived rather than counted
        # separately, so the two can never disagree.
        changes=max(len(legs) - 1, 0),
        # The two ends, plus the changes accumulated above. Riding contributes nothing -
        # you need no accessible route at a station you stay on the train through - so
        # this is the whole of what "step-free" means for a journey.
        step_free=step_free and _ends_are_step_free(network, legs),
    )


def _ends_are_step_free(network: Network, legs: list[Leg]) -> bool:
    """Whether you can board at the start and alight at the end."""
    if not legs:
        return True
    boarding = network.step_free_at(legs[0].stations[0], legs[0].line)
    alighting = network.step_free_at(legs[-1].stations[-1], legs[-1].line)
    return boarding and alighting


def _find_edge(
    network: Network, origin: StationId, destination: StationId, line: LineId
) -> Edge:
    """The edge the search used for one hop."""
    for edge in network.edges_from(origin):
        if edge.destination == destination and edge.line == line:
            return edge
    raise LookupError(f"no {line} edge from {origin} to {destination}")


def _find_interchange(
    network: Network, station_id: StationId, from_line: LineId, to_line: LineId
) -> Interchange:
    """The interchange the search used for one change."""
    for interchange in network.interchanges_at(station_id):
        if interchange.from_line == from_line and interchange.to_line == to_line:
            return interchange
    raise LookupError(f"no interchange at {station_id} from {from_line} to {to_line}")
