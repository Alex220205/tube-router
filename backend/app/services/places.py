"""
The Google Maps client. The only file in this project that talks to Google.

WHY THIS EXISTS
    Same argument as services/tfl.py: one outbound call site means the
    timeout, the retry policy, the field mask and the key are decided once
    rather than at each caller. Everything downstream is then a pure function
    over a payload, which is what lets the tests drive a MockTransport and
    never touch the network.

    It matters more here than it did for TfL, because these calls are billed.
    A retry policy scattered across call sites is a bill scattered across
    call sites.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, lines 239 and 276
    How:    Built a Places URL inline, twice, with the API key written into
            the string as a literal. Called it synchronously from the Tkinter
            event loop with no timeout and no error handling.
    Wrong:  Three things.
            1. The key was in the source, so it is in every copy of the file
               and in every commit that ever contained it. It cannot be
               rotated by changing a setting; it can only be revoked.
            2. No timeout, on the GUI thread. A slow answer from Google froze
               the whole window, and the user could not tell that from a
               crash.
            3. Two call sites meant two places to change the URL and two
               places to forget.

WHAT CHANGED AND WHY
    The key arrives from Settings, which reads the environment, and it goes
    in a header rather than a query string because Google supports one and a
    key in a URL is a key in an access log. Blank is a supported state: the
    client makes no request at all and the caller answers "unavailable",
    which is what keeps the project runnable by someone who has no key.

    Async with a timeout, so a slow Google delays one collapsed panel rather
    than the page. Retries transport failures, 5xx and 429, and nothing else.

WHAT'S NEW
    The field mask, which has no 2021 equivalent because the legacy Places
    API did not have one. Google bills by which fields are requested, so the
    mask is the price of a call written down in one place. Adding a field to
    schemas/places.py without adding it here returns null; adding it here
    without a reader spends money on nothing.

    And the free metadata check before any Street View image. Google charge
    for the image and not for asking whether one exists, and a location with
    no coverage returns a grey "no imagery" placeholder that costs exactly
    the same as a real photograph.
"""

import asyncio
import math
from dataclasses import dataclass
from typing import Any

import httpx

TOO_MANY_REQUESTS = 429

# Google does not send Retry-After on 429 for these APIs, so there is nothing
# to honour and this is the whole policy. Shorter than TfL's 30s because
# their quota window is per second and per day rather than per minute.
RATE_LIMIT_PAUSE = 2.0

# What to ask Nearby Search for. Every path here has a field in
# schemas/places.py and a reader in the frontend; Google bills by field, so
# an unused one is money spent on nothing.
FIELD_MASK = ",".join(
    (
        "places.displayName",
        "places.formattedAddress",
        "places.rating",
        "places.userRatingCount",
        "places.location",
    )
)

# The five categories the UI offers, and the Google place types each one
# expands to. Every string on the right is from Table A of Google's place
# type list, checked against their documentation rather than guessed.
#
# ONE CATEGORY IS SEVERAL TYPES, and that is the whole point. The first
# version sent a single type and it was close to useless outside zone 1: at
# Epping, "restaurant" within 500m returned two results and
# "tourist_attraction" returned nothing at all. Epping is not short of places
# to eat or things to look at - it is short of places Google files under
# exactly those two labels. Table A distinguishes a pub from a bar from a
# cocktail_bar, and a park from a garden from a historical_landmark, so
# asking for one of each pair is asking for a fraction of what is there.
#
# includedTypes accepts up to 50, so breadth here is free.
#
# The frontend keeps its own copy of the keys, for labels. This mapping is
# authoritative: the route answers 400 for any key not in it, and the browser
# never names a Google type at all.
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


@dataclass(frozen=True)
class Place:
    """One nearby place, flattened out of Google's nested response.

    Frozen for the same reason StationData is: it crosses the boundary out of
    this module and nothing downstream has any business editing it.

    `metres` is straight line from the station, computed here rather than
    asked for - Google does not return a distance, and the coordinates needed
    to work one out are already in the field mask and already paid for.
    """

    name: str
    address: str | None
    rating: float | None
    ratings: int | None
    metres: int | None


