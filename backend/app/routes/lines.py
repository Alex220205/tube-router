"""
GET /lines.

WHY THIS EXISTS
    The map legend and the objective toggle both need the lines, and both
    need the colours. Eleven rows, so there is no search, no pagination and
    no id lookup - asking for all of them is the only sensible request.

WHAT THE 2021 VERSION DID
    Where:  database[works].py line 729, GUI display of line status
    How:    SELECT lines.name, lines.service_status FROM lines, rendered
            straight into the window.
    Wrong:  service_status was live data in a persistent table, deleted and
            reinserted on every launch. Reading it from the database meant
            reading whatever was true the last time the program started.

WHAT CHANGED AND WHY
    No status here at all. This endpoint serves the things about a line that
    do not change - code, name, colour, mode. Live status arrives over a
    websocket in Phase 7, which is where volatile data belongs.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import OperationalError

from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.lines import LinePublic
from app.services import stations as station_service

router = APIRouter(prefix="/lines", tags=["lines"])


@router.get(
    "",
    response_model=list[LinePublic],
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def list_lines(session: SessionDep) -> list[LinePublic]:
    """Every line, ordered by name.

    Args:
        session: Injected per request.

    Returns:
        All eleven tube lines with their colours.
    """
    try:
        return [LinePublic(**row) for row in await station_service.list_lines(session)]
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
