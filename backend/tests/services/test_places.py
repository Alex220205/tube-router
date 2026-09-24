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

from app.services.places import KINDS, GoogleMapsClient, PlacesError

pytestmark = pytest.mark.anyio

NEARBY_BODY = {
    "places": [
        {
            "displayName": {"text": "Dishoom"},
            "formattedAddress": "12 Upper St Martin's Lane, London",
            "rating": 4.6,
            "userRatingCount": 9123,
            "location": {"latitude": 51.5117, "longitude": -0.1274},
            "accessibilityOptions": {"wheelchairAccessibleEntrance": True},
        },
        # No accessibilityOptions key at all, which is what Google sends for
        # the majority of places: nobody has ever recorded anything.
        {
            "displayName": {"text": "The Unrecorded Arms"},
            "formattedAddress": "1 Nowhere St, London",
            "location": {"latitude": 51.5117, "longitude": -0.1274},
        },
        # The key is present but this particular fact is not, which Google
        # also does.
        {
            "displayName": {"text": "Half Known Cafe"},
            "formattedAddress": "2 Nowhere St, London",
            "location": {"latitude": 51.5117, "longitude": -0.1274},
            "accessibilityOptions": {"wheelchairAccessibleParking": True},
        },
    ]
}


def client(handler, **kwargs) -> GoogleMapsClient:
    """A client wired to a MockTransport instead of the network."""
    return GoogleMapsClient(
        api_key=kwargs.pop("api_key", "test-key"),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


# A key in a query string is a key in every access log, proxy and browser
# history between here and Google. It is the same class of mistake as a key
# in a source file, which is the one this project exists to correct.
async def test_the_key_is_sent_as_a_header_and_never_in_the_url() -> None:
    """The whole argument of this phase, asserted rather than assumed."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request and answer with the sample places."""
        seen.append(request)
        return httpx.Response(200, json=NEARBY_BODY)

    async with client(handler) as maps:
        await maps.nearby(latitude=51.5, longitude=-0.1, types=KINDS["food"])

    request = seen[0]
    assert request.headers["X-Goog-Api-Key"] == "test-key"
    assert "test-key" not in str(request.url)
    assert "key=" not in str(request.url)

    # The field mask is what Google bills by, so it is part of the contract
    # rather than an optimisation. Every path here has a field on
    # schemas/places.Place and a reader on the page.
    assert request.headers["X-Goog-FieldMask"] == (
        "places.displayName,places.formattedAddress,places.rating,"
        "places.userRatingCount,places.location,places.accessibilityOptions,"
        "places.websiteUri,places.googleMapsUri"
    )


# Without it, every open of the panel on a machine with no key still
# reaches Google, gets a 403, retries it twice, and is billed for all
# three. The first sign would be an invoice.
async def test_a_blank_key_makes_no_request_at_all() -> None:
    """The line that stops an unconfigured deployment costing money."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Count a request, which should never be made."""
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=NEARBY_BODY)

    async with client(handler, api_key="") as maps:
        assert maps.configured is False
        assert (
            await maps.nearby(latitude=51.5, longitude=-0.1, types=KINDS["coffee"])
            == []
        )
        assert await maps.street_view(latitude=51.5, longitude=-0.1) is None

    assert calls == 0


async def test_a_server_error_is_retried_and_then_succeeds() -> None:
    """New code, not tfl.py's. A copied loop can be copied wrong."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Fail once with a 503, then answer."""
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=NEARBY_BODY)

    async with client(handler) as maps:
        found = await maps.nearby(
            latitude=51.5117, longitude=-0.1274, types=KINDS["food"]
        )

    assert attempts == 2
    assert [p.name for p in found][0] == "Dishoom"
    assert found[0].ratings == 9123

    # Asked for from the station the search was centred on, not returned by
    # Google. Dishoom is at the centre point here, so it is a few metres.
    assert found[0].metres is not None
    assert found[0].metres < 50


# Retrying a 400 is being wrong three times more slowly, and paying for each
# one. 403 is the same: a rejected key is still a rejected key on the third
# attempt.
async def test_a_client_error_is_not_retried() -> None:
    """A 4xx from Google is raised on the first attempt, never retried."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Refuse every request with a 403."""
        nonlocal attempts
        attempts += 1
        return httpx.Response(403, json={"error": {"message": "denied"}})

    async with client(handler) as maps:
        with pytest.raises(PlacesError, match="will not change on a retry"):
            await maps.nearby(latitude=51.5, longitude=-0.1, types=KINDS["food"])

    assert attempts == 1


# Most places on Earth have no accessibility data recorded. Google sends no
# `accessibilityOptions` key at all for those, and sends the key without
# `wheelchairAccessibleEntrance` for places where something else is known.
#
# Both must come back as None, not False. The page marks True and says
# nothing for None, so a False here would put "not accessible" on a
# restaurant nobody has ever checked - a confident lie about a real
# business, told to the one person who most needs it to be right.
#
# The field mask is asserted alongside it, because the whole feature is one
# path in that string and dropping it fails silently: every place would
# simply come back unrecorded, which looks exactly like a network where
# nobody has recorded anything.
async def test_accessibility_is_claimed_only_when_google_says_so() -> None:
    """True is a fact; absent is not a denial."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request and answer with the sample places."""
        seen.append(request)
        return httpx.Response(200, json=NEARBY_BODY)

    async with client(handler) as maps:
        found = await maps.nearby(
            latitude=51.5117, longitude=-0.1274, types=KINDS["food"]
        )

    assert "places.accessibilityOptions" in seen[0].headers["X-Goog-FieldMask"]

    by_name = {p.name: p.wheelchair_entrance for p in found}
    assert by_name["Dishoom"] is True
    assert by_name["The Unrecorded Arms"] is None
    assert by_name["Half Known Cafe"] is None


# A category is a human idea and Google's types are narrower than it: Table
# A files a pub apart from a bar, and a park apart from a garden and a
# historical landmark. Sending one type per category returned two places to
# eat at Epping and nothing at all to look at.
#
# This asserts the expansion reaches the request, because a category that
# quietly narrowed back to one type would still return a plausible short
# list and nothing would raise.
async def test_a_category_asks_for_every_type_it_covers() -> None:
    """The fix for a list that was empty outside zone 1."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request body and answer with the sample places."""
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, json=NEARBY_BODY)

    async with client(handler) as maps:
        await maps.nearby(latitude=51.5, longitude=-0.1, types=KINDS["see"])

    assert seen[0]["includedTypes"] == list(KINDS["see"])
    assert len(seen[0]["includedTypes"]) > 1

    # Every category is plural, or it is back to the bug this closed.
    assert all(len(types) > 1 for types in KINDS.values())
