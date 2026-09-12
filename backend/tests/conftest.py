"""
Shared test fixtures for the backend suite.

WHY THIS EXISTS
    The endpoint tests need an HTTP client and a database session, and need
    neither of them to be real. This file provides both, so the suite runs in
    CI with no Postgres container and no server process.

NO 2021 EQUIVALENT
    The old project had no tests. That is the central fact this rewrite is
    responding to: Traversal.Create_graph opened a database cursor inside the
    graph builder, so routing could not be exercised without a live SQLite
    file, so it never was, so the aliasing bug at line 532 survived five
    years.

WHAT'S NEW
    Dependency overrides. FastAPI resolves get_db through its injection
    system, which means a test can substitute a stand-in without the endpoint
    knowing. That is the practical payoff of injecting the session rather
    than importing it: the thing the test wants to control is already a seam.
"""

import os

# Set before importing the application: database.py builds the engine at
# import time, which requires DATABASE_URL to exist. Nothing ever connects to
# this address — every test overrides the session dependency — but a URL has
# to parse.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

from collections.abc import AsyncIterator  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402


class FakeSession:
    """Stands in for AsyncSession. Answers queries, or refuses to."""

    def __init__(self, *, reachable: bool = True) -> None:
        self.reachable = reachable

    async def execute(self, statement: Any) -> None:
        """Pretend to run a statement.

        Raises:
            OperationalError: when this session was built unreachable, which
                is what SQLAlchemy raises for a connection that is refused.
        """
        if not self.reachable:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def _client_with(*, reachable: bool) -> AsyncClient:
    async def override_get_db() -> AsyncIterator[FakeSession]:
        yield FakeSession(reachable=reachable)

    app.dependency_overrides[get_db] = override_get_db
    # ASGITransport drives the app in-process. No socket, no uvicorn, no port
    # to collide with a stack that happens to be running.
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client for an application whose database answers."""
    async with _client_with(reachable=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def client_db_down() -> AsyncIterator[AsyncClient]:
    """An HTTP client for an application whose database refuses connections."""
    async with _client_with(reachable=False) as c:
        yield c
    app.dependency_overrides.clear()
