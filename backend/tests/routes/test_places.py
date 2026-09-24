"""
Tests for GET /places/{naptan_id}.

WHY THIS EXISTS
    Two risks, both about what happens when Google is not there.

    The first is the contract the page hides the section on. With no key
    configured this endpoint must answer 200 with `available: false`, because
    the frontend renders nothing at all on that and would render an error
    banner on a 500. A missing credential is not a fault the user can do
    anything about and should not be shown to them.

    The second is the guard clause. `kind` is interpolated into a billed
    request, so anything not on the allow list has to be rejected here rather
    than sent to Google to be rejected there and charged for.

NO 2021 EQUIVALENT
    There were no endpoints. The old project called Places inline from the
    GUI and had no concept of a request that could be validated before it
    was made.

CONSTRAINT
    The first test needs a real Postgres with PostGIS, because the endpoint
    looks a station up by NaPTAN id before it decides anything else. The
    second does not: it is rejected before the database is touched, which is
    the property being asserted.
"""

import os

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.main import app
from app.models import Station


# `kind` ends up inside a request that Google bills for, so an arbitrary
# string must not reach them. This runs against the fake session from
# conftest, which proves the rejection happens before the database and
# therefore before anything is spent.
async def test_an_unrecognised_kind_is_rejected_before_any_call(
    client: AsyncClient,
) -> None:
    """A 400, from a session that would raise if it were used."""
    response = await client.get("/places/940GZZLUHR5", params={"kind": "casino"})

    assert response.status_code == 400
    assert "casino" in response.json()["detail"]


# It must be a 200 the page can quietly ignore, because a 500 would render
# an error banner over a missing credential the reader can do nothing
# about.
#
# `available: false` with an empty list is also deliberately different from
# `available: true` with an empty list. The first says we did not look; the
# second says we looked and there was nothing. Collapsing them would have
# the page claim that central London has no restaurants whenever somebody
# forgot to set a key.
#
# THE KEY IS BLANKED EXPLICITLY, not left to the environment. The first
# version of this test relied on nobody having set GOOGLE_MAPS_KEY, and
# passed for exactly as long as that was true - the moment a real key
# landed in .env it started reaching Google, and would have billed for the
# privilege. That is the defect CODE_STYLE.md section 10 records from the
# WebSocket tests in Phase 8b, reproduced faithfully: a suite whose meaning
# depends on what else is configured on the machine.
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is unset - this needs a live Postgres with PostGIS",
)
async def test_no_key_answers_200_with_available_false_not_an_error(
    db: AsyncSession, api: AsyncClient
) -> None:
    """An absent credential is a state, not a failure."""
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://unused/unused",
        google_maps_key="",
    )

    db.add(
        Station(
            naptan_id="940GZZLUHR5",
            name="Heathrow Terminal 5 Underground Station",
            location="SRID=4326;POINT(-0.488 51.4723)",
        )
    )
    await db.flush()

    try:
        response = await api.get("/places/940GZZLUHR5", params={"kind": "food"})
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["places"] == []
    assert body["station"] == "940GZZLUHR5"
    assert body["kind"] == "food"
