"""The routing graph."""

from collections.abc import Iterable, Iterator, Mapping
from collections.abc import Set as AbstractSet

from .types import Edge, Interchange, LineId, Station, StationId


class Network:
    """An immutable graph of stations, rides and changes."""

    # Every question the search asks is answered from a dict built here, so this is the
    # only place that iterates the raw collections.
    def __init__(
        self,
        stations: Iterable[Station],
        edges: Iterable[Edge],
        interchanges: Iterable[Interchange],
        step_free_platforms: Iterable[tuple[StationId, LineId]] = (),
    ) -> None:
        """Index the network for lookup."""
        self._stations: dict[StationId, Station] = {s.id: s for s in stations}
        self._step_free: frozenset[tuple[StationId, LineId]] = frozenset(
            step_free_platforms
        )

        outgoing: dict[StationId, list[Edge]] = {}
        changes: dict[StationId, list[Interchange]] = {}
        lines: dict[StationId, set[LineId]] = {}

        for edge in edges:
            outgoing.setdefault(edge.origin, []).append(edge)
            lines.setdefault(edge.origin, set()).add(edge.line)
            # A station you can only arrive at still serves that line, and the search
            # seeds itself from lines_at(origin) - so a terminus has to be listed too.
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
        """Look up one station."""
        return self._stations[station_id]

    # The edges, as a tuple. Empty for a terminus or an unknown station - an empty
    # result is the correct answer to "what leaves from here", so this does not raise.
    def edges_from(self, station_id: StationId) -> tuple[Edge, ...]:
        """Every ride departing from a station."""
        return self._edges.get(station_id, ())

    def interchanges_at(self, station_id: StationId) -> tuple[Interchange, ...]:
        """Every line change available at a station."""
        return self._interchanges.get(station_id, ())

    # Used to seed the search: standing at the origin you are not yet on any line, so
    # every line serving it is a possible starting node.
    def lines_at(self, station_id: StationId) -> frozenset[LineId]:
        """Which lines serve a station."""
        return self._lines.get(station_id, frozenset())

    # True only where the caller said so. Green Park is step-free on the Victoria line
    # and not on the Piccadilly, which is why this takes a line and a station rather
    # than just a station.
    def step_free_at(self, station_id: StationId, line: LineId) -> bool:
        """Whether this platform can be reached step-free from the street."""
        return (station_id, line) in self._step_free

    # Used to seed a step-free search, the way lines_at seeds an ordinary one: you can
    # only start a step-free journey from a platform you can actually reach.
    def step_free_lines_at(self, station_id: StationId) -> frozenset[LineId]:
        """The lines at a station whose platforms are step-free."""
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

    # **Rides are kept, all of them.** You need no accessible route at a station you
    # stay on the train through, so filtering rides by the accessibility of their
    # endpoints removes journeys that are perfectly possible - it left 123 of 754 real
    # rides and broke the accessible network into fragments.
    def step_free_only(self) -> "Network":
        """A network whose every change can be made step-free."""
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

    # An interchange goes if **either** side names an excluded line. Changing from the
    # Victoria to a suspended Central is not possible just because the Victoria is
    # running, and filtering on from_line alone would leave changes that strand you on a
    # line that is not moving.
    def without_lines(self, lines: Iterable[LineId]) -> "Network":
        """A network with the named lines removed entirely."""
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

    # TfL's status feed distinguishes a line that is shut from a line that is shut
    # *between two places*, and `without_lines` cannot express the second. Removing the
    # whole District because it is closed west of Earl's Court costs a traveller the
    # entire eastern half of a line that is running normally.
    def without_closed_sections(
        self, closures: Mapping[LineId, AbstractSet[StationId]]
    ) -> "Network":
        """A network with only the closed stretch of each line removed."""
        closed = {line: frozenset(stops) for line, stops in closures.items() if stops}
        if not closed:
            return self

        def open_section(edge: Edge) -> bool:
            """Whether this edge lies outside every closed stretch."""
            stops = closed.get(edge.line)
            if stops is None:
                return True
            return not (edge.origin in stops and edge.destination in stops)

        return Network(
            stations=self._stations.values(),
            edges=(edge for edge in self._all_edges() if open_section(edge)),
            interchanges=self._all_interchanges(),
            step_free_platforms=self._step_free,
        )
