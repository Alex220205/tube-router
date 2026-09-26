"""POST /route - the endpoint the whole project exists to serve."""

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import OperationalError

from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.route import LegPublic, RouteRequest, RouteResponse, StationStop
from app.services import graph_loader, journeys
from tube_engine import Network, Objective, Route

router = APIRouter(prefix="/route", tags=["route"])

# Accepted values for `objective`, mapped from the wire spelling. Built from the enum
# rather than written out, so adding an objective to the engine makes it requestable
# here without a second edit that could be forgotten.
OBJECTIVES = {objective.value: objective for objective in Objective}


def _objective(name: str) -> Objective:
    """The objective a request names, or a 400 listing the real ones."""
    objective = OBJECTIVES.get(name)
    if objective is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown objective {name!r}. "
                f"Expected one of {', '.join(sorted(OBJECTIVES))}."
            ),
        )
    return objective


def _require_station(network: Network, naptan_id: str) -> None:
    """A 404 naming the station, if the network does not have it."""
    if naptan_id not in network:
        raise HTTPException(status_code=404, detail=f"Unknown station {naptan_id!r}")


# The engine speaks in NaPTAN ids because it must not care what anything is called. A
# client needs "Green Park", and this is the only place that knows both.
def _to_response(
    network: Network, result: Route, avoided: list[str], partial: list[str]
) -> RouteResponse:
    """Turn an engine Route into the wire format, resolving names as it goes."""
    return RouteResponse(
        found=True,
        avoided_for_disruption=avoided,
        partly_closed=partial,
        total_seconds=result.total_seconds,
        changes=result.changes,
        step_free=result.step_free,
        legs=[
            LegPublic(
                line=leg.line,
                seconds=leg.seconds,
                stations=[
                    StationStop(id=station_id, name=network.station(station_id).name)
                    for station_id in leg.stations
                ],
            )
            for leg in result.legs
        ],
    )


# The session is used only when the network has to be built. After that the process
# holds the network and the database is not asked again.
@router.post(
    "",
    response_model=RouteResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def plan_route(request: RouteRequest, session: SessionDep) -> RouteResponse:
    """Plan a journey between two stations."""
    try:
        # Guard before touching the database: no network is needed to know that
        # "quickest" is not an objective.
        objective = _objective(request.objective)

        # Built once per process and shared, not rebuilt per request.
        network = await graph_loader.get_network(session)

        # Checked separately so the message can say which end was wrong. "One of your
        # stations does not exist" is not a useful thing to tell someone.
        _require_station(network, request.origin)
        _require_station(network, request.destination)

        result, avoided, partial = await journeys.plan(
            network,
            request.origin,
            request.destination,
            objective,
            frozenset(request.avoid_lines),
        )
        if isinstance(result, Route):
            return _to_response(network, result, avoided, partial)

        # Real stations, no journey between them. A 200 with a reason: the question was
        # well-formed and this is its answer. The avoided list goes out here too - "no
        # route" and "no route while the Piccadilly is suspended" are different answers
        # and a caller should see which.
        return RouteResponse(
            found=False,
            reason=result.reason,
            avoided_for_disruption=avoided,
            partly_closed=partial,
        )

    except HTTPException:
        # First, or the handler below swallows the 404 and reports it as a 500.
        raise
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
