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

from geoalchemy2 import Geography, Geometry
from sqlalchemy import Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Line, Segment, Station, StationComplex, StationLine

# A search box cannot usefully show more than this, and an unbounded query is
# an unbounded response. 272 stations today, but the cap is about the client
# rather than the table size.
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 200


# ST_X is longitude and ST_Y is latitude. That reads backwards to anyone
# thinking in "lat, lon" order, and swapping them puts every station in the
# Indian Ocean without raising anything - so the conversion lives here once
# instead of at each call site.
def _station_columns() -> Select:
    """Select a station with its coordinates already unpacked."""
    geometry = cast(Station.location, Geometry)
    return select(
        Station.id,
        Station.naptan_id,
        Station.name,
        func.ST_Y(geometry).label("lat"),
        func.ST_X(geometry).label("lon"),
        Station.complex_id,
    )


# Substring rather than prefix, because names are stored exactly as TfL
# gives them - "Oxford Circus Underground Station" has to be findable by
# typing either "oxford" or "circus".
#
# session: Database session.
# query: What the user typed. None or blank returns everything, up to
#     the limit: the search box's first render is empty and erroring
#     there would be noise.
# limit: Maximum rows. Clamped to MAX_SEARCH_LIMIT.
async def search_stations(
    session: AsyncSession, query: str | None = None, limit: int = DEFAULT_SEARCH_LIMIT
) -> list[dict]:
    """Find stations whose name contains the query."""
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


# The station as a dict with `lines` and `complex_name`, or None if no
# such station exists. None rather than raising, so the handler decides
# what a missing station means in HTTP terms.
async def get_station(session: AsyncSession, station_id: int) -> dict | None:
    """Fetch one station with the lines serving it and its complex."""
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


# A dict rather than a (lat, lon) tuple on purpose. The one thing that goes
# wrong with coordinates in this codebase is the order, which is why
# _station_columns exists at all, and a tuple is two unlabelled floats that
# can be unpacked backwards without anything raising.
#
# A dict with `naptan_id`, `name`, `lat` and `lon`, or None if no such
# station exists. None rather than raising, as with get_station: the
# handler decides what a missing station means in HTTP terms.
async def coordinates_for_naptan(session: AsyncSession, naptan_id: str) -> dict | None:
    """Where a station is, looked up by its TfL id."""
    result = await session.execute(
        select(
            Station.naptan_id,
            Station.name,
            func.ST_Y(cast(Station.location, Geometry)).label("lat"),
            func.ST_X(cast(Station.location, Geometry)).label("lon"),
        ).where(Station.naptan_id == naptan_id)
    )
    row = result.mappings().first()
    return dict(row) if row else None


# `<->` is the KNN operator and it is what makes this "nearest" rather than
# "sorted by a distance somebody calculated". At 272 rows the GIST index
# Phase 1 built for this saves no measurable time - a sequential scan would
# be instant - but the operator is the one that expresses the question, and
# the alternative is pulling every station into Python to sort it.
#
# ST_MakePoint takes longitude FIRST. Reversed, every answer is a station
# in the Indian Ocean, sorted correctly.
async def nearest_to(
    session: AsyncSession, latitude: float, longitude: float, limit: int = 3
) -> list[dict]:
    """The stations closest to a point on the ground."""
    point = cast(
        func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326), Geography
    )

    result = await session.execute(
        select(
            Station.naptan_id,
            Station.name,
            func.ST_Distance(Station.location, point).label("metres"),
        )
        .order_by(Station.location.op("<->")(point))
        .limit(limit)
    )
    return [
        {"naptan_id": row.naptan_id, "name": row.name, "metres": round(row.metres)}
        for row in result
    ]


# Line rows as dicts. `mode` is the enum's value, not its name, so the
# response says "tube" rather than "TUBE".
async def list_lines(session: AsyncSession) -> list[dict]:
    """Every line, ordered by name."""
    result = await session.execute(
        select(Line.id, Line.code, Line.name, Line.colour, Line.mode).order_by(
            Line.name
        )
    )
    return [{**row, "mode": row["mode"].value} for row in result.mappings()]


# Whole rather than paginated: a map cannot draw a partial network, so a
# page of it is not useful to anybody. Roughly 272 stations and 754
# segments - a few hundred KB. It becomes a Redis cache candidate in Phase
# 6 alongside the built engine Network, not before.
#
# A dict with `stations`, `segments` and `lines`. Segments carry station
# ids rather than nested stations, so the client joins them once instead
# of the payload repeating every station up to a dozen times.
async def get_network(session: AsyncSession) -> dict:
    """Every station, segment and line in one payload."""
    # Step-free is per (station, line) in the database, because a platform is
    # what is accessible or not - the Jubilee at Westminster is step-free and
    # the District at the same station is not. The map draws one marker per
    # station, so it needs the OR of those: "you can get to at least one
    # platform here without stairs".
    #
    # A left join rather than a subquery in _station_columns, because the
    # other two callers of that helper - the search box and the station
    # detail page - do not want this and should not pay for it.
    step_free = (
        select(
            StationLine.station_id,
            func.bool_or(StationLine.step_free_to_platform).label("step_free"),
        )
        .group_by(StationLine.station_id)
        .subquery()
    )

    stations = await session.execute(
        _station_columns()
        .add_columns(func.coalesce(step_free.c.step_free, False).label("step_free"))
        .join(step_free, step_free.c.station_id == Station.id, isouter=True)
        .order_by(Station.name)
    )
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
