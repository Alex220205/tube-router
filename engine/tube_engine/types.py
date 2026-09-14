"""
The values the engine reasons about: stations, edges and interchanges.

WHY THIS EXISTS
    The engine needs a vocabulary that belongs to it rather than to whatever
    happens to be storing the data. These three types are that vocabulary,
    and they are the entire interface a caller has to satisfy — hand
    find_route a Network built from these and it works, whether they came out
    of Postgres, a CSV, or a test written by hand.

WHAT THE 2021 VERSION DID
    Where:  database[works].py lines 472-528, Traversal.Create_graph
    How:    There were no types. The graph was a dict of dicts,
            {station_name: {neighbour_name: minutes}}, built by opening a
            database cursor inside the graph builder and running
            SELECT * FROM connections. Stations were bare strings.
    Wrong:  Two things, and the second is the important one.

            The builder needed a live SQLite connection, so nothing about
            routing could be exercised without one. It never was.

            And the connections table had a line_id column which
            Create_graph read into memory and then never looked at — the loop
            at lines 540-546 uses k[2], k[3] and k[4] and never k[1]. A
            neighbour was a name and a number, with no record of how you got
            there, so "how many times did I change" was not a question the
            data could answer.

WHAT CHANGED AND WHY
    An Edge carries its line. That single field is what makes a change
    countable, and it is the difference between a graph that can answer
    "fewest changes" and one that cannot.

WHAT'S NEW
    Interchange. Changing line had no representation at all in 2021 — not a
    missing field, a missing idea. Here it is a first-class value with its own
    cost, which is what lets the search treat a change as an edge rather than
    as something that happens invisibly between edges.

    Accessibility is deliberately absent from Station and Edge. It belongs to
    a platform — a (station, line) pair — and Network holds it at that grain.
    Phase 5 shipped it on both types, Phase 6 measured what that produced, and
    removing it was the correction. A field the engine cannot answer honestly
    is worse than no field, which docs/DECISIONS.md already recorded once over
    LOG_LEVEL.

CONSTRAINT
    engine/ imports nothing web-related and nothing database-related.
    Enforced by tests/test_imports.py.
"""

from dataclasses import dataclass

# NaPTAN where the caller has it — "940GZZLUOXC" — but the engine never parses
# these, so any stable string works. Tests use "A", "B", "C".
StationId = str

# TfL's line id: "victoria", "hammersmith-city". Again opaque to the engine.
LineId = str


@dataclass(frozen=True)
class Station:
    """A place you can start from, finish at, or change lines at.

    Frozen, like everything else here. The 2021 search mutated the structure
    it was searching — line 532 aliased the graph and line 557 popped from it,
    so one search emptied it — and immutability is what makes that class of
    bug unwritable rather than merely avoided.

    Attributes:
        id: Stable identifier. Compared, never parsed.
        name: For display. The engine never matches on it, which is why the
            2021 habit of deduplicating stations by name string cannot recur
            here.
        lat: WGS84 latitude.
        lon: WGS84 longitude.

    There is deliberately no step_free flag. Accessibility is a property of a
    platform — Green Park is step-free on the Victoria line and not on the
    Piccadilly — so a station-level answer would have to pick one of them and
    be wrong about the other. Network holds it at the right grain instead.
    """

    id: StationId
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Edge:
    """One ride between adjacent stations on one line.

    Directional. The network genuinely is not symmetric: Waterloo & City is
    180 seconds from Bank to Waterloo and 240 seconds coming back, and the
    Piccadilly runs one way round the Heathrow terminal loop. An undirected
    edge would average that away or pick one arbitrarily.

    Attributes:
        origin: Station departed from.
        destination: Station arrived at.
        line: Which line this ride is on. The field 2021 had and discarded.
        seconds: Journey time. Always positive — a zero-weight edge tells a
            search the journey is free, which is worse than a missing edge
            because it produces a confident wrong answer.

    No step_free flag here either, and for a sharper reason than on Station:
    riding is always step-free once you are aboard. You need no accessible
    route at a station you stay on the train through, so a per-ride flag asks
    a question with no answer. Treating one as "both ends accessible" left
    123 of 754 real rides and fragmented the accessible network into pieces.
    """

    origin: StationId
    destination: StationId
    line: LineId
    seconds: int


@dataclass(frozen=True)
class Interchange:
    """The cost of changing from one line to another at a station.

    Directional for the same reason edges are: the walk from the Northern to
    the Central at Bank is not the walk back.

    Attributes:
        station: Where the change happens.
        from_line: Line being left.
        to_line: Line being joined.
        seconds: Walking time between platforms. Positive — a free
            interchange makes "fastest" and "fewest changes" collapse into the
            same answer.
        step_free: Whether this particular change can be made step-free, which
            is not the same as either platform being step-free on its own.
    """

    station: StationId
    from_line: LineId
    to_line: LineId
    seconds: int
    step_free: bool
