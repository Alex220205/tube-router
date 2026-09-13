"""
The routing engine. Give it a graph and a query, get a route back.

    from tube_engine import Network, RouteQuery, find_route

    route = find_route(network, RouteQuery(origin="A", destination="D"))

Pure Python. Zero dependencies, no I/O, no framework. It does not know that
Postgres, FastAPI or TfL exist, and `cd engine && pytest` passes on a machine
with Docker uninstalled.

That separation is the argument this project is making, and it is a reaction
to a specific failure: in 2021 Traversal.Create_graph opened a database cursor
inside the graph builder, so routing could not be exercised without a live
SQLite file. It never was — and the aliasing bug at line 532 destroyed the
graph on every search, unnoticed for five years.

CONSTRAINT
    engine/ imports nothing web-related and nothing database-related.
    Enforced by tests/test_imports.py.
"""

from .network import Network
from .query import Objective, RouteQuery
from .result import (
    DISCONNECTED,
    UNKNOWN_DESTINATION,
    UNKNOWN_ORIGIN,
    Leg,
    NoRoute,
    Route,
)
from .routing import find_route
from .types import Edge, Interchange, LineId, Station, StationId

__version__ = "0.1.0"

__all__ = [
    "DISCONNECTED",
    "UNKNOWN_DESTINATION",
    "UNKNOWN_ORIGIN",
    "Edge",
    "Interchange",
    "Leg",
    "LineId",
    "Network",
    "NoRoute",
    "Objective",
    "Route",
    "RouteQuery",
    "Station",
    "StationId",
    "find_route",
]
