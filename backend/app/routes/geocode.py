"""GET /geocode."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import OperationalError

from app.core.config import SettingsDep
from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.geocode import GeocodeResponse
from app.services import lookups

router = APIRouter(prefix="/geocode", tags=["geocode"])

# Long enough for an address, short enough that nobody is posting an essay into a billed
# API.
MAX_QUERY_LENGTH = 120


# Every match Google recognised, most confident first, each carrying its nearest
# stations. `available` is false when we could not look.
@router.get(
    "",
    response_model=GeocodeResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def geocode(
    session: SessionDep,
    settings: SettingsDep,
    q: Annotated[str, Query(description="Free text: a place, an address, a postcode.")],
) -> GeocodeResponse:
    """Resolve typed text to places, each with the stations nearest to it."""
    try:
        query = q.strip()

        # Guard clauses before anything that costs. An empty or overlong query never
        # reaches the database, let alone Google.
        if not query:
            raise HTTPException(status_code=400, detail="Nothing to search for")
        if len(query) > MAX_QUERY_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Search text is too long, maximum {MAX_QUERY_LENGTH}",
            )

        return await lookups.geocode_matches(session, settings, query)

    except HTTPException:
        raise
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
