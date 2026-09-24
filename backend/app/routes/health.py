"""
GET /health - is the service up, and can it reach Postgres.

WHY THIS EXISTS
    A health check that only proves the process started tells you nothing the
    open port did not already tell you. The interesting failure is the
    service running happily while the database is unreachable, so this
    endpoint actually executes a query.

NO 2021 EQUIVALENT
    The old project was a desktop application: if it was not running you
    could see that, and if SQLite was missing it crashed in front of you.
    A service that runs somewhere else has to be asked, both by Docker's
    healthcheck and by the frontend.

WHAT CHANGED AND WHY
    Reporting rather than raising. An unreachable database returns 200 with
    status "degraded" instead of a 500, because the question being asked is
    "what is your state", and refusing to answer it is not a useful reply.
    Docker and the frontend both read the body.
"""

from typing import Literal

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..core.config import SettingsDep
from ..core.database import SessionDep
from ..schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])

# Documented on every route so the generated OpenAPI page lists what a client
# can actually receive, rather than only the happy path. Shared because these
# five mean the same thing everywhere in the API.
responses = {
    400: {"description": "Bad Request"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    500: {"description": "Internal Server Error"},
    503: {"description": "Service Unavailable"},
}


@router.get(
    "",
    response_model=HealthResponse,
    responses={**responses, 200: {"description": "OK"}},
)
async def get_health(session: SessionDep, settings: SettingsDep) -> HealthResponse:
    """Report service and database status."""
    database: Literal["ok", "unreachable"] = "ok"
    try:
        # Cheapest possible round trip. The point is to prove the connection
        # works end to end, not to read anything.
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        # Narrow on purpose: a driver or socket failure means "unreachable",
        # which is the answer this endpoint exists to give. Anything else is
        # a bug in the service and should surface as a 500 rather than being
        # reported as a healthy-ish database.
        database = "unreachable"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        database=database,
        version=settings.version,
    )
