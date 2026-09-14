"""
The routing graph. Holds stations, edges and interchanges, and answers
adjacency questions.

WHY THIS EXISTS
    find_route asks "what can I reach from here" thousands of times per
    search. This class indexes adjacency once at construction so the search
    never scans a list.

WHAT THE 2021 VERSION DID
    Where:  database[works].py lines 472-528, Traversal.Create_graph
    How:    Built a dict of dicts, {station_name: {neighbour_name: minutes}},
            by opening a database cursor and running SELECT * FROM connections
            inside the graph builder at line 494. It also created a dummy
            station object with ten placeholder arguments at line 474, purely
            to borrow its database access method.
    Wrong:  Three separate problems.
            1. The builder needed a live SQLite connection, so routing could
               not be exercised without one. None of it was ever tested.
            2. DisplayStationdatabase() — a full SELECT * FROM stations — was
               called inside the innermost loop at lines 509 and 513, so
               building one graph ran tens of thousands of full table scans.
               It ran on every search.
            3. The graph was mutable and the search emptied it while running:
               line 532 aliased it rather than copying, line 557 popped from
               it. A second search on the same object traversed nothing.

WHAT CHANGED AND WHY
    Network takes stations, edges and interchanges as plain objects and does
    not know where they came from. Loading them is
    backend/app/services/graph_loader.py's job in Phase 6, which fixes (1)
    and (2) — the data arrives once, already assembled.

    Nothing here mutates. Adjacency is built in __init__ and never written to
    again, lookups return tuples rather than the internal lists, and the
    search keeps its own distance dict rather than touching the graph. Bug (3)
    is not avoided, it is not expressible: there is nothing to pop from.

WHAT'S NEW
    Interchanges, and lines_at(). The old connections table had a line_id
    column and Create_graph read it then never used it, which is exactly why
    "fewest changes" was never buildable. Edges now carry their line and
    interchanges are first-class, which is what makes the (station, line)
    expansion in routing.py possible.

CONSTRAINT
    engine/ imports nothing web-related and nothing database-related.
    Enforced by tests/test_imports.py.
"""

from collections.abc import Iterable

from .types import Edge, Interchange, LineId, Station, StationId


class Network:
    """An immutable graph of stations, rides and changes."""

    def __init__(
        self,
        stations: Iterable[Station],
        edges: Iterable[Edge],
        interchanges: Iterable[Interchange],
    ) -> None:
        """Index the network for lookup.

        Every question the search asks is answered from a dict built here, so
        this is the only place that iterates the raw collections.

        Args:
            stations: Every station. Later duplicates of an id overwrite
                earlier ones rather than erroring — the caller is responsible
                for its own uniqueness, and the schema already enforces it.
            edges: Every directional ride.
            interchanges: Every directional change.
        """
        self._stations: dict[StationId, Station] = {s.id: s for s in stations}

        # Built as lists, frozen into tuples below. A tuple cannot be appended
        # to by accident, which matters more here than anywhere else in the
        # project: mutating the graph mid-search is the 2021 bug.
        outgoing: dict[StationId, list[Edge]] = {}
        changes: dict[StationId, list[Interchange]] = {}
        lines: dict[StationId, set[LineId]] = {}

        for edge in edges:
            outgoing.setdefault(edge.origin, []).append(edge)
            lines.setdefault(edge.origin, set()).add(edge.line)
            # A station you can only arrive at still serves that line, and
            # the search seeds itself from lines_at(origin) — so a terminus
            # has to be listed too.
            lines.setdefault(edge.destination, set()).add(edge.line)

        for interchange in interchanges:
            changes.setdefault(interchange.station, []).append(interchange)

        self._edges: dict[StationId, tuple[Edge, ...]] = {
            station_id: tuple(items) for station_id, items in outgoing.items()
        }
        self._interchanges: dict[StationId, tuple[Interchange, ...]] = {
            station_id: tuple(items) for station_id, items in changes.items()
        }
        self._lines: dict[StationId, frozenset[LineId]] = {
            station_id: frozenset(items) for station_id, items in lines.items()
        }

    def __contains__(self, station_id: object) -> bool:
        """Whether a station exists in this network."""
        return station_id in self._stations

    def __len__(self) -> int:
        """How many stations the network holds."""
        return len(self._stations)

    def station(self, station_id: StationId) -> Station:
        """Look up one station.

        Args:
            station_id: The id to find.

        Returns:
            The station.

        Raises:
            KeyError: If no such station exists. Raising rather than returning
                None because callers here have already checked membership —
                find_route returns NoRoute("unknown_origin") long before this
                is reached, so a KeyError means a genuine bug rather than
                ordinary missing input.
        """
        return self._stations[station_id]

    def edges_from(self, station_id: StationId) -> tuple[Edge, ...]:
        """Every ride departing from a station.

        Args:
            station_id: Where to depart from.

        Returns:
            The edges, as a tuple. Empty for a terminus or an unknown station
            — an empty result is the correct answer to "what leaves from
            here", so this does not raise.
        """
        return self._edges.get(station_id, ())

    def interchanges_at(self, station_id: StationId) -> tuple[Interchange, ...]:
        """Every line change available at a station.

        Args:
            station_id: Where the change would happen.

        Returns:
            The interchanges, as a tuple. Empty where only one line calls.
        """
        return self._interchanges.get(station_id, ())

    def lines_at(self, station_id: StationId) -> frozenset[LineId]:
        """Which lines serve a station.

        Used to seed the search: standing at the origin you are not yet on any
        line, so every line serving it is a possible starting node.

        Args:
            station_id: The station.

        Returns:
            The line ids. Empty for an unknown or unconnected station.
        """
        return self._lines.get(station_id, frozenset())
