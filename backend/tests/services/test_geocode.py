"""Tests for turning typed text into stations."""

import httpx
import pytest

from app.services.lookups import MAX_STATION_DISTANCE_METRES, reachable
from app.services.places import GoogleMapsClient

pytestmark = pytest.mark.anyio


def result(address: str, lat: float, lng: float) -> dict:
    """One geocoding result in Google's response shape."""
    return {
        "formatted_address": address,
        "geometry": {"location": {"lat": lat, "lng": lng}},
    }


def client(handler, **kwargs) -> GoogleMapsClient:
    """A client wired to a MockTransport instead of the network."""
    return GoogleMapsClient(
        api_key=kwargs.pop("api_key", "test-key"),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


# Google will resolve a bare London place name to another continent and report OK. The
# route then plans from a real station to a real coordinate five thousand miles away,
# and nothing anywhere raises: the address looks like an address and the coordinate
# looks like a coordinate.
async def test_a_geocode_is_pinned_to_britain_and_biased_to_london() -> None:
    """Without this, "Victoria" is a state in Australia."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request and answer with one match."""
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [result("Victoria, London, UK", 51.5, -0.1)],
            },
        )

    async with client(handler) as maps:
        await maps.geocode("Victoria")

    assert seen[0].url.params["components"] == "country:GB"
    assert seen[0].url.params["bounds"] == "51.28,-0.51|51.70,0.33"


async def test_every_match_comes_back_not_the_best_one() -> None:
    """ "High Street" is seven places and the user has to be told."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Answer with several matching streets."""
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    result("High St, Uxbridge, UK", 51.546, -0.478),
                    result("High St, Chesham, UK", 51.705, -0.611),
                    result("High St, Rickmansworth, UK", 51.638, -0.472),
                ],
            },
        )

    async with client(handler) as maps:
        found = await maps.geocode("High Street")

    assert len(found) == 3
    assert [p.address for p in found][0] == "High St, Uxbridge, UK"

    # ZERO_RESULTS is an ordinary answer, not a failure: the text matched nothing. It
    # must not raise, or "no such place" becomes an error page.
    def nothing(request: httpx.Request) -> httpx.Response:
        """Answer that nothing matched."""
        return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})

    async with client(nothing) as maps:
        assert await maps.geocode("qqqqqq") == []


# Without it, an unconfigured deployment reaches Google on every search, is rejected,
# retries, and is charged for each attempt. The first sign is an invoice rather than a
# bug report.
async def test_a_blank_key_makes_no_geocode_request() -> None:
    """Billing, and the same guard the places client has."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Count a request, which should never be made."""
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": "OK", "results": []})

    async with client(handler, api_key="") as maps:
        assert await maps.geocode("British Museum") == []

    assert calls == 0


# `components=country:GB` does not make nonsense fail. It makes nonsense resolve to
# *Britain*: "zzzzqqqqxxxx" came back as a match called "United Kingdom" at the country
# centroid, and the endpoint offered Chesham, 449km away. A real address, a real
# station, and a useless answer.
async def test_a_match_the_underground_cannot_reach_is_rejected() -> None:
    """The guard against a confident answer in the middle of Scotland."""
    assert reachable([{"metres": 410}]) is True  # Heathrow Airport
    assert reachable([{"metres": 9_710}]) is True  # Bexleyheath
    assert reachable([{"metres": 18_759}]) is True  # Biggin Hill

    assert reachable([{"metres": 64_523}]) is False  # Brighton
    assert reachable([{"metres": 449_534}]) is False  # the UK centroid

    # A station list that came back empty is not reachable either, and the check must
    # not raise on it.
    assert reachable([]) is False

    # The boundary itself is inclusive, so the constant means what it says.
    assert reachable([{"metres": MAX_STATION_DISTANCE_METRES}]) is True
    assert reachable([{"metres": MAX_STATION_DISTANCE_METRES + 1}]) is False
