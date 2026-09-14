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

import asyncio
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.models import Interchange as InterchangeRow
from app.models import Line, Segment, StationLine
from app.models import Station as StationRow
from tube_engine import Edge, Interchange, Network, Station

# Bumped when the shape below changes, so a deploy reading an older entry
# treats it as a miss rather than unpacking it wrongly.
CACHE_KEY = "tube-router:network:v1"

# An hour. Long enough that it is effectively always warm, short enough that
# a reseed which forgot to invalidate corrects itself rather than serving a
# stale network until someone restarts the process.
CACHE_TTL_SECONDS = 3600

# The built graph, held for the life of the process. This is the direct fix
# for Create_graph running inside the search, and it is only safe because
# Network is immutable — a mutable one shared between requests would be the
# 2021 aliasing bug with concurrency on top.
_network: Network | None = None

# Without this, the first few concurrent requests after a restart each build
# their own copy. Harmless but wasteful, and it is the moment the service is
# busiest.
_lock = asyncio.Lock()


async def get_network(session: AsyncSession) -> Network:
    """The routing graph, built once per process.

    Built on first use rather than at startup. Phase 0 established that a
    degraded database must not stop the API serving — /health reports
    `degraded` with a 200 and the frontend renders it — and building here at
    boot would undo that, failing the container whenever Postgres was slow
    and taking down the one page whose job is to say "database unreachable".

    Args:
        session: Used only if the graph has to be built.

    Returns:
        The shared Network. The same object every time, which callers may
        rely on because nothing can modify it.
    """
    global _network
    if _network is not None:
        return _network

    async with _lock:
        # Checked again inside the lock: several requests can arrive here
        # together and only the first should do the work.
        if _network is not None:
            return _network

        rows = await cache.read_json(CACHE_KEY)
        if rows is None:
            rows = await read_rows(session)
            await cache.write_json(CACHE_KEY, rows, CACHE_TTL_SECONDS)

        _network = network_from_rows(rows)
        return _network


def forget() -> None:
    """Drop the in-process graph so the next request rebuilds it.

    For tests, and for a reseed that wants the running service to notice.
    Does not touch Redis; call cache.delete(CACHE_KEY) for that.
    """
    global _network
    _network = None


async def load_network(session: AsyncSession) -> Network:
    """Build the routing graph from the database, ignoring every cache.

    Args:
        session: An open async session. Read only; nothing here writes.

    Returns:
        A freshly built Network. get_network is what request handlers want;
        this is for tests and for anything that must see current data.
    """
    return network_from_rows(await read_rows(session))


def network_from_rows(rows: dict[str, Any]) -> Network:
    """Assemble a Network from the plain structure read_rows produces."""
    return Network(
        stations=[
            Station(id=naptan, name=name, lat=lat, lon=lon)
            for naptan, name, lat, lon in rows["stations"]
        ],
        edges=[
            Edge(origin=origin, destination=destination, line=line, seconds=seconds)
            for origin, destination, line, seconds in rows["edges"]
        ],
        interchanges=[
            Interchange(
                station=station,
                from_line=from_line,
                to_line=to_line,
                seconds=seconds,
                step_free=step_free,
            )
            for station, from_line, to_line, seconds, step_free in rows["interchanges"]
        ],
        step_free_platforms=[
            (station, line) for station, line in rows["step_free_platforms"]
        ],
    )


async def read_rows(session: AsyncSession) -> dict[str, Any]:
    """Read everything the graph is built from, as plain JSON-safe values.

    Five queries rather than one join. The engine wants whole collections, not
    a row-per-combination, and joining would return every station once per
    line it serves — which is exactly the shape the 2021 schema had and the
    reason it deduplicated by name string on every search.

    Lists rather than dicts, because this goes into Redis and the field names
    would be about 60% of the payload.

    Args:
        session: An open async session. Read only; nothing here writes.

    Returns:
        Stations, edges, interchanges and step-free platforms, keyed by
        NaPTAN id and TfL line code. Those are the identifiers that mean
        something outside this database, so a Route can be rendered without a
        second lookup to translate integers back.
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

    return {
        "stations": [
            [row.naptan_id, row.name, row.lat, row.lon] for row in station_rows
        ],
        "edges": [
            [
                naptan[row.origin_station_id],
                naptan[row.destination_station_id],
                line_codes[row.line_id],
                row.seconds,
            ]
            for row in await session.scalars(select(Segment))
        ],
        "interchanges": [
            [
                naptan[row.station_id],
                line_codes[row.from_line_id],
                line_codes[row.to_line_id],
                row.seconds,
                row.step_free,
            ]
            for row in await session.scalars(select(InterchangeRow))
        ],
        "step_free_platforms": [
            [naptan[row.station_id], line_codes[row.line_id]]
            for row in await session.scalars(select(StationLine))
            if row.step_free_to_platform
        ],
    }
