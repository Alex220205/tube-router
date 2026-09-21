"""
Tests for the Google Maps client.

WHY THIS EXISTS
    Four risks, and two of them are about money rather than correctness.

    A key that leaks into a URL is the 2021 defect wearing new clothes. A
    client that calls Google when no key is configured turns an unconfigured
    deployment into an invoice. A retry loop that retries a 400 pays three
    times to be wrong. A retry loop that does not retry a 503 gives up on a
    blip.

    None of the four raises anything when it goes wrong. The feature keeps
    working, and the only evidence is a bill or a log.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, lines 239 and 276
    How:    No tests of any kind. The key was in the source, the call was on
            the GUI thread, and there was no way to exercise either without a
            network and a live key.
    Wrong:  Untestable by construction. A test would have had to make a real,
            billed request.

WHAT CHANGED AND WHY
    The client takes an httpx transport, so every test here drives a
    MockTransport and none of them touches the network or costs anything.
    Same device as test_tfl.py, for the same reason: CI must not go red
    because someone else's server is having a bad afternoon, and it must
    certainly not spend money.
"""

import httpx
import pytest

from app.services.places import GoogleMapsClient, PlacesError

pytestmark = pytest.mark.anyio

NEARBY_BODY = {
    "places": [
        {
            "displayName": {"text": "Dishoom"},
            "formattedAddress": "12 Upper St Martin's Lane, London",
            "rating": 4.6,
            "userRatingCount": 9123,
            "location": {"latitude": 51.5117, "longitude": -0.1274},
        }
    ]
}


def client(handler, **kwargs) -> GoogleMapsClient:
    """A client wired to a MockTransport instead of the network."""
    return GoogleMapsClient(
        api_key=kwargs.pop("api_key", "test-key"),
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        **kwargs,
    )


async def test_the_key_is_sent_as_a_header_and_never_in_the_url() -> None:
    """The whole argument of this phase, asserted rather than assumed.

    A key in a query string is a key in every access log, proxy and browser
    history between here and Google. It is the same class of mistake as a key
    in a source file, which is the one this project exists to correct.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=NEARBY_BODY)

    async with client(handler) as maps:
        await maps.nearby(latitude=51.5, longitude=-0.1, kind="restaurant")

    request = seen[0]
    assert request.headers["X-Goog-Api-Key"] == "test-key"
    assert "test-key" not in str(request.url)
    assert "key=" not in str(request.url)

    # The field mask is what Google bills by, so it is part of the contract
    # rather than an optimisation. Every path here has a field on
    # schemas/places.Place and a reader on the page.
    assert request.headers["X-Goog-FieldMask"] == (
        "places.displayName,places.formattedAddress,places.rating,"
        "places.userRatingCount,places.location"
    )


async def test_a_blank_key_makes_no_request_at_all() -> None:
    """The line that stops an unconfigured deployment costing money.

    Without it, every open of the panel on a machine with no key still
    reaches Google, gets a 403, retries it twice, and is billed for all
    three. The first sign would be an invoice.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=NEARBY_BODY)

    async with client(handler, api_key="") as maps:
        assert maps.configured is False
        assert await maps.nearby(latitude=51.5, longitude=-0.1, kind="cafe") == []
        assert await maps.street_view(latitude=51.5, longitude=-0.1) is None

    assert calls == 0


async def test_a_server_error_is_retried_and_then_succeeds() -> None:
    """New code, not tfl.py's. A copied loop can be copied wrong."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=NEARBY_BODY)

    async with client(handler) as maps:
        found = await maps.nearby(latitude=51.5, longitude=-0.1, kind="restaurant")

    assert attempts == 2
    assert [p.name for p in found] == ["Dishoom"]
    assert found[0].ratings == 9123


async def test_a_client_error_is_not_retried() -> None:
    """Retrying a 400 is being wrong three times more slowly, and paying for
    each one. 403 is the same: a rejected key is still a rejected key on the
    third attempt."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(403, json={"error": {"message": "denied"}})

    async with client(handler) as maps:
        with pytest.raises(PlacesError, match="will not change on a retry"):
            await maps.nearby(latitude=51.5, longitude=-0.1, kind="restaurant")

    assert attempts == 1
