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
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import SettingsDep
from app.core.database import SessionDep, ping
from app.routes import COMMON_RESPONSES
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    response_model=HealthResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def get_health(session: SessionDep, settings: SettingsDep) -> HealthResponse:
    """Report service and database status."""
    database: Literal["ok", "unreachable"] = "ok"
    try:
        await ping(session)
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
