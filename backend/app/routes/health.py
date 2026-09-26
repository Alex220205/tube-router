"""GET /health - is the service up, and can it reach Postgres."""

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
        # Narrow on purpose: a driver or socket failure means "unreachable", which is
        # the answer this endpoint exists to give. Anything else is a bug in the service
        # and should surface as a 500 rather than being reported as a healthy-ish
        # database.
        database = "unreachable"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        database=database,
        version=settings.version,
    )
