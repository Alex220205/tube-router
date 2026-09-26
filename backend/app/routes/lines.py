"""GET /lines."""

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
    """Every line, ordered by name."""
    try:
        return [LinePublic(**row) for row in await station_service.list_lines(session)]
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
