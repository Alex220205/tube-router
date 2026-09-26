"""The database engine, the connection pool, and one session per request."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    # Small on purpose. Postgres becomes unhappy well before the number of concurrent
    # requests would suggest, and sessions borrow a connection only while they are
    # actually running SQL.
    #
    # pool_size:     connections kept open permanently.
    # max_overflow:  extra connections allowed above pool_size before a
    #                request has to wait.
    # pool_timeout:  seconds to wait for one before raising, rather than
    #                hanging indefinitely under load.
    # pool_pre_ping: issues a cheap check before handing a connection out, so
    #                a connection the database has since dropped is recycled
    #                instead of failing the request. This is what let the API
    #                recover on its own when Postgres was stopped and started
    #                underneath it.
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# Used as a FastAPI dependency. The session is closed and its connection returned to the
# pool on the way out, including when the handler raises.
async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a database session scoped to one request."""
    async with SessionLocal() as session:
        yield session


# Declared here rather than in each route module, so every endpoint that needs a session
# spells it the same way and there is one place to change if the dependency ever does.
SessionDep = Annotated[AsyncSession, Depends(get_db)]


# Without this the process can exit holding open sockets to Postgres, which shows up as
# connections lingering on the server side after a restart.
async def dispose_engine() -> None:
    """Close every pooled connection. Called on application shutdown."""
    await engine.dispose()


# The cheapest possible round trip. The point is to prove the connection works end to
# end, not to read anything. It sits beside the session it is testing, so the health
# route can ask the question without writing any SQL itself.
async def ping(session: AsyncSession) -> None:
    """Make one round trip to the database, raising if it cannot."""
    await session.execute(text("SELECT 1"))
