"""Transforms TfL payloads into rows ready for the database."""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from .line_colours import LINE_COLOURS, UNKNOWN_LINE_COLOUR

# TfL's timetables are in whole minutes, so two adjacent stations can report the same
# arrival and a gap of zero. The schema rejects a zero-second hop, rightly, so one
# minute is the smallest honest value the source can express.
MIN_SEGMENT_SECONDS = 60

# Used for a segment TfL gives no timetable for at all. Happens on branches whose
# timetable endpoint returns nothing for the direction requested.
DEFAULT_SEGMENT_SECONDS = 120

# StepFreeIntechangeInfo.csv covers about 114 platform pairs network-wide, so most
# interchanges have no measured distance.
DEFAULT_INTERCHANGE_SECONDS = 180

# Metres per second. Ordinary walking pace is about 1.4; 1.2 allows for stairs, crowds
# and the fact that these distances are measured along corridors rather than as the crow
# flies.
WALKING_SPEED_M_PER_S = 1.2

# No interchange is instant, whatever the measured distance says.
MIN_INTERCHANGE_SECONDS = 60


@dataclass(frozen=True)
class LineRow:
    """A tube line as the seed will write it."""

    code: str
    name: str
    colour: str


@dataclass(frozen=True)
class StationRow:
    """A station as the seed will write it, before it has a database id."""

    naptan_id: str
    name: str
    lat: float
    lon: float
    hub_id: str | None


@dataclass(frozen=True)
class ComplexRow:
    """A group of stations TfL treats as one hub, such as Bank and Monument."""

    tfl_hub_id: str
    name: str


@dataclass(frozen=True)
class StationLineRow:
    """One line calling at one station, and whether that platform is step-free."""

    naptan_id: str
    line_code: str
    step_free_to_platform: bool


@dataclass(frozen=True)
class SegmentRow:
    """One directional hop between adjacent stations on a line."""

    line_code: str
    origin_naptan: str
    destination_naptan: str
    seconds: int


@dataclass(frozen=True)
class InterchangeRow:
    """The cost of changing from one line to another at a station."""

    naptan_id: str
    from_line_code: str
    to_line_code: str
    seconds: int
    step_free: bool


# --- booleans ----------------------------------------------------------------


# The CSVs are inconsistent: DesignatedLevelAccessPoint holds both 'TRUE' and 'False',
# and HasStepFreeRouteInformation has rows reading 'FALSE ' with a trailing space.
# Comparing to "TRUE" directly would silently read some true values as false, which for
# step-free access means telling a wheelchair user a station is inaccessible when it is
# not.
def parse_bool(value: str | None) -> bool:
    """Read one of TfL's booleans."""
    if value is None:
        return False
    return value.strip().casefold() in {"true", "yes", "1"}


# --- lines -------------------------------------------------------------------


# One row per line, ordered by code so a re-run produces the same insertion order and
# diffs of seed output stay readable.
def lines_from_payload(payload: list[dict[str, Any]]) -> list[LineRow]:
    """Turn /Line/Mode/tube into line rows."""
    rows = [
        LineRow(
            code=line["id"],
            name=line["name"],
            colour=LINE_COLOURS.get(line["id"], UNKNOWN_LINE_COLOUR),
        )
        for line in payload
    ]
    return sorted(rows, key=lambda row: row.code)


# --- stations and complexes --------------------------------------------------


# A station on three lines appears in three responses. NaPTAN id is the identity,
# so the duplicates collapse into one row.
def stations_from_stop_points(
    stop_points_by_line: dict[str, list[dict[str, Any]]],
) -> list[StationRow]:
    """Collect every station across every line, deduplicated by NaPTAN id."""
    seen: dict[str, StationRow] = {}
    for stops in stop_points_by_line.values():
        for stop in stops:
            naptan = stop["naptanId"]
            if naptan in seen:
                continue
            lat, lon = stop.get("lat"), stop.get("lon")
            if lat is None or lon is None:
                raise ValueError(
                    f"{naptan} ({stop.get('commonName')}) has no coordinates"
                )
            seen[naptan] = StationRow(
                naptan_id=naptan,
                name=stop["commonName"],
                lat=float(lat),
                lon=float(lon),
                # Empty string means "no hub", which is not the same as a hub called "".
                # Normalised to None so the column is honest.
                hub_id=(stop.get("hubNaptanCode") or None),
            )
    return [seen[key] for key in sorted(seen)]


# Bank and Monument share HUBBAN. Naming the complex after its members rather than
# inventing a label keeps it checkable against TfL.
def complexes_from_stations(stations: list[StationRow]) -> list[ComplexRow]:
    """Derive station complexes from TfL's hub codes."""
    members: dict[str, list[str]] = defaultdict(list)
    for station in stations:
        if station.hub_id:
            members[station.hub_id].append(_short_name(station.name))

    return [
        ComplexRow(tfl_hub_id=hub, name=" and ".join(sorted(set(names))))
        for hub, names in sorted(members.items())
    ]


