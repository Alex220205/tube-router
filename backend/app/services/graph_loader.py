"""
Rows in, Network out. The boundary between the database and the engine.

WHY THIS EXISTS
    This is the only module in the project allowed to import both SQLAlchemy
    models and engine types. Above it, rows. Below it, domain objects. When
    someone asks where the boundary is, this is the file - and the fact that
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
            connections, and DisplayStationdatabase() - a full SELECT * FROM
            stations over 486 rows - was called at lines 509 and 513 inside a
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
    immutable - the same property that makes the first defect unwritable.

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
import time
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache

# Aliased because this file holds both halves of the boundary: the table rows
# read from Postgres and the engine types built from them share two names.
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
# Network is immutable - a mutable one shared between requests would be the
# 2021 aliasing bug with concurrency on top.
_network: Network | None = None

# Without this, the first few concurrent requests after a restart each build
# their own copy. Harmless but wasteful, and it is the moment the service is
# busiest.
_lock = asyncio.Lock()

# Which generation _network was built at, and when that was last confirmed.
_generation: int | None = None
_checked_at = 0.0

# How often to ask Redis whether the graph is stale. Not per request: a GET is
# well under a millisecond when Redis is healthy and a 250ms timeout when it is
# not, and core/cache.py already measured what that costs - an unreachable
# Redis made the endpoint tests nearly three times slower.
#
# Five seconds bounds staleness at five seconds, costs one GET per five seconds
# under any load, and leaves the warm path exactly as fast as it was.
GENERATION_CHECK_SECONDS = 5.0


# Built on first use rather than at startup. Phase 0 established that a
# degraded database must not stop the API serving - /health reports
# `degraded` with a 200 and the frontend renders it - and building here at
# boot would undo that, failing the container whenever Postgres was slow
# and taking down the one page whose job is to say "database unreachable".
#
# The shared Network. The same object every time, which callers may
# rely on because nothing can modify it.
async def get_network(session: AsyncSession) -> Network:
    """The routing graph, built once per process."""
    global _network, _generation, _checked_at

    # Fast path, and the only one most requests take. _is_stale rate-limits
    # itself, so this is a Redis GET at most once every few seconds.
    if _network is not None and not await _is_stale():
        return _network

    async with _lock:
        # One authoritative read, inside the lock, rather than calling
        # _is_stale again - that would report "not stale" purely because it
        # had just looked, and the rebuild would never happen.
        generation = await cache.read_generation()

        # Another request may have rebuilt while this one waited for the lock.
        if _network is not None and generation in (None, _generation):
            return _network

        rows = await cache.read_json(CACHE_KEY)
        if rows is None:
            rows = await read_rows(session)
            await cache.write_json(CACHE_KEY, rows, CACHE_TTL_SECONDS)

        _network = network_from_rows(rows)
        _generation = generation
        _checked_at = time.monotonic()
        return _network


# True only on a definite mismatch. An unreachable Redis returns None,
# which is treated as "no news" and keeps the current graph - rebuilding
# on every request because the cache is down is how a degraded
# dependency becomes an outage.
async def _is_stale() -> bool:
    """Whether the built graph is older than the generation Redis reports."""
    global _checked_at

    now = time.monotonic()
    if now - _checked_at < GENERATION_CHECK_SECONDS:
        return False

    generation = await cache.read_generation()
    _checked_at = now
    if generation is None:
        return False
    return generation != _generation


# For tests. A reseed does not need this - it bumps the generation key and
# every running process notices within GENERATION_CHECK_SECONDS.
def forget() -> None:
    """Drop the in-process graph so the next request rebuilds it."""
    global _network, _generation, _checked_at
    _network = None
    _generation = None
    _checked_at = 0.0


# A freshly built Network. get_network is what request handlers want;
# this is for tests and for anything that must see current data.
async def load_network(session: AsyncSession) -> Network:
    """Build the routing graph from the database, ignoring every cache."""
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


# Five queries rather than one join. The engine wants whole collections, not
# a row-per-combination, and joining would return every station once per
# line it serves - which is exactly the shape the 2021 schema had and the
# reason it deduplicated by name string on every search.
#
# Lists rather than dicts, because this goes into Redis and the field names
# would be about 60% of the payload.
#
# Stations, edges, interchanges and step-free platforms, keyed by
# NaPTAN id and TfL line code. Those are the identifiers that mean
# something outside this database, so a Route can be rendered without a
# second lookup to translate integers back.
async def read_rows(session: AsyncSession) -> dict[str, Any]:
    """Read everything the graph is built from, as plain JSON-safe values."""
    line_codes = {row.id: row.code for row in await session.scalars(select(Line))}

    # location is geography(Point, 4326), which is not a float pair, so the
    # coordinates are unpacked in SQL. ST_X is longitude and ST_Y is latitude
    # - backwards to anyone thinking "lat, lon", and getting it wrong puts
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
