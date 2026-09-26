"""Cached answers from Google about a station, or about somewhere typed in."""

import base64
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import Settings
from app.schemas.geocode import GeocodeMatch, GeocodeResponse, NearbyStation
from app.schemas.places import PlacesResponse
from app.services import stations as station_service
from app.services.places import KINDS, GeocodedPlace, GoogleMapsClient, PlacesError

# The only logger in the backend, and it earns its place.
#
# Everything else here either answers or raises, so a failure is visible. This module is
# the exception: when Google refuses, the endpoint returns `available: false` and the
# page quietly shows one line - which is right for the reader and leaves the operator
# with no way to tell "no key" from "bad key" from "Google is down".
logger = logging.getLogger(__name__)

# Versioned, as every cache key in this project is. A change to the field mask or to
# Place changes the shape of what is stored, and a v1 reader meeting a v0 entry is the
# bug that versioning exists to make impossible.
PLACES_KEY = "tube-router:places:v2"
STREET_VIEW_KEY = "tube-router:streetview:v1"

# A week, because a museum does not move and the same handful of landmarks get searched
# over and over - but not forever, because a new development does appear and an address
# can be corrected.
GEOCODE_KEY = "tube-router:geocode:v1"
GEOCODE_TTL_SECONDS = 604_800

# How many stations to offer per match. Three is enough to cover "the obvious one, and
# the two you might prefer"; more is a list to read rather than a choice to make.
STATIONS_PER_MATCH = 3

# Beyond this, a match is not somewhere the Underground can take you. Restricted to
# Britain, Google resolves nonsense to the middle of the country rather than failing,
# with a real address and a real station 450km away. 25km keeps every real place on
# the London fringe, Biggin Hill included, and rejects that.
MAX_STATION_DISTANCE_METRES = 25_000


# A named function for a one line condition, because it is the guard against a
# confident match in the middle of Scotland, and a condition buried in a loop is a
# condition nothing can test.
def reachable(nearby: list[dict]) -> bool:
    """Whether a match is somewhere this network can take you."""
    return bool(nearby) and nearby[0]["metres"] <= MAX_STATION_DISTANCE_METRES


def _client(settings: Settings) -> GoogleMapsClient:
    """A Google client configured from settings, the same for every lookup."""
    return GoogleMapsClient(
        places_base_url=settings.google_places_base_url,
        street_view_base_url=settings.google_street_view_base_url,
        geocoding_base_url=settings.google_geocoding_base_url,
        api_key=settings.google_maps_key,
        timeout_seconds=settings.google_maps_timeout_seconds,
        max_attempts=settings.google_maps_max_attempts,
    )


# No key is a state, not an error. The whole feature is optional and the project has to
# run for someone who has not got one.
async def places_near(
    settings: Settings, naptan_id: str, station: dict, kind: str
) -> PlacesResponse:
    """The places of one kind near a station, nearest first."""
    empty = PlacesResponse(available=False, station=naptan_id, kind=kind)
    if not settings.google_maps_key:
        return empty

    cache_key = f"{PLACES_KEY}:{naptan_id}:{kind}"
    cached = await cache.read_json(cache_key)
    if cached is not None:
        return PlacesResponse(**cached)

    async with _client(settings) as client:
        try:
            found = await client.nearby(
                latitude=station["lat"],
                longitude=station["lon"],
                types=KINDS[kind],
                radius_metres=settings.google_places_radius_metres,
                max_results=settings.google_places_max_results,
            )
        except PlacesError as exc:
            logger.warning("places lookup failed for %s: %s", naptan_id, exc)
            return empty

    answer = PlacesResponse(
        available=True,
        station=naptan_id,
        kind=kind,
        # A place with no name is not worth a row.
        places=[p for p in found if p.name],
    )
    await cache.write_json(
        cache_key,
        answer.model_dump(),
        ttl_seconds=settings.google_places_cache_ttl_seconds,
    )
    return answer


# Stored base64 because Redis holds text and the cache helper speaks JSON. A 400x200
# JPEG is about 20KB, so a third more in Redis is a trade worth making to reuse the
# helper rather than add a bytes path to it for one caller.
async def street_view_of(
    settings: Settings, naptan_id: str, station: dict
) -> bytes | None:
    """The street outside a station as a JPEG, or None where there is none."""
    cache_key = f"{STREET_VIEW_KEY}:{naptan_id}"
    cached = await cache.read_json(cache_key)
    if cached is not None:
        return base64.b64decode(cached)

    async with _client(settings) as client:
        try:
            image = await client.street_view(
                latitude=station["lat"], longitude=station["lon"]
            )
        except PlacesError as exc:
            logger.warning("street view failed for %s: %s", naptan_id, exc)
            raise

    if image is None:
        return None
    await cache.write_json(
        cache_key,
        base64.b64encode(image).decode("ascii"),
        ttl_seconds=settings.google_street_view_cache_ttl_seconds,
    )
    return image


# Two halves, and only the first costs money: Google resolves the text to points, and
# PostGIS finds the stations nearest each one.
async def geocode_matches(
    session: AsyncSession, settings: Settings, query: str
) -> GeocodeResponse:
    """Every place Google matches for the text, each with its nearest stations."""
    empty = GeocodeResponse(available=False, query=query)
    if not settings.google_maps_key:
        return empty

    # Case folded, so "British Museum" and "british museum" are one entry rather than
    # two identical billed calls.
    cache_key = f"{GEOCODE_KEY}:{query.casefold()}"
    cached = await cache.read_json(cache_key)
    if cached is not None:
        return GeocodeResponse(**cached)

    async with _client(settings) as client:
        try:
            found = await client.geocode(query)
        except PlacesError as exc:
            # Quiet on the page, loud in the log. The reader cannot act on a rejected
            # credential; whoever runs this can.
            logger.warning("geocode failed for %r: %s", query, exc)
            return empty

    matches = await _with_nearest_stations(session, found)
    answer = GeocodeResponse(available=True, query=query, results=matches)
    await cache.write_json(
        cache_key, answer.model_dump(), ttl_seconds=GEOCODE_TTL_SECONDS
    )
    return answer


# The nearest-station join is ours, not Google's, so it costs nothing per match and
# happens after the single billed call rather than inside a loop around one.
async def _with_nearest_stations(
    session: AsyncSession, found: list[GeocodedPlace]
) -> list[GeocodeMatch]:
    """Attach the nearest stations to each match, dropping any out of reach."""
    matches = []
    for place in found:
        nearby = await station_service.nearest_to(
            session, place.latitude, place.longitude, STATIONS_PER_MATCH
        )

        # Dropped rather than returned with a warning. A match the Underground cannot
        # reach is not a destination this service has an opinion about, and listing it
        # invites a journey that does not exist.
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
    return matches
