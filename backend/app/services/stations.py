"""
Queries over the network tables.

WHY THIS EXISTS
    Route handlers validate input, call one thing, and shape a response.
    Everything with reasoning in it lives here - which for Phase 3 means the
    search, the coordinate extraction, and the joins that turn six normalised
    tables back into something a map can draw.

    Keeping it separate also means these can be tested directly, without an
    HTTP client in the way.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, throughout - Stations.DisplayStationdatabase
            and the SELECTs inline in the GUI methods
    How:    SQL was written wherever a result was wanted, including inside
            Traversal.Create_graph's inner loop at lines 509 and 513.
    Wrong:  A full table scan per call, run tens of thousands of times to
            build one graph, on every search. And because the query and the
            interface were the same function, neither could be exercised
            without the other.

WHAT CHANGED AND WHY
    One place per question. A handler calls a function here and gets rows;
    nothing further down the stack knows HTTP exists.

WHAT'S NEW
    Coordinate extraction. stations.location is geography(Point, 4326), which
    is not JSON, so every read that leaves the database converts it - and
    that conversion is in exactly one place rather than at each call site.
"""

from geoalchemy2 import Geometry
from sqlalchemy import Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Line, Segment, Station, StationComplex, StationLine

# A search box cannot usefully show more than this, and an unbounded query is
# an unbounded response. 272 stations today, but the cap is about the client
# rather than the table size.
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 200


def _station_columns() -> Select:
    """Select a station with its coordinates already unpacked.

    ST_X is longitude and ST_Y is latitude. That reads backwards to anyone
    thinking in "lat, lon" order, and swapping them puts every station in the
    Indian Ocean without raising anything - so the conversion lives here once
    instead of at each call site.
    """
    geometry = cast(Station.location, Geometry)
    return select(
        Station.id,
        Station.naptan_id,
        Station.name,
        func.ST_Y(geometry).label("lat"),
        func.ST_X(geometry).label("lon"),
        Station.complex_id,
    )


async def search_stations(
    session: AsyncSession, query: str | None = None, limit: int = DEFAULT_SEARCH_LIMIT
) -> list[dict]:
    """Find stations whose name contains the query.

    Substring rather than prefix, because names are stored exactly as TfL
    gives them - "Oxford Circus Underground Station" has to be findable by
    typing either "oxford" or "circus".

    Args:
        session: Database session.
        query: What the user typed. None or blank returns everything, up to
            the limit: the search box's first render is empty and erroring
            there would be noise.
        limit: Maximum rows. Clamped to MAX_SEARCH_LIMIT.

    Returns:
        Station rows as dicts, ordered by name.
    """
    statement = _station_columns()

    if query and query.strip():
        # ILIKE rather than lower() = lower(), so Postgres can use an index if
        # one is ever added. There is none today: 272 rows is a sequential
        # scan in under a millisecond, and a trigram index is the right answer
        # at fifty thousand rows, not at this size.
        statement = statement.where(Station.name.ilike(f"%{query.strip()}%"))

    statement = statement.order_by(Station.name).limit(min(limit, MAX_SEARCH_LIMIT))
    result = await session.execute(statement)
    return [dict(row) for row in result.mappings()]


async def get_station(session: AsyncSession, station_id: int) -> dict | None:
    """Fetch one station with the lines serving it and its complex.

    Args:
        session: Database session.
        station_id: Surrogate primary key.

    Returns:
        The station as a dict with `lines` and `complex_name`, or None if no
        such station exists. None rather than raising, so the handler decides
        what a missing station means in HTTP terms.
    """
    result = await session.execute(_station_columns().where(Station.id == station_id))
    row = result.mappings().first()
    if row is None:
        return None

    station = dict(row)

    lines = await session.execute(
        select(Line.code, Line.name, Line.colour, StationLine.step_free_to_platform)
        .join(StationLine, StationLine.line_id == Line.id)
        .where(StationLine.station_id == station_id)
        .order_by(Line.name)
    )
    station["lines"] = [dict(line) for line in lines.mappings()]

    # Bank and Monument share a complex. Nullable, because most stations
    # belong to none.
    station["complex_name"] = None
    if station["complex_id"] is not None:
        station["complex_name"] = await session.scalar(
            select(StationComplex.name).where(
                StationComplex.id == station["complex_id"]
            )
        )

    return station


async def list_lines(session: AsyncSession) -> list[dict]:
    """Every line, ordered by name.

    Returns:
        Line rows as dicts. `mode` is the enum's value, not its name, so the
        response says "tube" rather than "TUBE".
    """
    result = await session.execute(
        select(Line.id, Line.code, Line.name, Line.colour, Line.mode).order_by(
            Line.name
        )
    )
    return [{**row, "mode": row["mode"].value} for row in result.mappings()]


async def get_network(session: AsyncSession) -> dict:
    """Every station, segment and line in one payload.

    Whole rather than paginated: a map cannot draw a partial network, so a
    page of it is not useful to anybody. Roughly 272 stations and 754
    segments - a few hundred KB. It becomes a Redis cache candidate in Phase
    6 alongside the built engine Network, not before.

    Returns:
        A dict with `stations`, `segments` and `lines`. Segments carry station
        ids rather than nested stations, so the client joins them once instead
        of the payload repeating every station up to a dozen times.
    """
    stations = await session.execute(_station_columns().order_by(Station.name))
    segments = await session.execute(
        select(
            Segment.line_id,
            Segment.origin_station_id,
            Segment.destination_station_id,
            Segment.seconds,
        )
    )
    return {
        "stations": [dict(row) for row in stations.mappings()],
        "segments": [dict(row) for row in segments.mappings()],
        "lines": await list_lines(session),
    }
