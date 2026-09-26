"""Tests for GET /places/{naptan_id}."""

import os

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.main import app
from app.models import Station


# `kind` ends up inside a request that Google bills for, so an arbitrary string must not
# reach them. This runs against the fake session from conftest, which proves the
# rejection happens before the database and therefore before anything is spent.
async def test_an_unrecognised_kind_is_rejected_before_any_call(
    client: AsyncClient,
) -> None:
    """A 400, from a session that would raise if it were used."""
    response = await client.get("/places/940GZZLUHR5", params={"kind": "casino"})

    assert response.status_code == 400
    assert "casino" in response.json()["detail"]


# It must be a 200 the page can quietly ignore, because a 500 would render an error
# banner over a missing credential the reader can do nothing about.
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