class GoogleMapsClient:
    """Reads Google Places and Street View. Knows nothing about this schema."""

    def __init__(
        self,
        *,
        places_base_url: str = "https://places.googleapis.com",
        street_view_base_url: str = "https://maps.googleapis.com",
        api_key: str = "",
        timeout_seconds: float = 5.0,
        max_attempts: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Build a client.

        Args:
            places_base_url: Root of the Places API (New).
            street_view_base_url: Root of the Street View Static API. Google
                splits these across two hosts.
            api_key: Blank means the feature is off. Nothing is requested and
                every method returns an empty answer, which is what
                `configured` exists to let callers report honestly.
            timeout_seconds: Applied per attempt, not to the total.
            max_attempts: Total attempts including the first.
            transport: Injected by tests. None means a real network.
        """
        self._places_base_url = places_base_url.rstrip("/")
        self._street_view_base_url = street_view_base_url.rstrip("/")
        self._api_key = api_key
        self._max_attempts = max_attempts
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    @property
    def configured(self) -> bool:
        """Whether there is a key at all.

        Checked by callers before doing anything, so that "no key" is a state
        the service reports rather than an error it raises. The project runs
        without one, as it already does without a TfL key.
        """
        return bool(self._api_key)

    async def __aenter__(self) -> "GoogleMapsClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        await self._client.aclose()

    # --- the request itself --------------------------------------------------

    async def _send(self, request: httpx.Request) -> httpx.Response:
        """Send a prepared request, retrying transport failures, 5xx and 429.

        Args:
            request: Built by the caller, so that a POST body and a GET query
                go through the same retry policy.

        Returns:
            The successful response.

        Raises:
            PlacesError: On a 4xx other than 429, or once attempts run out.

        The loop is deliberately the same shape as TfLClient._get rather than
        shared with it. Extracting it would mean editing a module the seed,
        the poller and nineteen tests depend on, to save twenty lines here.
        Copied code is tested code: the retry paths have their own tests.
        """
        label = f"{request.method} {request.url.path}"
        last: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            pause = 0.5 * attempt

            try:
                response = await self._client.send(request)
            except httpx.HTTPError as exc:
                # Timeouts and connection failures. Worth retrying: the
                # request may never have arrived.
                last = exc
            else:
                if response.status_code < 400:
                    return response

                if response.status_code == TOO_MANY_REQUESTS:
                    # Not "you were wrong", but "you were too quick". Waiting
                    # is the entire fix, and it is the only 4xx worth a retry.
                    last = PlacesError(f"{label} was rate limited")
                    pause = max(pause, RATE_LIMIT_PAUSE)
                elif response.status_code < 500:
                    # 400 means the body is wrong and 403 means the key is.
                    # Neither improves on a second attempt, and both are
                    # billed on every one of them.
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

    async def nearby(
        self,
        *,
        latitude: float,
        longitude: float,
        types: tuple[str, ...],
        radius_metres: float = 1500.0,
        max_results: int = 8,
    ) -> list[Place]:
        """Places of several related types near a point, nearest first.

        Args:
            latitude: WGS84.
            longitude: WGS84.
            types: Google place types, from one entry in KINDS. Several, not
                one, because a category is a human idea and Google's types
                are narrower than it.
            radius_metres: Google accepts 0 to 50,000.
            max_results: Google accepts 1 to 20.

        Returns:
            Up to max_results places, nearest first. Empty when Google found
            nothing, which is a real answer and not a failure.

        Raises:
            PlacesError: If Google could not be reached or answered oddly.

        rankPreference is DISTANCE rather than the default POPULARITY. The
        alternative would mean computing distances here and printing a
        walking time this service cannot actually know - Google orders by
        straight line too, but ordering is a weaker claim than a number.
        """
        if not self.configured:
            # No key, no request. This is the line that keeps an
            # unconfigured deployment from calling a billed API on every
            # page open.
            return []

        request = self._client.build_request(
            "POST",
            f"{self._places_base_url}/v1/places:searchNearby",
            headers={
                "Content-Type": "application/json",
                # A header, not a query parameter. Google supports both and
                # only one of them stays out of the access log.
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

        # Google omits `places` entirely when there are no results rather
        # than sending an empty array, so this cannot be payload["places"].
        return [
            _place(entry, latitude, longitude) for entry in payload.get("places", [])
        ]

    async def street_view(
        self, *, latitude: float, longitude: float, size: str = "400x200"
    ) -> bytes | None:
        """A photograph of the street at a point, or None if there is none.

        Args:
            latitude: WGS84.
            longitude: WGS84.
            size: Google's `size` parameter, width x height in pixels.

        Returns:
            JPEG bytes, or None when Google has no imagery there and when
            there is no key.

        Raises:
            PlacesError: If Google could not be reached.

        The metadata call first is not an optimisation, it is the difference
        between paying for a photograph and paying for a grey rectangle.
        Google charge for the image whether or not coverage exists, and
        charge nothing for asking: "metadata requests are available at no
        charge. No quota is consumed."
        """
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
            # ZERO_RESULTS is the ordinary case and is not an error: plenty
            # of station entrances have no panorama. REQUEST_DENIED and the
            # rest are configuration problems the caller reports as
            # unavailable rather than crashing a page over.
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


def _place(entry: dict[str, Any], from_lat: float, from_lon: float) -> Place:
    """One Google result, flattened, with how far it is from the station.

    Every field is optional on Google's side even when requested in the mask,
    so each is read defensively. A place with no name is not worth showing
    and gets an empty string the caller can drop.
    """
    location = entry.get("location") or {}
    lat, lon = location.get("latitude"), location.get("longitude")

    return Place(
        name=(entry.get("displayName") or {}).get("text", ""),
        address=entry.get("formattedAddress"),
        rating=entry.get("rating"),
        ratings=entry.get("userRatingCount"),
        metres=(
            None
            if lat is None or lon is None
            else _metres_between(from_lat, from_lon, lat, lon)
        ),
    )


# Mean Earth radius. Good to about 0.5% at these distances, which is well
# inside the error of "straight line from the station entrance" anyway.
_EARTH_RADIUS_M = 6_371_000.0


def _metres_between(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Great circle distance in metres, rounded.

    Straight line, not walking distance, and the page says so. Google does
    not return a distance from a Nearby Search and asking the Routes API for
    a real walking time would be a second billed call per result.

    Here rather than in PostGIS, which could do it exactly: these coordinates
    never touch the database, and a round trip per result to avoid six lines
    of trigonometry is the wrong shape.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return round(_EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
