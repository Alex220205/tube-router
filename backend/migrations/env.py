"""
Alembic's entry point: how migrations find the database and what they compare
against.

WHY THIS EXISTS
    Alembic needs two things — a connection and a description of the intended
    schema. This file supplies both, and it takes the connection from the
    same place the running application does rather than from alembic.ini.

NO 2021 EQUIVALENT
    The old project had no migrations. The schema was created by hand in a
    tool, existed only inside train_stations.db, and changed by someone
    running ad-hoc SQL — several such statements survive commented out at the
    bottom of database[works].py, lines 972-976, including an UPDATE that
    repairs a single connection's line_id. There was no record of what the
    schema was, when it changed, or why.

WHAT'S NEW
    Two decisions worth stating.

    The URL comes from app.config.get_settings(), not from alembic.ini. One
    source of connection settings. A URL in the ini file would be a second
    one, free to disagree with the first, and the way that disagreement
    surfaces is a migration applied to the wrong database.

    include_object filters out spatial_ref_sys. PostGIS creates that table
    itself when the extension is enabled; autogenerate does not know it is
    not ours and would emit a DROP TABLE for it in every revision.
"""

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings

# Imports the models package, not just Base — which is what guarantees every
# model module has been executed and every table is registered on the
# metadata. See app/models/__init__.py; a model whose module is never imported
# is silently absent from autogenerate rather than an error.
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The single source of connection settings. See the module docstring.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata

# Tables PostGIS owns. Ours are everything else.
POSTGIS_TABLES = {"spatial_ref_sys", "geography_columns", "geometry_columns"}


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Decide whether autogenerate should consider a database object.

    Args:
        obj: The schema object being considered.
        name: Its name, if it has one.
        type_: What kind of object it is — "table", "column" and so on.
        reflected: Whether it came from the database rather than the models.
        compare_to: The corresponding object on the other side, if any.

    Returns:
        False for objects PostGIS owns, True for everything else.
    """
    return not (type_ == "table" and name in POSTGIS_TABLES)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it against a database.

    Used for generating a migration script to hand to a DBA. Not used here,
    but kept because removing it would mean `alembic upgrade --sql` fails
    with an unhelpful error rather than working.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on an already-open connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        # Without this, altering a column's type produces a migration that
        # Postgres accepts and that silently does nothing.
        compare_type=True,
        # Server-side defaults are otherwise invisible to autogenerate.
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async engine and run the migrations through it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for a normal `alembic upgrade`."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
