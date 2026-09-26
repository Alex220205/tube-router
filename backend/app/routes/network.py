"""GET /network."""

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import OperationalError

from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.network import NetworkResponse
from app.services import stations as station_service

router = APIRouter(prefix="/network", tags=["network"])


# Stations with coordinates, directional segments carrying station ids rather than
# nested stations, and the lines with their colours.
@router.get(
    "",
    response_model=NetworkResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def get_network(session: SessionDep) -> NetworkResponse:
    """Every station, segment and line in one payload."""
    try:
        return NetworkResponse(**await station_service.get_network(session))
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
