"""
GET /network.

WHY THIS EXISTS
    Phase 8's map needs every station and every link before it can draw
    anything, so this sends the lot in one response rather than making the
    client assemble it from several.

NO 2021 EQUIVALENT
    The old project drew no map. Its nearest equivalent was the dict of dicts
    that Traversal.Create_graph rebuilt from SQL on every single search and
    then discarded — which is why nothing could ever ask a question about the
    network as a whole. Not even whether it was connected. It was not: 244 of
    346 stations, with two Central line branches and the entire Overground
    unreachable.

WHAT'S NEW
    Sent whole rather than paginated. A partial network is not useful to
    anybody — a map cannot draw half a graph — and at 272 stations and 754
    segments it is a few hundred KB. It becomes a Redis cache candidate in
    Phase 6 alongside the built engine Network, not before: there is no
    evidence yet that it is slow, and caching something fast is how a cache
    becomes a thing to invalidate for no benefit.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import OperationalError

from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.network import NetworkResponse
from app.services import stations as station_service

router = APIRouter(prefix="/network", tags=["network"])


@router.get(
    "",
    response_model=NetworkResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def get_network(session: SessionDep) -> NetworkResponse:
    """Every station, segment and line in one payload.

    Args:
        session: Injected per request.

    Returns:
        Stations with coordinates, directional segments carrying station ids
        rather than nested stations, and the lines with their colours.
    """
    try:
        return NetworkResponse(**await station_service.get_network(session))
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
