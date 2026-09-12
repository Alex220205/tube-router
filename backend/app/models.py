"""
SQLAlchemy models — the database schema as Python.

WHY THIS EXISTS
    One declarative definition of every table, which Alembic compares against
    the live database to generate migrations, and which the query layer uses
    to build SQL. Without it the schema would exist only in migration files
    and there would be nothing to check the database against.

WHAT THE 2021 VERSION DID
    Where:  train_stations.db, and SQL string literals scattered through
            database[works].py
    How:    Four tables created by hand, presumably in a GUI tool, with the
            application referring to them through inline SQL strings.
    Wrong:  There was no definition of the schema anywhere in version
            control, so it could not be reviewed, reproduced, or checked.
            One consequence is recorded in docs/AUDIT.md: the train_stations
            table was created with the commas missing, so SQLite parsed it as
            a single column named `longitude` whose declared type was the
            literal string "REAL\\n latitude REAL\\n name TEXT". No error was
            raised and it sat empty for five years.

WHAT CHANGED AND WHY
    The schema is code, reviewed in a pull request and applied by migration.
    A malformed definition now fails at import rather than silently producing
    a table that is not what it looks like.

    Every table carries constraints. The 2021 schema had none at all beyond
    primary keys — foreign keys were declared but SQLite does not enforce
    them unless PRAGMA foreign_keys is set per connection, which the
    application never did. Every guarantee therefore lived in application
    code, and the application did not enforce them either. That is the direct
    cause of the 12 zero-duration links and the two detached Central line
    branches the audit found.

WHAT'S NEW
    Phase 1 defines the declarative base and nothing else. The five tables
    arrive in the next two commits so that each one lands with its migration
    and its constraint tests together.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every model in the schema.

    Alembic's env.py points `target_metadata` at `Base.metadata`, so a model
    that does not inherit from this is invisible to autogenerate.
    """
