"""
Rows in, Network out. The boundary between the database and the engine.

WHY THIS EXISTS
    This is the only module in the project allowed to import both SQLAlchemy
    models and engine types. Above it, rows. Below it, domain objects. When
    someone asks where the boundary is, this is the file — and the fact that
    it is one small module rather than a layer spread through the codebase is
    the argument the repository structure has been making since Phase 0.

    It exists so that engine/ does not have to. find_route takes a Network
    and knows nothing about where it came from, which is what lets the whole
    routing suite run with Docker uninstalled.

WHAT THE 2021 VERSION DID
    Where:  database[works].py lines 472-528, Traversal.Create_graph
    How:    The graph builder opened its own database cursor. Line 474 built
            a throwaway station object with ten placeholder arguments purely
            to reach its database method, line 494 ran SELECT * FROM
            connections, and DisplayStationdatabase() — a full SELECT * FROM
            stations over 486 rows — was called at lines 509 and 513 inside a
            triple-nested loop.
    Wrong:  Two things, and they compounded.

            Loading and routing were the same function, so routing could not
            be exercised without a live SQLite file. It never was, and the
            aliasing bug at line 532 survived five years as a result.

            And because the graph was built inside the search, it was rebuilt
            on every single query: roughly 173,000 inner iterations and a
            thousand full table scans to answer one question.

WHAT CHANGED AND WHY
    Five queries, run once, assembled into a Network. The engine never sees a
    session, a model or a row; this module never sees a heap or a cost.

    Building it once per process rather than once per search is the direct
    fix for the second defect above, and it is only safe because Network is
    immutable — the same property that makes the first defect unwritable.

WHAT'S NEW
    step_free_platforms. Accessibility is per (station, line), which is the
    grain station_lines has stored since Phase 1, and Phase 6 is where the
    engine finally learned to ask for it at that grain rather than flattening
    it onto edges.

CONSTRAINT
    The import rule runs the other way here. engine/ may not import this;
    this may import engine/. tests/test_imports.py enforces the direction.
"""

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Interchange as InterchangeRow
from app.models import Line, Segment, StationLine
from app.models import Station as StationRow
from tube_engine import Edge, Interchange, Network, Station


async def load_network(session: AsyncSession) -> Network:
    """Build the routing graph from the database.

    Five queries rather than one join. The engine wants whole collections, not
    a row-per-combination, and joining would return every station once per
    line it serves — which is exactly the shape the 2021 schema had and the
    reason it deduplicated by name string on every search.

    Args:
        session: An open async session. Read only; nothing here writes.

    Returns:
        A Network keyed by NaPTAN id and TfL line code. Those are the
        identifiers that mean something outside this database, so a Route can
        be rendered without a second lookup to translate integers back.
    """
    line_codes = {row.id: row.code for row in await session.scalars(select(Line))}

    # location is geography(Point, 4326), which is not a float pair, so the
    # coordinates are unpacked in SQL. ST_X is longitude and ST_Y is latitude
    # — backwards to anyone thinking "lat, lon", and getting it wrong puts
    # every station in the Indian Ocean without raising anything.
    geometry = cast(StationRow.location, Geometry)
    station_rows = (
        await session.execute(
            select(
                StationRow.id,
                StationRow.naptan_id,
                StationRow.name,
                func.ST_Y(geometry).label("lat"),
                func.ST_X(geometry).label("lon"),
            )
        )
    ).all()
    naptan = {row.id: row.naptan_id for row in station_rows}

    stations = [
        Station(id=row.naptan_id, name=row.name, lat=row.lat, lon=row.lon)
        for row in station_rows
    ]

    edges = [
        Edge(
            origin=naptan[row.origin_station_id],
            destination=naptan[row.destination_station_id],
            line=line_codes[row.line_id],
            seconds=row.seconds,
        )
        for row in await session.scalars(select(Segment))
    ]

    interchanges = [
        Interchange(
            station=naptan[row.station_id],
            from_line=line_codes[row.from_line_id],
            to_line=line_codes[row.to_line_id],
            seconds=row.seconds,
            step_free=row.step_free,
        )
        for row in await session.scalars(select(InterchangeRow))
    ]

    step_free_platforms = [
        (naptan[row.station_id], line_codes[row.line_id])
        for row in await session.scalars(select(StationLine))
        if row.step_free_to_platform
    ]

    return Network(
        stations=stations,
        edges=edges,
        interchanges=interchanges,
        step_free_platforms=step_free_platforms,
    )
