"""
GET /places/{naptan_id} and GET /places/{naptan_id}/streetview.

WHY THIS EXISTS
    A journey planner that stops at the station has answered a narrower
    question than the one people have. This is the other end of it: you have
    arrived, what is here.

    It is also the only endpoint in this service that costs money per call,
    which is why the cache and the guard clauses are the interesting parts
    rather than the query.

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

import base64
import logging

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy.exc import OperationalError

from app.core import cache
from app.core.config import SettingsDep
from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.places import Place, PlacesResponse
from app.services import stations as station_service
from app.services.places import KINDS, GoogleMapsClient, PlacesError

router = APIRouter(prefix="/places", tags=["places"])

# The only logger in the backend, and it earns its place.
#
# Everything else here either answers or raises, so a failure is visible.
# This module is the exception: when Google refuses, the endpoint returns
# `available: false` and the page quietly shows one line - which is right for
# the reader and leaves the operator with no way to tell "no key" from "bad
# key" from "Google is down". All three look identical from outside.
#
# That is not the same trade core/cache.py makes. A swallowed Redis error
# still produces the correct answer from the source, so there is nothing to
# investigate. A swallowed 401 means a feature is off and nobody can say why,
# which cost two rounds of diagnosis to establish by hand.
logger = logging.getLogger(__name__)

# Versioned, as every cache key in this project is. A change to the field
# mask or to Place changes the shape of what is stored, and a v1 reader
# meeting a v0 entry is the bug that versioning exists to make impossible.
PLACES_KEY = "tube-router:places:v2"
STREET_VIEW_KEY = "tube-router:streetview:v1"


@router.get(
    "/{naptan_id}",
    response_model=PlacesResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def places_near(
    naptan_id: str,
    session: SessionDep,
    settings: SettingsDep,
    kind: str = Query(default="food", description="One of the five keys in KINDS."),
) -> PlacesResponse:
    """What is near a station.

    Args:
        naptan_id: TfL's station id, e.g. 940GZZLUHR5.
        session: Injected per request.
        settings: Injected per request.
        kind: Category - food, coffee, pubs, museums or see. Validated
            against the allow list before anything is spent, and expanded to
            several Google place types here rather than in the browser.

    Returns:
        Up to eight places, nearest first, with `available` saying whether we
        were able to look at all.

    Raises:
        HTTPException: 400 for an unknown kind, 404 for an unknown station,
            503 if the database is unreachable.
    """
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

        empty = PlacesResponse(available=False, station=naptan_id, kind=kind)

        # No key is a state, not an error. The whole feature is optional and
        # the project has to run for someone who has not got one.
        if not settings.google_maps_key:
            return empty

        cache_key = f"{PLACES_KEY}:{naptan_id}:{kind}"
        cached = await cache.read_json(cache_key)
        if cached is not None:
            return PlacesResponse(**cached)

        async with GoogleMapsClient(
            places_base_url=settings.google_places_base_url,
            street_view_base_url=settings.google_street_view_base_url,
            api_key=settings.google_maps_key,
            timeout_seconds=settings.google_maps_timeout_seconds,
            max_attempts=settings.google_maps_max_attempts,
        ) as client:
            try:
                found = await client.nearby(
                    latitude=station["lat"],
                    longitude=station["lon"],
                    types=KINDS[kind],
                    radius_metres=settings.google_places_radius_metres,
                    max_results=settings.google_places_max_results,
                )
            except PlacesError as exc:
                # Google being down is not this service being down. The route
                # is already on the page; this is an extra that goes quiet -
                # quiet on the page, and loud in the log, because the two
                # audiences need opposite things here.
                logger.warning("places lookup failed for %s: %s", naptan_id, exc)
                return empty

        answer = PlacesResponse(
            available=True,
            station=naptan_id,
            kind=kind,
            # A place with no name is not worth a row.
            places=[Place(**vars(p)) for p in found if p.name],
        )
        await cache.write_json(
            cache_key,
            answer.model_dump(),
            ttl_seconds=settings.google_places_cache_ttl_seconds,
        )
        return answer

    except HTTPException:
        raise
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
    """A photograph of the street outside a station.

    Args:
        naptan_id: TfL's station id.
        session: Injected per request.
        settings: Injected per request.

    Returns:
        A JPEG.

    Raises:
        HTTPException: 404 for an unknown station and for a station Google
            has no imagery for, 503 if the database is unreachable.

    404 rather than an empty 200, because unlike the list above there is no
    useful "we looked and found nothing" image to send. The page treats a
    failed image the way any page treats one: it shows nothing. The `<img>`
    never reaches the user's eye and nothing has to be explained.
    """
    try:
        station = await station_service.coordinates_for_naptan(session, naptan_id)
        if station is None:
            raise HTTPException(status_code=404, detail=f"No station {naptan_id}")

        if not settings.google_maps_key:
            raise HTTPException(status_code=404, detail="Street view is not configured")

        cache_key = f"{STREET_VIEW_KEY}:{naptan_id}"
        cached = await cache.read_json(cache_key)
        if cached is not None:
            # Stored base64 because Redis holds text and the cache helper
            # speaks JSON. A 400x200 JPEG is about 20KB, so a third more in
            # Redis is a trade worth making to reuse the helper rather than
            # add a bytes path to it for one caller.
            return _jpeg(base64.b64decode(cached))

        async with GoogleMapsClient(
            places_base_url=settings.google_places_base_url,
            street_view_base_url=settings.google_street_view_base_url,
            api_key=settings.google_maps_key,
            timeout_seconds=settings.google_maps_timeout_seconds,
            max_attempts=settings.google_maps_max_attempts,
        ) as client:
            try:
                image = await client.street_view(
                    latitude=station["lat"], longitude=station["lon"]
                )
            except PlacesError as exc:
                logger.warning("street view failed for %s: %s", naptan_id, exc)
                raise HTTPException(
                    status_code=404, detail="Street view unavailable"
                ) from exc

        if image is None:
            # No panorama there. Ordinary, and not a failure: plenty of
            # station entrances have never been driven past.
            raise HTTPException(status_code=404, detail="No imagery for this station")

        await cache.write_json(
            cache_key,
            base64.b64encode(image).decode("ascii"),
            ttl_seconds=settings.google_street_view_cache_ttl_seconds,
        )
        return _jpeg(image)

    except HTTPException:
        raise
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _jpeg(image: bytes) -> Response:
    """The image, with a cache header matching how long we keep it ourselves.

    A station entrance does not move, so the browser may hold it as long as
    Redis does. Without this the image is re-fetched from us on every open,
    which costs nothing in money and everything in feeling slow.
    """
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=2592000"},
    )
