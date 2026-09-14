"""
Transforms TfL payloads into rows ready for the database.

WHY THIS EXISTS
    Every function here is pure: a payload in, plain dataclasses out, no
    database and no network. That is the whole point of the split from
    tfl.py — it means the awkward parts of this phase (branch handling, the
    cumulative timetable arithmetic, the zero-duration floor, TfL's mixed-case
    booleans) are unit-testable against a saved fixture in milliseconds.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, Station.TravelTimesForStations and the
            Add*database methods
    How:    Data arrived from TfL and went into SQLite in the same function
            that fetched it, with the SQL inline.
    Wrong:  There was no point at which a transformed value could be
            inspected before it was written, so nothing could be checked. The
            audit found the result: 12 links stored as zero minutes, two
            Central line branches disconnected from the network, and no
            coordinates at all. None of it was noticed for five years.

WHAT CHANGED AND WHY
    Fetching, transforming and writing are three separate steps. This is the
    middle one and it touches nothing external, so its output can be asserted
    on directly.

WHAT'S NEW
    A stated policy for bad data rather than a silent one. Where TfL gives a
    zero-length gap the duration is floored and *counted*, and the seed
    reports the count. The 2021 code hid the same class of problem behind a
    random number in DisplayTravelTime, which is how it survived so long.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .line_colours import LINE_COLOURS, UNKNOWN_LINE_COLOUR

# TfL's timetables are in whole minutes, so two adjacent stations can report
# the same cumulative arrival and the difference is zero. CHECK (seconds > 0)
# rejects that, correctly — a free hop is exactly the defect the audit found
# twelve of. One minute is the smallest honest value the source can express.
MIN_SEGMENT_SECONDS = 60

# Used for a segment TfL gives no timetable for at all. Happens on branches
# whose timetable endpoint returns nothing for the direction requested.
DEFAULT_SEGMENT_SECONDS = 120

# StepFreeIntechangeInfo.csv covers about 114 platform pairs network-wide, so
# most interchanges have no measured distance. Three minutes is TfL's own
# rule-of-thumb minimum for an interchange in journey planning, and it is
# deliberately not generous: a value that is too low makes the router prefer
# changing, which is the error a user notices immediately and complains about,
# rather than one that quietly degrades the answer.
DEFAULT_INTERCHANGE_SECONDS = 180

# Metres per second. Ordinary walking pace is about 1.4; 1.2 allows for
# stairs, crowds and the fact that these distances are measured along
# corridors rather than as the crow flies.
WALKING_SPEED_M_PER_S = 1.2

# No interchange is instant, whatever the measured distance says.
MIN_INTERCHANGE_SECONDS = 60


@dataclass(frozen=True)
class LineRow:
    code: str
    name: str
    colour: str


@dataclass(frozen=True)
class StationRow:
    naptan_id: str
    name: str
    lat: float
    lon: float
    hub_id: str | None


@dataclass(frozen=True)
class ComplexRow:
    tfl_hub_id: str
    name: str


@dataclass(frozen=True)
class StationLineRow:
    naptan_id: str
    line_code: str
    step_free_to_platform: bool


@dataclass(frozen=True)
class SegmentRow:
    line_code: str
    origin_naptan: str
    destination_naptan: str
    seconds: int


@dataclass(frozen=True)
class InterchangeRow:
    naptan_id: str
    from_line_code: str
    to_line_code: str
    seconds: int
    step_free: bool


# --- booleans ----------------------------------------------------------------


def parse_bool(value: str | None) -> bool:
    """Read one of TfL's booleans.

    The CSVs are inconsistent: DesignatedLevelAccessPoint holds both 'TRUE'
    and 'False', and HasStepFreeRouteInformation has rows reading 'FALSE '
    with a trailing space. Comparing to "TRUE" directly would silently read
    some true values as false, which for step-free access means telling a
    wheelchair user a station is inaccessible when it is not.

    Args:
        value: Raw cell, possibly None, possibly padded, any casing.

    Returns:
        True only for an affirmative value. Anything unrecognised is False:
        absence of evidence is not step-free.
    """
    if value is None:
        return False
    return value.strip().casefold() in {"true", "yes", "1"}


# --- lines -------------------------------------------------------------------


def lines_from_payload(payload: list[dict[str, Any]]) -> list[LineRow]:
    """Turn /Line/Mode/tube into line rows.

    Args:
        payload: Line objects from TfL.

    Returns:
        One row per line, ordered by code so a re-run produces the same
        insertion order and diffs of seed output stay readable.
    """
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


def stations_from_stop_points(
    stop_points_by_line: dict[str, list[dict[str, Any]]],
) -> list[StationRow]:
    """Collect every station across every line, deduplicated by NaPTAN id.

    A station on three lines appears in three responses. The 2021 database
    kept all three as separate rows — 486 rows for 346 stations — which is
    why its graph builder had to deduplicate by name string on every search.
    Here NaPTAN is the identity and the duplicates collapse.

    Args:
        stop_points_by_line: Line code to that line's /StopPoints response.

    Returns:
        One row per distinct station, ordered by NaPTAN id.

    Raises:
        ValueError: If a stop point has no coordinates. stations.location is
            NOT NULL and a station the map cannot draw is not usable, so this
            fails the seed rather than writing a hole.
    """
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
                # commonName verbatim, suffix included. See docs/DECISIONS.md
                # on why nothing here corrects a spelling.
                name=stop["commonName"],
                lat=float(lat),
                lon=float(lon),
                # Empty string means "no hub", which is not the same as a hub
                # called "". Normalised to None so the column is honest.
                hub_id=(stop.get("hubNaptanCode") or None),
            )
    return [seen[key] for key in sorted(seen)]


def complexes_from_stations(stations: list[StationRow]) -> list[ComplexRow]:
    """Derive station complexes from TfL's hub codes.

    Bank and Monument share HUBBAN. Naming the complex after its members
    rather than inventing a label keeps it checkable against TfL.

    Args:
        stations: Station rows, some carrying a hub id.

    Returns:
        One row per distinct hub, named after its member stations.
    """
    members: dict[str, list[str]] = defaultdict(list)
    for station in stations:
        if station.hub_id:
            members[station.hub_id].append(_short_name(station.name))

    return [
        ComplexRow(tfl_hub_id=hub, name=" and ".join(sorted(set(names))))
        for hub, names in sorted(members.items())
    ]


def _short_name(name: str) -> str:
    """Drop the station-type suffix for display inside a complex name.

    Used only to build a readable complex name. It never touches
    stations.name, which stays exactly as TfL gave it.
    """
    for suffix in (" Underground Station", " Rail Station", " DLR Station", " Station"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


# --- station/line membership and step-free access ----------------------------


def step_free_by_station_line(
    platform_services: list[dict[str, str]],
) -> dict[tuple[str, str], bool]:
    """Read step-free access per (station, line) from PlatformServices.csv.

    This is the only place TfL publishes accessibility at that grain, and it
    is why step_free_to_platform lives on station_lines rather than on
    stations: Green Park is step-free on the Victoria line and Pimlico is
    not, on the same line.

    A station counts as step-free for a line if *any* of its platforms on
    that line is accessible. One accessible platform is what makes the
    journey possible.

    Two columns count, not one. DesignatedLevelAccessPoint marks a permanent
    level boarding point; LevelAccessByManualRamp marks one where staff
    deploy a ramp. TfL's own journey planner treats both as step-free, and
    they are nearly disjoint in the data — reading only the first drops
    roughly half the accessible platforms in the network and leaves the
    Central and Bakerloo lines with no step-free stations at all, which is
    not true of the real railway.

    Args:
        platform_services: Rows from PlatformServices.csv.

    Returns:
        (station NaPTAN, line code) to whether it is step-free.
    """
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


def station_lines_from_sequences(
    sequences_by_line: dict[str, list[dict[str, Any]]],
    step_free: dict[tuple[str, str], bool],
) -> list[StationLineRow]:
    """Work out which lines call at which stations.

    Derived from the route sequences rather than from /StopPoints, because a
    sequence is the definitive statement that a line actually runs through a
    station.

    Args:
        sequences_by_line: Line code to that line's route sequence payloads.
        step_free: Output of step_free_by_station_line.

    Returns:
        One row per (station, line), ordered for a stable seed.
    """
    pairs: set[tuple[str, str]] = set()
    for line_code, payloads in sequences_by_line.items():
        for payload in payloads:
            for sequence in payload.get("stopPointSequences", []):
                for stop in sequence.get("stopPoint", []):
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


def durations_from_timetable(
    payload: dict[str, Any], origin_naptan: str
) -> dict[tuple[str, str], int]:
    """Derive adjacent-station durations from a timetable response.

    timeToArrival is cumulative minutes from the origin, so the time between
    two adjacent stations is the difference between consecutive values. The
    first entry is measured from the origin the timetable was requested for,
    which is why that has to be passed in — it does not appear in the
    intervals.

    Args:
        payload: A /Timetable response.
        origin_naptan: The station the timetable was requested from.

    Returns:
        (origin, destination) to seconds. Empty if the payload has no
        timetable, which TfL returns for some branch/direction combinations.
    """
    durations: dict[tuple[str, str], int] = {}
    timetable = payload.get("timetable") or {}

    for route in timetable.get("routes", []):
        for interval_set in route.get("stationIntervals", []):
            previous_stop = origin_naptan
            previous_minutes = 0.0
            for interval in interval_set.get("intervals", []):
                stop = interval.get("stopId")
                minutes = interval.get("timeToArrival")
                if not stop or minutes is None:
                    continue
                gap_seconds = round((float(minutes) - previous_minutes) * 60)
                durations[(previous_stop, stop)] = gap_seconds
                previous_stop = stop
                previous_minutes = float(minutes)

    return durations


def segments_from_sequences(
    line_code: str,
    payloads: list[dict[str, Any]],
    durations: dict[tuple[str, str], int],
) -> tuple[list[SegmentRow], int]:
    """Turn ordered stop sequences into directional segment rows.

    Consecutive stops *within one stopPointSequence* are adjacent. Stops in
    different sequences are on different branches and are not adjacent —
    joining across them would invent track that does not exist, which is the
    mirror image of the 2021 problem where real track was missing and two
    Central line branches ended up unreachable.

    Args:
        line_code: The line these sequences belong to.
        payloads: Route sequence payloads, normally inbound and outbound.
        durations: Lookup from durations_from_timetable.

    Returns:
        The segment rows, and the number whose duration had to be floored or
        defaulted. The count is returned rather than logged so the caller can
        report it — a silent floor is how the 2021 zeroes survived.
    """
    rows: dict[tuple[str, str], SegmentRow] = {}
    adjusted = 0

    for payload in payloads:
        for sequence in payload.get("stopPointSequences", []):
            stops = [stop["id"] for stop in sequence.get("stopPoint", [])]
            for origin, destination in zip(stops, stops[1:], strict=False):
                if origin == destination:
                    # TfL occasionally repeats a stop at a branch join. A
                    # self-loop is rejected by the schema and means nothing.
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
    """Pull the station and its lines out of a platform identifier.

    TfL formats these as {station}-Plat{NN}-{DIRECTION}-{line}, where the
    line itself may contain hyphens ("hammersmith-city") or be several lines
    separated by pipes ("london-overground|national-rail").

    Args:
        platform_id: e.g. "940GZZLUGPK-Plat03-NB-victoria".

    Returns:
        (station NaPTAN, line codes), or None if the id is not in that shape.
    """
    station, separator, remainder = platform_id.partition("-Plat")
    if not separator or not station:
        return None
    parts = remainder.split("-", 2)
    if len(parts) < 3:
        return None
    return station, [code for code in parts[2].split("|") if code]


def interchange_distances(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str, str], int]:
    """Read measured platform-to-platform distances.

    Args:
        rows: StepFreeIntechangeInfo.csv.

    Returns:
        (station, from line, to line) to distance in metres. Where a platform
        serves several lines the distance applies to each pairing. Sparse:
        about 114 rows cover the whole network.
    """
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
            # A walk between two different stations is not an interchange in
            # this model; that is what a station complex represents.
            continue
        for from_line in from_lines:
            for to_line in to_lines:
                if from_line != to_line:
                    distances[(station, from_line, to_line)] = int(raw)
    return distances


def interchanges_from_station_lines(
    station_lines: list[StationLineRow],
    distances: dict[tuple[str, str, str], int],
) -> list[InterchangeRow]:
    """Build an interchange for every ordered pair of lines at a station.

    The pairs are derived — if two lines call at a station you can change
    between them — but the *cost* is not, which is why these are stored rows
    rather than something computed at query time. A measured distance is used
    where TfL has one; everything else gets a stated default rather than a
    number that looks calculated but is not.

    Args:
        station_lines: Output of station_lines_from_sequences.
        distances: Output of interchange_distances.

    Returns:
        One row per (station, from line, to line), both directions.
    """
    by_station: dict[str, list[StationLineRow]] = defaultdict(list)
    for row in station_lines:
        by_station[row.naptan_id].append(row)

    rows: list[InterchangeRow] = []
    for naptan in sorted(by_station):
        serving = sorted(by_station[naptan], key=lambda row: row.line_code)
        for source in serving:
            for target in serving:
                if source.line_code == target.line_code:
                    continue
                metres = distances.get((naptan, source.line_code, target.line_code))
                if metres is None:
                    seconds = DEFAULT_INTERCHANGE_SECONDS
                else:
                    seconds = max(
                        MIN_INTERCHANGE_SECONDS,
                        round(metres / WALKING_SPEED_M_PER_S),
                    )
                rows.append(
                    InterchangeRow(
                        naptan_id=naptan,
                        from_line_code=source.line_code,
                        to_line_code=target.line_code,
                        seconds=seconds,
                        # Two sources, and the order matters. A measured
                        # distance in StepFreeIntechangeInfo.csv is TfL
                        # stating the change is step-free, and it is
                        # authoritative where it exists — but it covers only
                        # a few hundred pairs network-wide.
                        #
                        # Otherwise it is inferred: both platforms being
                        # step-free means the change can normally be made via
                        # the lifts, which is the standard assumption in
                        # accessible journey planning. It is an inference
                        # rather than a fact, and it can be wrong where two
                        # accessible platforms are joined only by stairs.
                        #
                        # Requiring the measurement instead is the safer
                        # reading and was the original rule. It marked 6 of
                        # 312 changes step-free, which left the step-free
                        # network in 40-odd disconnected fragments and made
                        # the objective answer "no route" for essentially
                        # every real journey. A feature that always refuses
                        # is not a cautious feature, it is an absent one.
                        step_free=metres is not None
                        or (
                            source.step_free_to_platform
                            and target.step_free_to_platform
                        ),
                    )
                )
    return rows
