"""The Google Maps client."""

import asyncio
import math
from dataclasses import dataclass
from typing import Any

import httpx

from app.schemas.places import Place

TOO_MANY_REQUESTS = 429

# Google does not send Retry-After on 429 for these APIs, so there is nothing to honour
# and this is the whole policy. Shorter than TfL's 30s because their quota window is per
# second and per day rather than per minute.
RATE_LIMIT_PAUSE = 2.0

# What to ask Nearby Search for. Every path here has a field in schemas/places.py and a
# reader in the frontend; Google bills by field, so an unused one is money spent on
# nothing.
FIELD_MASK = ",".join(
    (
        "places.displayName",
        "places.formattedAddress",
        "places.rating",
        "places.userRatingCount",
        "places.location",
        # Free, in the only sense that matters. Google bills Nearby Search by the most
        # expensive tier any requested field belongs to; accessibilityOptions is Pro,
        # and rating and userRatingCount above are already Enterprise. Adding it changes
        # the bill by nothing.
        "places.accessibilityOptions",
        # Somewhere to send people. websiteUri is the place's own site and is
        # Enterprise; googleMapsUri is its page on Google Maps and is Pro. Both are free
        # here for the same reason accessibilityOptions is: the mask already triggers
        # Enterprise through rating.
        "places.websiteUri",
        "places.googleMapsUri",
    )
)

# The five categories the UI offers, and the Google place types each one expands to.
# Every string on the right is from Table A of Google's place type list, checked against
# their documentation rather than guessed.
KINDS: dict[str, tuple[str, ...]] = {
    "food": ("restaurant", "meal_takeaway", "bakery"),
    "coffee": ("cafe", "coffee_shop", "bakery"),
    "pubs": ("pub", "bar"),
    "museums": ("museum", "art_gallery"),
    "see": (
        "tourist_attraction",
        "historical_landmark",
        "park",
        "garden",
        "performing_arts_theater",
    ),
}


class PlacesError(RuntimeError):
    """Google could not be reached, or answered with something unusable."""


# Where "here" is. Google will happily resolve a London place name to another continent
# - "Victoria" is a state in Australia, "Richmond" is in Virginia - and the result is a
# route planned from a real station to a real coordinate five thousand miles away, with
# nothing raising anywhere.
#
# Two guards, because either alone leaks: country:GB rules out the other continents,
# and the viewport biases matches within Britain towards Greater London.
UK_ONLY = "country:GB"
LONDON_BOUNDS = "51.28,-0.51|51.70,0.33"


@dataclass(frozen=True)
class GeocodedPlace:
    """A place name resolved to a point on the ground."""

    address: str
    latitude: float
    longitude: float


