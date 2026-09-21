"""
GET /geocode.

WHY THIS EXISTS
    To use this service you have had to know which station you want, which is
    precisely what somebody visiting London does not know. They know "British
    Museum". This is the endpoint that closes that gap, and it is the only
    change in the project that removes a requirement rather than adding a
    feature.

NO 2021 EQUIVALENT
    The old project used a Google key for places near a destination and
    nothing else. Its station entry was a text field over a list in the same
    process, and a name that was not in that list was simply not a journey it
    could plan.

WHAT'S NEW
    Two halves, and only the first costs money.

    Google resolves text to a point. PostGIS then finds the stations nearest
    that point, using the GIST index Phase 1 created and nothing has used
    until now. The second half never leaves this machine, so the expensive
    call happens once per distinct query and the cheap one happens per
    result.

    Every match is returned. "High Street" is seven places in Britain and
    picking one silently would plan a confident journey to the wrong one.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import OperationalError

from app.core import cache
from app.core.config import SettingsDep
from app.core.database import SessionDep
from app.routes import COMMON_RESPONSES
from app.schemas.geocode import GeocodeMatch, GeocodeResponse, NearbyStation
from app.services import stations as station_service
from app.services.places import GoogleMapsClient, PlacesError

router = APIRouter(prefix="/geocode", tags=["geocode"])

logger = logging.getLogger(__name__)

# Versioned like every cache key here. A week, because a museum does not move
# and the same handful of landmarks get searched over and over - but not
# forever, because a new development does appear and an address can be
# corrected.
GEOCODE_KEY = "tube-router:geocode:v1"
GEOCODE_TTL_SECONDS = 604_800

# Long enough for an address, short enough that nobody is posting an essay
# into a billed API.
MAX_QUERY_LENGTH = 120

# How many stations to offer per match. Three is enough to cover "the obvious
# one, and the two you might prefer"; more is a list to read rather than a
# choice to make.
STATIONS_PER_MATCH = 3

# Beyond this, a match is not somewhere this service can take you, and
# offering it would be worse than offering nothing.
#
# The reason it exists is a real failure, not a hypothetical. Google's
# `components=country:GB` does not make nonsense fail - it makes nonsense
# resolve to *Britain*. "zzzzqqqqxxxx" comes back as a confident match called
# "United Kingdom", at the country centroid in Scotland, and the endpoint
# then helpfully offered Chesham, 449km away. A wrong answer with a real
# address on it and a real station under it.
#
# Measured before choosing the number:
#
#   Heathrow Airport      410m       Bexleyheath      9,710m
#   Watford             1,467m       Biggin Hill     18,759m
#   Croydon             7,342m
#   ---------------------------------- 25km ----------------------------------
#   Brighton           64,523m       Manchester     226,393m
#   "zzzzqqqqxxxx"    449,534m
#
# 25km keeps every real place on the London fringe, including Biggin Hill
# which genuinely is nineteen kilometres from a tube station, and rejects
# everything that is not a journey this network can make.
MAX_STATION_DISTANCE_METRES = 25_000


def reachable(nearby: list[dict]) -> bool:
    """Whether a match is somewhere this network can take you.

    Args:
        nearby: The nearest stations to a match, nearest first, as
            `nearest_to` returns them.

    Returns:
        True when the closest station is inside MAX_STATION_DISTANCE_METRES.

    A named function for a one line condition, because it is the guard
    against the failure described above - a confident match at the centre of
    Scotland - and a condition buried in a loop is a condition nothing can
    test. Inverting it, or moving the constant, breaks nothing visible: the
    endpoint keeps answering 200 with plausible looking addresses.
    """
    return bool(nearby) and nearby[0]["metres"] <= MAX_STATION_DISTANCE_METRES


@router.get(
    "",
    response_model=GeocodeResponse,
    responses={**COMMON_RESPONSES, 200: {"description": "OK"}},
)
async def geocode(
    session: SessionDep,
    settings: SettingsDep,
    q: str = Query(description="Free text: a place, an address, a postcode."),
) -> GeocodeResponse:
    """Resolve typed text to places, each with the stations nearest to it.

    Args:
        session: Injected per request.
        settings: Injected per request.
        q: What the user typed.

    Returns:
        Every match Google recognised, most confident first, each carrying
        its nearest stations. `available` is false when we could not look.

    Raises:
        HTTPException: 400 for an empty or overlong query, 503 if the
            database is unreachable.
    """
    try:
        query = q.strip()

        # Guard clauses before the database, and the database before Google.
        # Each step costs more than the one above it and only the last one
        # has a price.
        if not query:
            raise HTTPException(status_code=400, detail="Nothing to search for")
        if len(query) > MAX_QUERY_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Search text is too long, maximum {MAX_QUERY_LENGTH}",
            )

        empty = GeocodeResponse(available=False, query=query)

        # No key is a state, not an error, exactly as in routes/places.py.
        if not settings.google_maps_key:
            return empty

        # Case folded, so "British Museum" and "british museum" are one entry
        # rather than two identical billed calls.
        cache_key = f"{GEOCODE_KEY}:{query.casefold()}"
        cached = await cache.read_json(cache_key)
        if cached is not None:
            return GeocodeResponse(**cached)

        async with GoogleMapsClient(
            places_base_url=settings.google_places_base_url,
            street_view_base_url=settings.google_street_view_base_url,
            geocoding_base_url=settings.google_geocoding_base_url,
            api_key=settings.google_maps_key,
            timeout_seconds=settings.google_maps_timeout_seconds,
            max_attempts=settings.google_maps_max_attempts,
        ) as client:
            try:
                found = await client.geocode(query)
            except PlacesError as exc:
                # Quiet on the page, loud in the log. The reader cannot act
                # on a rejected credential; whoever runs this can.
                logger.warning("geocode failed for %r: %s", query, exc)
                return empty

        # The nearest-station join is ours, not Google's, so it costs nothing
        # per match and happens after the single billed call rather than
        # inside a loop around one.
        matches = []
        for place in found:
            nearby = await station_service.nearest_to(
                session, place.latitude, place.longitude, STATIONS_PER_MATCH
            )

            # Dropped rather than returned with a warning. A match the
            # Underground cannot reach is not a destination this service has
            # an opinion about, and listing it invites a journey that does
            # not exist.
            if not reachable(nearby):
                continue

            matches.append(
                GeocodeMatch(
                    address=place.address,
                    latitude=place.latitude,
                    longitude=place.longitude,
                    stations=[NearbyStation(**row) for row in nearby],
                )
            )

        answer = GeocodeResponse(available=True, query=query, results=matches)
        await cache.write_json(
            cache_key, answer.model_dump(), ttl_seconds=GEOCODE_TTL_SECONDS
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
