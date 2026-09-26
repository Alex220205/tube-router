"""The values the engine reasons about: stations, edges and interchanges."""

from dataclasses import dataclass

# NaPTAN where the caller has it - "940GZZLUOXC" - but the engine never parses these, so
# any stable string works. Tests use "A", "B", "C".
StationId = str

# TfL's line id: "victoria", "hammersmith-city". Again opaque to the engine.
LineId = str


# There is deliberately no step_free flag. Accessibility is a property of a platform -
# Green Park is step-free on the Victoria line and not on the Piccadilly - so a
# station-level answer would have to pick one of them and be wrong about the other.
# Network holds it at the right grain instead.
@dataclass(frozen=True)
class Station:
    """A place you can start from, finish at, or change lines at."""

    id: StationId
    name: str
    lat: float
    lon: float


# Directional. The network genuinely is not symmetric: Waterloo & City is 180 seconds
# from Bank to Waterloo and 240 seconds coming back, and the Piccadilly runs one way
# round the Heathrow terminal loop. An undirected edge would average that away or pick
# one arbitrarily.
@dataclass(frozen=True)
class Edge:
    """One ride between adjacent stations on one line."""

    origin: StationId
    destination: StationId
    line: LineId
    seconds: int


# Directional for the same reason edges are: the walk from the Northern to the Central
# at Bank is not the walk back.
@dataclass(frozen=True)
class Interchange:
    """The cost of changing from one line to another at a station."""

    station: StationId
    from_line: LineId
    to_line: LineId
    seconds: int
    step_free: bool
