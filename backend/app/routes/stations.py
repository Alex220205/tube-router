"""
GET /stations and GET /stations/{id}.

WHY THIS EXISTS
    The first endpoints that read the seeded network. Everything before this
    put data in; these are what let anything get it out.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, GUI.Find_shortest_path and the Display*
            methods
    How:    The interface queried SQLite directly and rendered the result in
            the same function.
    Wrong:  There was no boundary, so there was nothing to test and nothing
            another client could ever consume. The desktop window was the
            only possible front end.

WHAT CHANGED AND WHY
    A handler validates, calls one function in services/, and shapes the
    reply. No SQL here, and no reasoning either — both live in
    services/stations.py, where they can be exercised without HTTP.
"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import OperationalError

from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.stations import StationPublic, StationRead
from app.services import stations as station_service

router = APIRouter(prefix="/stations", tags=["stations"])


@router.get(
    "",
    response_model=list[StationPublic],
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def search_stations(
    session: SessionDep,
    q: str | None = Query(
        default=None,
        description="Substring of the station name. Blank returns everything.",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum results."),
) -> list[StationPublic]:
    """Search stations by name.

    Args:
        session: Injected per request.
        q: What the user typed. Blank or absent returns everything up to the
            limit, because the search box starts empty and a 400 there would
            be noise.
        limit: Capped by the query parameter itself, so an absurd value is a
            422 from FastAPI before any code runs.

    Returns:
        Matching stations, ordered by name. An empty list when nothing
        matches — not a 404. "No stations called zzz" is a successful answer
        to a reasonable question.
    """
    try:
        rows = await station_service.search_stations(session, query=q, limit=limit)
        return [StationPublic(**row) for row in rows]
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc


@router.get(
    "/{station_id}",
    response_model=StationRead,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def get_station(station_id: int, session: SessionDep) -> StationRead:
    """Fetch one station, with the lines calling at it.

    Args:
        station_id: Surrogate identifier.
        session: Injected per request.

    Returns:
        The station, its lines and its interchange complex.

    Raises:
        HTTPException: 400 if the id is not positive, 404 if no such station.
    """
    try:
        # Guard before touching the database. A negative id cannot match
        # anything, so asking is wasted work and a 404 would misdescribe it —
        # the request is malformed, not pointing at something absent.
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
        # First, or the handler below swallows the 404 and reports it as a
        # 500 — which sends whoever is debugging it to entirely the wrong
        # place.
        raise
    except OperationalError as exc:
        # The database being briefly unavailable is not a bug in this service.
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
