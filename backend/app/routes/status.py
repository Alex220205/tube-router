"""
GET /status - what TfL currently says about every tube line.

WHY THIS EXISTS
    The map needs to colour eleven lines and the route panel needs to explain
    why it avoided one. Both want the same small payload, and neither should
    wait on TfL to get it - so this reads Redis and nothing else.

    **It never calls TfL.** That is the whole point of the poller: a page load
    must not depend on someone else's server being up, and an endpoint that
    fell back to a live fetch would be fast in testing and slow at exactly the
    moment a lot of people were looking at it.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, Line.AddLinedatabase and GUI
    How:    Status was read from the lines table, which was emptied and
            refilled on launch. There was no endpoint; the window read the
            database directly.
    Wrong:  The value was as old as the process. Start the program at nine and
            the "live" status still said nine o'clock at lunchtime, with
            nothing on screen to say so.

WHAT CHANGED AND WHY
    A poller refreshes it every minute and the response carries `as_of`, so a
    client can tell the difference between current, stale and unknown.
"""

from fastapi import APIRouter, HTTPException

from app.routes import COMMON_RESPONSES
from app.schemas.status import StatusResponse
from app.services import status_poller

router = APIRouter(prefix="/status", tags=["status"])


@router.get(
    "",
    response_model=StatusResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def line_status() -> StatusResponse:
    """Live status for every tube line.

    Returns:
        The lines and when they were fetched. When the poller has not run yet,
        or Redis is unreachable, `as_of` is null and `lines` is empty - a 200,
        not a 503.

        That follows Phase 3's rule for an empty station search: "I do not
        know yet" is a truthful answer to a well-formed question. A 503 would
        say the service is broken when it is working correctly, and would make
        the frontend render an error over a condition that resolves itself
        within a minute of startup.

    Raises:
        HTTPException: 500 if reading the cache fails in a way core/cache.py
            does not already absorb, which would mean a bug here rather than a
            missing dependency.
    """
    try:
        return StatusResponse(**await status_poller.current())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