# Used only to build a readable complex name. It never touches stations.name, which
# stays exactly as TfL gave it.
def _short_name(name: str) -> str:
    """Drop the station-type suffix for display inside a complex name."""
    for suffix in (" Underground Station", " Rail Station", " DLR Station", " Station"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


# --- station/line membership and step-free access ----------------------------


# This is the only place TfL publishes accessibility at that grain, and it is why
# step_free_to_platform lives on station_lines rather than on stations: Green Park is
# step-free on the Victoria line and Pimlico is not, on the same line.
def step_free_by_station_line(
    platform_services: list[dict[str, str]],
) -> dict[tuple[str, str], bool]:
    """Read step-free access per (station, line) from PlatformServices.csv."""
    result: dict[tuple[str, str], bool] = {}
    for row in platform_services:
        station = (row.get("StopAreaNaptanCode") or "").strip()
        line = (row.get("Line") or "").strip()
        if not station or not line:
            continue
        key = (station, line)
        accessible = parse_bool(row.get("DesignatedLevelAccessPoint")) or parse_bool(
            row.get("LevelAccessByManualRamp")
        )
        result[key] = result.get(key, False) or accessible
    return result


# TfL nests a line's route three deep: a payload per direction, a sequence per branch
# within it, and the ordered stops within that. Every caller wants the innermost level,
# so the walk is written once here.
def stop_sequences(
    payloads: Iterable[dict[str, Any]],
) -> Iterator[list[dict[str, Any]]]:
    """Every ordered run of stops in a line's route sequence payloads."""
    for payload in payloads:
        for sequence in payload.get("stopPointSequences", []):
            stops = sequence.get("stopPoint", [])
            if stops:
                yield stops


# Derived from the route sequences rather than from /StopPoints, because a sequence is
# the definitive statement that a line actually runs through a station.
def station_lines_from_sequences(
    sequences_by_line: dict[str, list[dict[str, Any]]],
    step_free: dict[tuple[str, str], bool],
) -> list[StationLineRow]:
    """Work out which lines call at which stations."""
    pairs: set[tuple[str, str]] = set()
    for line_code, payloads in sequences_by_line.items():
        for stops in stop_sequences(payloads):
            for stop in stops:
                pairs.add((stop["id"], line_code))

    return [
        StationLineRow(
            naptan_id=naptan,
            line_code=line_code,
            step_free_to_platform=step_free.get((naptan, line_code), False),
        )
        for naptan, line_code in sorted(pairs)
    ]


# --- segments ----------------------------------------------------------------


# timeToArrival is cumulative minutes from the origin, so the time between two adjacent
# stations is the difference between consecutive values. The first entry is measured
# from the origin the timetable was requested for, which is why that has to be passed in
# - it does not appear in the intervals.
def _gaps_between(
    interval_set: dict[str, Any], origin_naptan: str
) -> dict[tuple[str, str], int]:
    """Seconds between each adjacent pair in one run of intervals."""
    gaps: dict[tuple[str, str], int] = {}
    previous_stop = origin_naptan
    previous_minutes = 0.0

    for interval in interval_set.get("intervals", []):
        stop = interval.get("stopId")
        minutes = interval.get("timeToArrival")
        if not stop or minutes is None:
            continue
        gaps[(previous_stop, stop)] = round((float(minutes) - previous_minutes) * 60)
        previous_stop = stop
        previous_minutes = float(minutes)

    return gaps


# (origin, destination) to seconds. Empty if the payload has no timetable, which TfL
# returns for some branch/direction combinations.
def durations_from_timetable(
    payload: dict[str, Any], origin_naptan: str
) -> dict[tuple[str, str], int]:
    """Derive adjacent-station durations from a timetable response."""
    durations: dict[tuple[str, str], int] = {}
    timetable = payload.get("timetable") or {}

    for route in timetable.get("routes", []):
        for interval_set in route.get("stationIntervals", []):
            durations.update(_gaps_between(interval_set, origin_naptan))

    return durations


def segments_from_sequences(
    line_code: str,
    payloads: list[dict[str, Any]],
    durations: dict[tuple[str, str], int],
) -> tuple[list[SegmentRow], int]:
    """Turn ordered stop sequences into directional segment rows."""
    rows: dict[tuple[str, str], SegmentRow] = {}
    adjusted = 0

    for stops in stop_sequences(payloads):
        ids = [stop["id"] for stop in stops]
        for origin, destination in zip(ids, ids[1:], strict=False):
            if origin == destination:
                # TfL occasionally repeats a stop at a branch join. A self-loop is
                # rejected by the schema and means nothing.
                continue

            seconds = durations.get((origin, destination))
            if seconds is None:
                seconds = DEFAULT_SEGMENT_SECONDS
                adjusted += 1
            elif seconds < MIN_SEGMENT_SECONDS:
                seconds = MIN_SEGMENT_SECONDS
                adjusted += 1

            rows[(origin, destination)] = SegmentRow(
                line_code=line_code,
                origin_naptan=origin,
                destination_naptan=destination,
                seconds=seconds,
            )

    return [rows[key] for key in sorted(rows)], adjusted


# --- interchanges ------------------------------------------------------------


def parse_platform_id(platform_id: str) -> tuple[str, list[str]] | None:
    """Pull the station and its lines out of a platform identifier."""
    station, separator, remainder = platform_id.partition("-Plat")
    if not separator or not station:
        return None
    parts = remainder.split("-", 2)
    if len(parts) < 3:
        return None
    return station, [code for code in parts[2].split("|") if code]


# A platform id can name several lines, separated by pipes, so one measured walk becomes
# a pair for each line at each end. The same line at both ends is not a change.
def _different_lines(
    from_lines: list[str], to_lines: list[str]
) -> Iterator[tuple[str, str]]:
    """Every ordered pair of different lines across two platform ends."""
    for from_line in from_lines:
        for to_line in to_lines:
            if from_line != to_line:
                yield from_line, to_line


# (station, from line, to line) to distance in metres. Where a platform serves several
# lines the distance applies to each pairing. Sparse: about 114 rows cover the whole
# network.
def interchange_distances(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str, str], int]:
    """Read measured platform-to-platform distances."""
    distances: dict[tuple[str, str, str], int] = {}
    for row in rows:
        source = parse_platform_id((row.get("FromPlatformUniqueId") or "").strip())
        target = parse_platform_id((row.get("ToPlatformUniqueId") or "").strip())
        raw = (row.get("DistanceInMetres") or "").strip()
        if not source or not target or not raw.isdigit():
            continue
        station, from_lines = source
        to_station, to_lines = target
        if station != to_station:
            # A walk between two different stations is not an interchange in this model;
            # that is what a station complex represents.
            continue
        for from_line, to_line in _different_lines(from_lines, to_lines):
            distances[(station, from_line, to_line)] = int(raw)
    return distances


