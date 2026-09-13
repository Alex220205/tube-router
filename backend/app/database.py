"""
The database engine, the connection pool, and one session per request.

WHY THIS EXISTS
    Opening a connection to Postgres is expensive, and a request needs a
    transaction boundary that matches its own lifetime: everything commits or
    nothing does. This file creates the pool once at import and hands out a
    fresh session per request through a FastAPI dependency, so no handler is
    ever responsible for closing one.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, throughout — including Traversal.Create_graph
            at lines 472-529
    How:    Every method that touched data opened its own sqlite3 connection,
            ran SQL inline, and closed it. There was no pool, no session and
            no transaction spanning more than a single statement.
    Wrong:  Database access was scattered across every layer, including
            inside the graph builder, which is why routing could not run
            without a live database file and was therefore never tested. It
            also meant a full table scan per call with no shared connection:
            DisplayStationdatabase() ran inside a triple-nested loop at lines
            507-515, on every search.

WHAT CHANGED AND WHY
    Connections live in one pool, sessions are scoped to a request by
    get_db(), and the only code permitted to use them is the web service.
    The routing engine never sees a session — backend/app/graph_loader.py
    (Phase 6) queries, converts rows to engine dataclasses, and hands those
    across. A Session is the most contagious object in a web application:
    once a function takes one, everything it calls can trigger SQL at
    unpredictable times and needs a database in order to be tested.

WHAT'S NEW
    Async. The 2021 project was synchronous desktop code where blocking was
    invisible because there was one user. This service spends nearly all its
    time waiting on Postgres and, from Phase 7, on TfL, so an event loop is
    close to free concurrency.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    # Small on purpose. Postgres becomes unhappy well before the number of
    # concurrent requests would suggest, and sessions borrow a connection
    # only while they are actually running SQL.
    pool_size=5,
    max_overflow=10,
    # Checks a pooled connection is alive before handing it out. Costs a
    # round trip; avoids the stale-connection error after the database
    # restarts, which is routine during development.
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a database session scoped to one request.

    Used as a FastAPI dependency. The session is closed and its connection
    returned to the pool on the way out, including when the handler raises.

    Yields:
        An AsyncSession bound to the shared engine.
    """
    async with SessionLocal() as session:
        yield session
