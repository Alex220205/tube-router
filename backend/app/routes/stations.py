"""GET /stations and GET /stations/{id}."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import OperationalError

from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.stations import StationPublic, StationRead
from app.services import stations as station_service

router = APIRouter(prefix="/stations", tags=["stations"])


# Matching stations, ordered by name. An empty list when nothing matches - not a 404.
# "No stations called zzz" is a successful answer to a reasonable question.
@router.get(
    "",
    response_model=list[StationPublic],
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def search_stations(
    session: SessionDep,
    q: Annotated[
        str | None,
        Query(description="Substring of the station name. Blank returns everything."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum results.")] = 50,
) -> list[StationPublic]:
    """Search stations by name."""
    try:
        rows = await station_service.search_stations(session, query=q, limit=limit)
        return [StationPublic(**row) for row in rows]
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/{station_id}",
    response_model=StationRead,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def get_station(station_id: int, session: SessionDep) -> StationRead:
    """Fetch one station, with the lines calling at it."""
    try:
        # Guard before touching the database. A negative id cannot match anything, so
        # asking is wasted work and a 404 would misdescribe it - the request is
        # malformed, not pointing at something absent.
        if station_id <= 0:
            raise HTTPException(
                status_code=400, detail="Station ID must be a positive integer"
            )

        station = await station_service.get_station(session, station_id)
        if station is None:
            raise HTTPException(
                status_code=404, detail=f"Station {station_id} not found"
            )

        return StationRead(**station)
    except HTTPException:
        # First, or the handler below swallows the 404 and reports it as a 500 - which
        # sends whoever is debugging it to entirely the wrong place.
        raise
    except OperationalError as exc:
        # The database being briefly unavailable is not a bug in this service.
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
