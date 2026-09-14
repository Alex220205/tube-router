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

    step_free_only() and without_lines() return a new Network rather than
    editing this one. That is what makes them safe to apply per request in
    Phase 6 — a filter that edited in place would make the graph depend on
    which query ran last, which is bug (3) with a new spelling.

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

from collections.abc import Iterable, Iterator

from .types import Edge, Interchange, LineId, Station, StationId


class Network:
    """An immutable graph of stations, rides and changes."""

    def __init__(
        self,
        stations: Iterable[Station],
        edges: Iterable[Edge],
        interchanges: Iterable[Interchange],
        step_free_platforms: Iterable[tuple[StationId, LineId]] = (),
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
            step_free_platforms: Which (station, line) platforms can be
                reached step-free from the street. Defaults to none, so a
                network built without it answers "not step-free" to
                everything rather than claiming access it was never told
                about — the safe direction, since the failure that strands
                someone is claiming access that is not there.
        """
        self._stations: dict[StationId, Station] = {s.id: s for s in stations}
        self._step_free: frozenset[tuple[StationId, LineId]] = frozenset(
            step_free_platforms
        )

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

    def step_free_at(self, station_id: StationId, line: LineId) -> bool:
        """Whether this platform can be reached step-free from the street.

        Args:
            station_id: The station.
            line: The line whose platform is being asked about.

        Returns:
            True only where the caller said so. Green Park is step-free on the
            Victoria line and not on the Piccadilly, which is why this takes a
            line and a station rather than just a station.
        """
        return (station_id, line) in self._step_free

    def step_free_lines_at(self, station_id: StationId) -> frozenset[LineId]:
        """The lines at a station whose platforms are step-free.

        Used to seed a step-free search, the way lines_at seeds an ordinary
        one: you can only start a step-free journey from a platform you can
        actually reach.
        """
        return frozenset(
            line
            for line in self.lines_at(station_id)
            if self.step_free_at(station_id, line)
        )

    def _all_edges(self) -> Iterator[Edge]:
        """Every edge, flattened back out of the adjacency index."""
        for edges in self._edges.values():
            yield from edges

    def _all_interchanges(self) -> Iterator[Interchange]:
        """Every interchange, flattened back out of the index."""
        for interchanges in self._interchanges.values():
            yield from interchanges

    def step_free_only(self) -> "Network":
        """A network whose every change can be made step-free.

        **Rides are kept, all of them.** You need no accessible route at a
        station you stay on the train through, so filtering rides by the
        accessibility of their endpoints removes journeys that are perfectly
        possible — it left 123 of 754 real rides and broke the accessible
        network into fragments. What a step-free journey actually requires is
        an accessible origin platform, accessible changes, and an accessible
        destination platform. The changes are filtered here; the two ends are
        the search's business, because only it knows where they are.

        Every station is kept too. Dropping them would turn "you cannot get to
        Epping step-free" into NoRoute("unknown_destination"), which is the
        engine claiming a real station does not exist. The honest answer is
        "disconnected".

        Returns:
            A new Network. This one is untouched — the filters are the reason
            immutability was built in Phase 4, since a filter that edited in
            place would make the graph depend on which query ran last.
        """
        return Network(
            stations=self._stations.values(),
            edges=self._all_edges(),
            interchanges=(
                interchange
                for interchange in self._all_interchanges()
                if interchange.step_free
            ),
            step_free_platforms=self._step_free,
        )

    def without_lines(self, lines: Iterable[LineId]) -> "Network":
        """A network with the named lines removed entirely.

        An interchange goes if **either** side names an excluded line. Changing
        from the Victoria to a suspended Central is not possible just because
        the Victoria is running, and filtering on from_line alone would leave
        changes that strand you on a line that is not moving.

        Args:
            lines: Line ids to remove. Unknown ids are ignored rather than
                raising — "avoid the Bakerloo" is a reasonable thing to ask of
                a network that has no Bakerloo.

        Returns:
            A new Network, or this one unchanged when nothing was excluded.
            Returning self is safe precisely because nothing here mutates.
        """
        excluded = frozenset(lines)
        if not excluded:
            return self

        return Network(
            stations=self._stations.values(),
            edges=(edge for edge in self._all_edges() if edge.line not in excluded),
            interchanges=(
                interchange
                for interchange in self._all_interchanges()
                if interchange.from_line not in excluded
                and interchange.to_line not in excluded
            ),
            step_free_platforms=self._step_free,
        )