class GoogleMapsClient:
    """Reads Google Places and Street View, retrying what is worth retrying."""

    def __init__(
        self,
        *,
        places_base_url: str = "https://places.googleapis.com",
        street_view_base_url: str = "https://maps.googleapis.com",
        geocoding_base_url: str = "https://maps.googleapis.com",
        api_key: str = "",
        timeout_seconds: float = 5.0,
        max_attempts: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Build a client."""
        self._places_base_url = places_base_url.rstrip("/")
        self._street_view_base_url = street_view_base_url.rstrip("/")
        self._geocoding_base_url = geocoding_base_url.rstrip("/")
        self._api_key = api_key
        self._max_attempts = max_attempts
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    # Checked by callers before doing anything, so that "no key" is a state the service
    # reports rather than an error it raises. The project runs without one, as it
    # already does without a TfL key.
    @property
    def configured(self) -> bool:
        """Whether there is a key at all."""
        return bool(self._api_key)

    async def __aenter__(self) -> "GoogleMapsClient":
        """Open the client for an `async with` block."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the underlying HTTP client on the way out."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        await self._client.aclose()

    # --- the request itself --------------------------------------------------

    # The loop is deliberately the same shape as TfLClient._get rather than shared with
    # it. Extracting it would mean editing a module the seed, the poller and nineteen
    # tests depend on, to save twenty lines here. Copied code is tested code: the retry
    # paths have their own tests.
    async def _send(self, request: httpx.Request) -> httpx.Response:
        """Send a prepared request, retrying transport failures, 5xx and 429."""
        label = f"{request.method} {request.url.path}"
        last: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            pause = 0.5 * attempt

            try:
                response = await self._client.send(request)
            except httpx.HTTPError as exc:
                # Timeouts and connection failures. Worth retrying: the request may
                # never have arrived.
                last = exc
            else:
                if response.status_code < 400:
                    return response

                if response.status_code == TOO_MANY_REQUESTS:
                    # Not "you were wrong", but "you were too quick". Waiting is the
                    # entire fix, and it is the only 4xx worth a retry.
                    last = PlacesError(f"{label} was rate limited")
                    pause = max(pause, RATE_LIMIT_PAUSE)
                elif response.status_code < 500:
                    # 400 means the body is wrong and 403 means the key is. Neither
                    # improves on a second attempt, and both are billed on every one of
                    # them.
                    raise PlacesError(
                        f"{label} returned {response.status_code}, which will not "
                        f"change on a retry"
                    )
                else:
                    last = PlacesError(f"{label} returned {response.status_code}")

            if attempt < self._max_attempts:
                await asyncio.sleep(pause)

        raise PlacesError(
            f"{label} failed after {self._max_attempts} attempts"
        ) from last

    # --- endpoints -----------------------------------------------------------

    # rankPreference is DISTANCE rather than the default POPULARITY. The alternative
    # would mean computing distances here and printing a walking time this service
    # cannot actually know - Google orders by straight line too, but ordering is a
    # weaker claim than a number.
    async def nearby(
        self,
        *,
        latitude: float,
        longitude: float,
        types: tuple[str, ...],
        radius_metres: float = 1500.0,
        max_results: int = 8,
    ) -> list[Place]:
        """Places of several related types near a point, nearest first."""
        if not self.configured:
            # No key, no request. This is the line that keeps an unconfigured deployment
            # from calling a billed API on every page open.
            return []

        request = self._client.build_request(
            "POST",
            f"{self._places_base_url}/v1/places:searchNearby",
            headers={
                "Content-Type": "application/json",
                # A header, not a query parameter. Google supports both and only one of
                # them stays out of the access log.
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            json={
                "includedTypes": list(types),
                "maxResultCount": max_results,
                "rankPreference": "DISTANCE",
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": latitude, "longitude": longitude},
                        "radius": radius_metres,
                    }
                },
            },
        )

        response = await self._send(request)
        try:
            payload = response.json()
        except ValueError as exc:
            raise PlacesError("searchNearby returned a body that is not JSON") from exc

        # Google omits `places` entirely when there are no results rather than sending
        # an empty array, so this cannot be payload["places"].
        return [
            _place(entry, latitude, longitude) for entry in payload.get("places", [])
        ]

    # Matches, most confident first, biased to London. Empty when Google recognised
    # nothing and when there is no key.
    async def geocode(self, query: str, *, limit: int = 5) -> list[GeocodedPlace]:
        """Turn typed text into points on the ground."""
        if not self.configured:
            return []

        response = await self._send(
            self._client.build_request(
                "GET",
                f"{self._geocoding_base_url}/maps/api/geocode/json",
                params={
                    "address": query,
                    "components": UK_ONLY,
                    "bounds": LONDON_BOUNDS,
                    "key": self._api_key,
                },
            )
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PlacesError("geocode returned a body that is not JSON") from exc

        # Geocoding answers 200 with a status field rather than an HTTP error, so _send
        # cannot have caught this. ZERO_RESULTS is an ordinary answer - the text matched
        # nothing - and anything else is a problem worth raising so services/lookups.py
        # can log it.
        status = payload.get("status")
        if status == "ZERO_RESULTS":
            return []
        if status != "OK":
            raise PlacesError(
                f"geocode returned {status}: {payload.get('error_message', '')}"
            )

        return _geocoded(payload.get("results", [])[:limit], query)

    # The metadata call first is not an optimisation, it is the difference between
    # paying for a photograph and paying for a grey rectangle. Google charge for the
    # image whether or not coverage exists, and charge nothing for asking: "metadata
    # requests are available at no charge. No quota is consumed."
    async def street_view(
        self, *, latitude: float, longitude: float, size: str = "400x200"
    ) -> bytes | None:
        """A photograph of the street at a point, or None if there is none."""
        if not self.configured:
            return None

        metadata = await self._send(
            self._client.build_request(
                "GET",
                f"{self._street_view_base_url}/maps/api/streetview/metadata",
                params={
                    "location": f"{latitude},{longitude}",
                    "key": self._api_key,
                },
            )
        )
        try:
            status = metadata.json().get("status")
        except ValueError as exc:
            raise PlacesError("street view metadata was not JSON") from exc

        if status != "OK":
            # ZERO_RESULTS is the ordinary case and is not an error: plenty of station
            # entrances have no panorama. REQUEST_DENIED and the rest are configuration
            # problems the caller reports as unavailable rather than crashing a page
            # over.
            return None

        image = await self._send(
            self._client.build_request(
                "GET",
                f"{self._street_view_base_url}/maps/api/streetview",
                params={
                    "size": size,
                    "location": f"{latitude},{longitude}",
                    "key": self._api_key,
                },
            )
        )
        return image.content


# Every field is optional on Google's side even when requested in the mask, so each is
# read defensively. A place with no name is not worth showing and gets an empty string
# the caller can drop.
def _place(entry: dict[str, Any], from_lat: float, from_lon: float) -> Place:
    """One Google result, flattened, with how far it is from the station."""
    location = entry.get("location") or {}
    lat, lon = location.get("latitude"), location.get("longitude")

    # .get() twice rather than a default dict, because Google omits accessibilityOptions
    # entirely for a place nobody has recorded anything about - which is most of them -
    # and omits individual keys within it for the rest.
    access = entry.get("accessibilityOptions") or {}

    return Place(
        name=(entry.get("displayName") or {}).get("text", ""),
        address=entry.get("formattedAddress"),
        rating=entry.get("rating"),
        ratings=entry.get("userRatingCount"),
        wheelchair_entrance=access.get("wheelchairAccessibleEntrance"),
        website=_safe_url(entry.get("websiteUri")),
        maps_url=_safe_url(entry.get("googleMapsUri")),
        metres=(
            None
            if lat is None or lon is None
            else _metres_between(from_lat, from_lon, lat, lon)
        ),
    )


# https only, and rejected rather than coerced. These strings come from a third party
# and end up in an anchor's href, which is the one place a `javascript:` URL becomes
# code running on our origin.
def _safe_url(value: Any) -> str | None:
    """A URL only if it is one we are willing to put in an href."""
    if isinstance(value, str) and value.startswith("https://"):
        return value
    return None


# Mean Earth radius. Good to about 0.5% at these distances, which is well inside the
# error of "straight line from the station entrance" anyway.
_EARTH_RADIUS_M = 6_371_000.0


# Straight line, not walking distance, and the page says so. Google does not return a
# distance from a Nearby Search and asking the Routes API for a real walking time would
# be a second billed call per result.
def _metres_between(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Great circle distance in metres, rounded."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return round(_EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


# Every field is optional on Google's side, so each is read defensively, the same as
# _place. A result with no point is no use to a journey planner and is dropped rather
# than guessed at.
def _geocoded(results: list[dict[str, Any]], query: str) -> list[GeocodedPlace]:
    """Google's geocoding results as points, skipping any without one."""
    found = []
    for entry in results:
        location = (entry.get("geometry") or {}).get("location") or {}
        if location.get("lat") is None or location.get("lng") is None:
            continue
        found.append(
            GeocodedPlace(
                address=entry.get("formatted_address", query),
                latitude=location["lat"],
                longitude=location["lng"],
            )
        )
    return found
