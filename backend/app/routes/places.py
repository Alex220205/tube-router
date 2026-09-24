"""
GET /places/{naptan_id} and GET /places/{naptan_id}/streetview.

WHY THIS EXISTS
    A journey planner that stops at the station has answered a narrower
    question than the one people have. This is the other end of it: you have
    arrived, what is here.

    It is also the only endpoint in this service that costs money per call,
    which is why the guard clauses here, and the cache behind them in
    services/lookups.py, are the interesting parts rather than the query.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, lines 239 and 276
    How:    Built a Places URL inline with the key as a literal and called it
            from the GUI thread, twice, in two places.
    Wrong:  The key was in the source and therefore in every commit; there
            was no timeout, so a slow Google froze the window; and there was
            no boundary, so the raw response was rendered directly.

WHAT CHANGED AND WHY
    The browser sends a NaPTAN id and nothing else. The coordinates come out
    of Postgres here, which means the browser cannot ask Google about
    somewhere that is not a Tube station, and this endpoint cannot be turned
    into an open proxy for arbitrary lookups by anyone who finds it.

    The key stays on this side entirely, the image included. What the page
    gets is a URL on our own host.

WHAT'S NEW
    `available`, and the three empty answers it separates.

    No key, Google unreachable, and a station with genuinely nothing near it
    all produce an empty list, and they are not the same statement. The first
    two mean "we did not look"; the third means "we looked". A client that
    cannot tell them apart either shows an error because a credential is
    missing, or tells someone that central London has no restaurants.

    This is the opposite of what routes/status.py does, where an unknown
    state must never be rendered as good service, and the two are
    reconcilable: a wrong line status sends someone to a platform with no
    trains, and a wrong restaurant list costs nothing. The rule is not
    "always report uncertainty loudly", it is "never let a guess look like an
    answer" - here the honest move is to say nothing at all.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy.exc import OperationalError

from app.core.config import SettingsDep
from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.places import PlacesResponse
from app.services import lookups
from app.services import stations as station_service
from app.services.places import KINDS, PlacesError

router = APIRouter(prefix="/places", tags=["places"])


# naptan_id: TfL's station id, e.g. 940GZZLUHR5.
# session: Injected per request.
# settings: Injected per request.
# kind: Category - food, coffee, pubs, museums or see. Validated
#     against the allow list before anything is spent, and expanded to
#     several Google place types here rather than in the browser.
#
# Up to eight places, nearest first, with `available` saying whether we
# were able to look at all.
#
# HTTPException: 400 for an unknown kind, 404 for an unknown station,
#     503 if the database is unreachable.
@router.get(
    "/{naptan_id}",
    response_model=PlacesResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def places_near(
    naptan_id: str,
    session: SessionDep,
    settings: SettingsDep,
    kind: Annotated[str, Query(description="One of the five keys in KINDS.")] = "food",
) -> PlacesResponse:
    """What is near a station."""
    try:
        # Guard clauses before the database, and the database before Google.
        # Each step is more expensive than the one above it, and the last one
        # is the only one with a price.
        if kind not in KINDS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown kind {kind!r}. Expected one of {sorted(KINDS)}.",
            )

        station = await station_service.coordinates_for_naptan(session, naptan_id)
        if station is None:
            raise HTTPException(status_code=404, detail=f"No station {naptan_id}")

        return await lookups.places_near(settings, naptan_id, station, kind)

    except HTTPException:
        raise
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 404 rather than an empty 200, because unlike the list above there is no
# useful "we looked and found nothing" image to send. The page treats a
# failed image the way any page treats one: it shows nothing. The `<img>`
# never reaches the user's eye and nothing has to be explained.
#
# HTTPException: 404 for an unknown station and for a station Google
#     has no imagery for, 503 if the database is unreachable.
@router.get(
    "/{naptan_id}/streetview",
    responses={
        **COMMON_RESPONSES,
        200: {"description": "OK", "content": {"image/jpeg": {}}},
    },
)
async def street_view(
    naptan_id: str, session: SessionDep, settings: SettingsDep
) -> Response:
    """A photograph of the street outside a station."""
    try:
        station = await station_service.coordinates_for_naptan(session, naptan_id)
        if station is None:
            raise HTTPException(status_code=404, detail=f"No station {naptan_id}")

        if not settings.google_maps_key:
            raise HTTPException(status_code=404, detail="Street view is not configured")

        try:
            image = await lookups.street_view_of(settings, naptan_id, station)
        except PlacesError as exc:
            raise HTTPException(
                status_code=404, detail="Street view unavailable"
            ) from exc

        if image is None:
            # No panorama there. Ordinary, and not a failure: plenty of
            # station entrances have never been driven past.
            raise HTTPException(status_code=404, detail="No imagery for this station")

        return _jpeg(image)

    except HTTPException:
        raise
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# A station entrance does not move, so the browser may hold it as long as
# Redis does. Without this the image is re-fetched from us on every open,
# which costs nothing in money and everything in feeling slow.
def _jpeg(image: bytes) -> Response:
    """The image, with a cache header matching how long we keep it ourselves."""
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=2592000"},
    )
