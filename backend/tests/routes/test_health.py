"""
Tests for GET /health.

WHY THIS EXISTS
    /health is the only endpoint in Phase 0, and the thing worth testing
    about it is not that it returns 200 - it is that it tells the truth about
    the database when the database is gone. A health check that reports "ok"
    unconditionally is worse than no health check, because it is trusted.

NO 2021 EQUIVALENT
    There were no tests of any kind.
"""

from httpx import AsyncClient


async def test_health_returns_ok_when_database_answers(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "version": "0.1.0"}


async def test_health_reports_degraded_when_database_is_unreachable(
    client_db_down: AsyncClient,
) -> None:
    response = await client_db_down.get("/health")

    # 200, not 500. The question is "what is your state", and refusing to
    # answer it is not a useful reply - Docker's healthcheck and the frontend
    # both read this body.
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "database": "unreachable",
        "version": "0.1.0",
    }


async def test_health_payload_has_exactly_the_documented_keys(
    client: AsyncClient,
) -> None:
    # The frontend renders these three fields by name. Adding a key is
    # harmless; removing or renaming one breaks it silently, so the contract
    # is pinned here rather than only in the schema.
    response = await client.get("/health")

    assert set(response.json()) == {"status", "database", "version"}
