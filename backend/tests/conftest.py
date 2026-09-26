"""Shared test fixtures for the backend suite."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

# `cp .env.example .env` is the documented setup, so the test suite reads the same file
# rather than asking for a second, separate export. load_dotenv does not overwrite
# variables already in the environment, so CI - which sets them directly - still wins.
load_dotenv(REPO_ROOT / ".env")

# Where the schema tests point. Unset means they skip, so the suite still runs with
# nothing running. See .env.example.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Set before importing the application: database.py builds the engine at import time,
# which requires DATABASE_URL to exist.
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
else:
    # A URL that parses and is never dialled: every endpoint test overrides the session
    # dependency.
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
    )

os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

# Point the cache at a port nothing listens on. .env names the compose hostname
# `redis`, which does not resolve outside Docker, and a failed DNS lookup is not
# covered by the socket timeout; localhost refuses instantly.
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"

from collections.abc import AsyncIterator, Iterator  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import graph_loader  # noqa: E402


class FakeSession:
    """Stands in for AsyncSession. Answers queries, or refuses to."""

    def __init__(self, *, reachable: bool = True) -> None:
        """Behave as a database that does or does not answer."""
        self.reachable = reachable

    async def execute(self, statement: Any) -> None:
        """Pretend to run a statement."""
        if not self.reachable:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def _client_with(*, reachable: bool) -> AsyncClient:
    """An API client whose database is a fake that does or does not answer."""

    async def override_get_db() -> AsyncIterator[FakeSession]:
        """Hand every request the fake session instead of a real one."""
        yield FakeSession(reachable=reachable)

    app.dependency_overrides[get_db] = override_get_db
    # ASGITransport drives the app in-process. No socket, no uvicorn, no port to collide
    # with a stack that happens to be running.
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


# Synchronous on purpose. Alembic's env.py calls asyncio.run(), which fails if there is
# already a running loop - so this must not be an async fixture.
@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Bring the test database up to head, once per session."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is unset")

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")

    yield TEST_DATABASE_URL

    # The schema is left in place. Re-running upgrade on the next session is a no-op,
    # and CI gets a fresh container every time regardless.


# get_network caches the built Network for the life of the process, which is right in
# production and wrong here: each test rolls its database back and seeds its own, so the
# second test to call /route would be answered from the first test's graph.
@pytest.fixture(autouse=True)
def fresh_network() -> Iterator[None]:
    """Drop the process-wide routing graph around every test."""
    graph_loader.forget()
    yield
    graph_loader.forget()


# get_db is overridden to hand back the *same* session the test is using, so rows a test
# flushes are visible to the endpoint it then calls, and the whole lot is rolled back
# afterwards. Without this the endpoint would open its own session, see an empty
# database, and every test would have to commit - leaving debris behind.
@pytest.fixture
async def api(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An HTTP client whose endpoints share the test's own transaction."""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        """Hand every request the test's own session, so its rows are visible."""
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


# The session runs inside a transaction that is always rolled back, so a test can insert
# whatever it likes - including rows that violate a constraint - without leaking into
# the next one. That matters more than usual here: several tests deliberately abort
# their transaction, and without the rollback the database would carry that state
# forward.
@pytest.fixture
async def db(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """A session whose work is discarded when the test ends."""
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            # A SAVEPOINT, because many of these tests provoke an IntegrityError on
            # purpose, and the session's own rollback would otherwise tear down the
            # transaction this fixture still holds.
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
