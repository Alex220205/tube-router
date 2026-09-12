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
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

# `cp .env.example .env` is the documented setup, so the test suite reads the
# same file rather than asking for a second, separate export. load_dotenv does
# not overwrite variables already in the environment, so CI — which sets them
# directly — still wins.
load_dotenv(REPO_ROOT / ".env")

# Where the schema tests point. Unset means they skip, so the suite still runs
# with nothing running. See .env.example.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Set before importing the application: database.py builds the engine at
# import time, which requires DATABASE_URL to exist.
#
# When TEST_DATABASE_URL is set it becomes DATABASE_URL, overriding whatever
# .env said. That keeps the Phase 1 non-negotiable intact: Alembic reads its
# URL from app.config, so pointing the application at the test database is
# what points the migrations at it too, and there is still exactly one source
# of connection settings. The override has to be unconditional — .env sets
# DATABASE_URL to the compose hostname `db`, which does not resolve from here.
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
else:
    # A URL that parses and is never dialled: every endpoint test overrides
    # the session dependency.
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
    )

os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

from collections.abc import AsyncIterator, Iterator  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

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


# --- Schema tests: a real database ------------------------------------------


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Bring the test database up to head, once per session.

    Synchronous on purpose. Alembic's env.py calls asyncio.run(), which fails
    if there is already a running loop — so this must not be an async fixture.

    Yields:
        The URL of a database whose schema is at head.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is unset")

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")

    yield TEST_DATABASE_URL

    # The schema is left in place. Re-running upgrade on the next session is a
    # no-op, and CI gets a fresh container every time regardless.


@pytest.fixture
async def db(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """A session whose work is discarded when the test ends.

    The session runs inside a transaction that is always rolled back, so a
    test can insert whatever it likes — including rows that violate a
    constraint — without leaking into the next one. That matters more than
    usual here: several tests deliberately abort their transaction, and
    without the rollback the database would carry that state forward.

    Yields:
        A session bound to an open transaction on the test database.
    """
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
