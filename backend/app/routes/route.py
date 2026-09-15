"""
POST /route - the endpoint the whole project exists to serve.

WHY THIS EXISTS
    Five phases built the parts. This is where a browser can finally ask for
    a journey and get one. It is also the second half of the engine boundary:
    a Pydantic request becomes a RouteQuery, find_route answers, and engine
    dataclasses become schemas on the way out. Nothing of FastAPI reaches the
    engine and nothing of the engine reaches the wire.

WHAT THE 2021 VERSION DID
    Where:  database[works].py lines 860-880, GUI.Find_shortest_path
    How:    A Tkinter button handler read two entry boxes, constructed a
            Traversal, called shortest_path(), and read the answer back off
            the same object. Lines 868 and 876 compared the result against
            the literal 9999999 to decide whether to draw a route.
    Wrong:  There was no interface, so there was no place for input handling
            to live. The window validated nothing, the search signalled
            failure with a magic number, and the two were the same program -
            which is why neither could be tested.

WHAT CHANGED AND WHY
    Unknown stations are a 404 naming which one was unknown. Two real
    stations that are not connected are a **200 carrying a reason**, because
    that is a successful answer to a well-formed question. The distinction
    matters: a 404 would tell a client the request was wrong when it was not.

WHAT'S NEW
    Nothing in 2021 had a network to hold. The built Network is cached per
    process rather than rebuilt per request, which is the direct fix for
    Create_graph running inside the search.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import OperationalError

from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.route import LegPublic, RouteRequest, RouteResponse, StationStop
from app.services import graph_loader, status_poller
from tube_engine import Network, Objective, Route, RouteQuery, find_route

router = APIRouter(prefix="/route", tags=["route"])

# Accepted values for `objective`, mapped from the wire spelling. Built from
# the enum rather than written out, so adding an objective to the engine makes
# it requestable here without a second edit that could be forgotten.
OBJECTIVES = {objective.value: objective for objective in Objective}


def _to_response(network: Network, result: Route, avoided: list[str]) -> RouteResponse:
    """Turn an engine Route into the wire format, resolving names as it goes.

    The engine speaks in NaPTAN ids because it must not care what anything is
    called. A client needs "Green Park", and this is the only place that
    knows both.
    """
    return RouteResponse(
        found=True,
        avoided_for_disruption=avoided,
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


@router.post(
    "",
    response_model=RouteResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def plan_route(request: RouteRequest, session: SessionDep) -> RouteResponse:
    """Plan a journey between two stations.

    Args:
        request: Origin, destination, objective and any lines to avoid.
        session: Injected per request. Used only if the network needs building.

    Returns:
        A RouteResponse. `found` is false with a reason when the two stations
        are real but not connected - a 200, because that is a correct answer
        rather than a failed request.

    Raises:
        HTTPException: 400 for an objective that does not exist, 404 for a
            station that does not exist, 503 if the network cannot be built.
    """
    try:
        objective = OBJECTIVES.get(request.objective)
        if objective is None:
            # Guard before touching the database: no network is needed to
            # know that "quickest" is not an objective.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown objective {request.objective!r}. "
                    f"Expected one of {', '.join(sorted(OBJECTIVES))}."
                ),
            )

        # Built once per process, not per request. The direct fix for
        # Create_graph rebuilding the whole graph from SQL inside the search.
        network = await graph_loader.get_network(session)

        # Named separately so the message can say which end was wrong. "One of
        # your stations does not exist" is not a useful thing to tell someone.
        if request.origin not in network:
            raise HTTPException(
                status_code=404, detail=f"Unknown station {request.origin!r}"
            )
        if request.destination not in network:
            raise HTTPException(
                status_code=404, detail=f"Unknown station {request.destination!r}"
            )

        # Lines with no trains on them, merged into whatever the caller asked
        # to avoid. Only closures and suspensions - a delay is reported on
        # /status and never silently rewrites a journey, because Severe Delays
        # often clears within the hour and rerouting someone around a line
        # that is still moving gives them a worse trip for nothing.
        disrupted = await status_poller.not_running_lines()
        avoided = sorted(disrupted)

        result = find_route(
            network,
            RouteQuery(
                origin=request.origin,
                destination=request.destination,
                objective=objective,
                avoid_lines=frozenset(request.avoid_lines) | disrupted,
            ),
        )

        if isinstance(result, Route):
            return _to_response(network, result, avoided)

        # Real stations, no journey between them. A 200 with a reason: the
        # question was well-formed and this is its answer. The avoided list
        # goes out here too - "no route" and "no route while the Piccadilly is
        # suspended" are different answers and a caller should see which.
        return RouteResponse(
            found=False, reason=result.reason, avoided_for_disruption=avoided
        )

    except HTTPException:
        # First, or the handler below swallows the 404 and reports it as a 500.
        raise
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