# TfL publishes the same corridor whole and in halves. At Green Park the direct
# jubilee-to-victoria walk is 380 m, and jubilee to piccadilly to victoria is
# 220 + 160, the same 380 m. Rounded to whole seconds separately, the halves come to a
# second less than the whole, so the router could save a second by walking through a
# platform it never boards. The shortest walk over every platform removes that.
def _shortest_walks(
    naptan: str,
    codes: list[str],
    distances: dict[tuple[str, str, str], int],
) -> dict[tuple[str, str], int]:
    """Interchange times at one station, closed under the triangle inequality."""
    cost: dict[tuple[str, str], int] = {}
    for source in codes:
        for target in codes:
            if source == target:
                continue
            metres = distances.get((naptan, source, target))
            if metres is None:
                cost[(source, target)] = DEFAULT_INTERCHANGE_SECONDS
            else:
                cost[(source, target)] = max(
                    MIN_INTERCHANGE_SECONDS,
                    round(metres / WALKING_SPEED_M_PER_S),
                )

    for via in codes:
        for source in codes:
            if source == via:
                continue
            for target in codes:
                if target in (source, via):
                    continue
                through = cost[(source, via)] + cost[(via, target)]
                if through < cost[(source, target)]:
                    cost[(source, target)] = through

    return cost


def _changes_at(
    serving: list[StationLineRow],
) -> Iterator[tuple[StationLineRow, StationLineRow]]:
    """Every ordered pair of different lines calling at one station."""
    for source in serving:
        for target in serving:
            if source.line_code != target.line_code:
                yield source, target


# Two sources, and the order matters. A measured distance in StepFreeIntechangeInfo.csv
# is TfL stating the change is step-free, and it is authoritative where it exists - but
# it covers only a few hundred pairs network-wide.
def _step_free_change(
    measured: bool, source: StationLineRow, target: StationLineRow
) -> bool:
    """Whether changing between these two platforms avoids stairs."""
    return measured or (source.step_free_to_platform and target.step_free_to_platform)


# The pairs are derived - if two lines call at a station you can change between them -
# but the *cost* is not, which is why these are stored rows rather than something
# computed at query time. A measured distance is used where TfL has one; everything else
# gets a stated default rather than a number that looks calculated but is not.
def interchanges_from_station_lines(
    station_lines: list[StationLineRow],
    distances: dict[tuple[str, str, str], int],
) -> list[InterchangeRow]:
    """Build an interchange for every ordered pair of lines at a station."""
    by_station: dict[str, list[StationLineRow]] = defaultdict(list)
    for row in station_lines:
        by_station[row.naptan_id].append(row)

    rows: list[InterchangeRow] = []
    for naptan in sorted(by_station):
        serving = sorted(by_station[naptan], key=lambda row: row.line_code)
        codes = [row.line_code for row in serving]
        cost = _shortest_walks(naptan, codes, distances)

        for source, target in _changes_at(serving):
            metres = distances.get((naptan, source.line_code, target.line_code))
            rows.append(
                InterchangeRow(
                    naptan_id=naptan,
                    from_line_code=source.line_code,
                    to_line_code=target.line_code,
                    seconds=cost[(source.line_code, target.line_code)],
                    step_free=_step_free_change(metres is not None, source, target),
                )
            )
    return rows
