"""
The declarative base every model inherits from, and the naming convention
applied to every constraint.

WHY THIS EXISTS
    One place that defines what "a model in this project" means. Alembic's
    env.py points target_metadata at Base.metadata, so a class that does not
    inherit from this is invisible to autogenerate — which produces an empty
    migration rather than an error, and is the single most common way an
    Alembic setup silently does nothing.

WHAT THE 2021 VERSION DID
    Where:  train_stations.db, created by hand
    How:    There was no definition of the schema in source at all. The tables
            existed only inside the database file.
    Wrong:  Nothing could be reviewed, reproduced or checked. docs/AUDIT.md
            records the consequence: the train_stations table was created with
            the commas missing, so SQLite parsed it as one column named
            `longitude` whose declared type was the literal string
            "REAL\\n latitude REAL\\n name TEXT". No error was raised and it
            sat empty for five years.

WHAT CHANGED AND WHY
    The schema is code, reviewed in a pull request and applied by migration.
    A malformed definition fails at import rather than producing a table that
    is not what it looks like.

WHAT'S NEW
    The naming convention. Postgres invents names for constraints you do not
    name, and those names vary with how the constraint was created, so a
    later migration wanting to drop or alter one has nothing reliable to
    reference. Setting it before any table existed cost one argument; after
    the fact it would cost a migration renaming every constraint in the
    database.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Applied to every constraint and index that is not explicitly named.
#
#   ix  index                 ix_stations_location
#   uq  unique constraint     uq_lines_code
#   ck  check constraint      ck_segments_seconds_positive
#   fk  foreign key           fk_segments_line_id_lines
#   pk  primary key           pk_stations
#
# `ck` interpolates constraint_name, so every CheckConstraint still has to be
# given one — an unnamed check would render as `ck_segments_` and collide with
# the next unnamed check on the same table.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every model in the schema."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
