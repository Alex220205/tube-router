"""Tests for GET /health."""

from httpx import AsyncClient


async def test_health_returns_ok_when_database_answers(client: AsyncClient) -> None:
    """/health returns ok when the database answers."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "version": "0.1.0"}


async def test_health_reports_degraded_when_database_is_unreachable(
    client_db_down: AsyncClient,
) -> None:
    """/health reports degraded when the database is unreachable."""
    response = await client_db_down.get("/health")

    # 200, not 500. The question is "what is your state", and refusing to answer it is
    # not a useful reply - Docker's healthcheck and the frontend both read this body.
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "database": "unreachable",
        "version": "0.1.0",
    }


async def test_health_payload_has_exactly_the_documented_keys(
    client: AsyncClient,
) -> None:
    """The /health payload has exactly the documented keys."""
    # The frontend renders these three fields by name. Adding a key is harmless;
    # removing or renaming one breaks it silently, so the contract is pinned here rather
    # than only in the schema.
    response = await client.get("/health")

    assert set(response.json()) == {"status", "database", "version"}
