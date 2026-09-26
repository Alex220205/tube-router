"""GET /status - what TfL currently says about every tube line."""

from fastapi import APIRouter, HTTPException

from app.routes import COMMON_RESPONSES
from app.schemas.status import StatusResponse
from app.services import status_poller

router = APIRouter(prefix="/status", tags=["status"])


# The lines and when they were fetched. When the poller has not run yet, or Redis is
# unreachable, `as_of` is null and `lines` is empty - a 200, not a 503.
@router.get(
    "",
    response_model=StatusResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def line_status() -> StatusResponse:
    """Live status for every tube line."""
    try:
        return StatusResponse(**await status_poller.current())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
