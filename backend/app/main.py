"""
FastAPI entry point: builds the application, applies CORS, wires the routers,
and closes the connection pool on shutdown.

WHY THIS EXISTS
    One place where the application is assembled, and deliberately nothing
    else. No endpoints are defined here — they live in routes/ — so this file
    stays a readable index of what the service exposes.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, module level and the GUI class
    How:    There was no application object and no entry point in this sense.
            The file defined classes and then built a Tkinter window, so
            importing it started the program.
    Wrong:  Nothing could be imported without side effects, which is another
            reason none of it was testable: to get at a function you had to
            launch the user interface.

WHAT CHANGED AND WHY
    Importing this module constructs an app object and does nothing else. No
    server starts, no window opens, no connection is made. uvicorn runs it in
    production; the test suite imports it and drives it in-process without a
    server at all.

WHAT'S NEW
    CORS, because the frontend runs on a different port and every request is
    therefore cross-origin. The allowed list comes from config rather than
    being a hardcoded literal, so a deployment elsewhere is a variable rather
    than an edit.

    A lifespan handler, so the connection pool is disposed on shutdown
    instead of the process exiting with sockets still open to Postgres.
    Note what it deliberately does NOT do: create tables. Schema changes
    belong to Alembic, where they are reviewable, ordered and reversible.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .core.database import dispose_engine
from .routes.health import router as health_route
from .routes.lines import router as lines_route
from .routes.network import router as network_route
from .routes.route import router as route_route
from .routes.stations import router as stations_route

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down work, either side of the yield.

    Nothing happens on the way in. On the way out the connection pool is
    closed, which is the part that matters — an unclean exit leaves
    connections lingering on the Postgres side until it times them out.
    """
    yield
    await dispose_engine()


app = FastAPI(
    title="Tube Router API",
    version=settings.version,
    summary="London Underground journey planning.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# One line per resource. Explicit rather than routed through an aggregator,
# so this file is the list of what the API serves — adding an endpoint module
# means adding it here, which is a visible change rather than a silent one.
#
# Explicit rather than aggregated, so this file reads as an index of what the
# service serves. status and the status websocket join in Phase 7.
app.include_router(health_route)
app.include_router(stations_route)
app.include_router(lines_route)
app.include_router(network_route)
app.include_router(route_route)


if __name__ == "__main__":
    # For running the API directly during development:
    #     cd backend && uv run python -m app.main
    # The container does not use this path — its CMD invokes uvicorn itself,
    # so host and port come from the Dockerfile rather than from here.
    uvicorn.run(app, host="127.0.0.1", port=8000)
