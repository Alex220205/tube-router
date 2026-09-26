"""
FastAPI entry point: builds the application, applies CORS, wires the routers, and closes
the connection pool on shutdown.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.cache import close as close_cache
from .core.config import get_settings
from .core.database import dispose_engine
from .routes.geocode import router as geocode_route
from .routes.health import router as health_route
from .routes.lines import router as lines_route
from .routes.network import router as network_route
from .routes.places import router as places_route
from .routes.route import router as route_route
from .routes.stations import router as stations_route
from .routes.status import router as status_route
from .routes.ws import router as ws_route
from .services import status_poller

settings = get_settings()


# Nothing here waits on another service. The routing graph is built on first use, so a
# slow database cannot stop the API starting and /health can still say "degraded", and
# the status poller is started rather than awaited: it owns its own failures.
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down work, either side of the yield."""
    poller = asyncio.create_task(status_poller.run())

    yield

    poller.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller
    await dispose_engine()
    await close_cache()


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

# One line per resource. Explicit rather than routed through an aggregator, so this file
# is the list of what the API serves - adding an endpoint module means adding it here,
# which is a visible change rather than a silent one.
app.include_router(health_route)
app.include_router(stations_route)
app.include_router(lines_route)
app.include_router(network_route)
app.include_router(route_route)
app.include_router(places_route)
app.include_router(geocode_route)
app.include_router(status_route)
app.include_router(ws_route)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
