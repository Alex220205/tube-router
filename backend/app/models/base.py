"""
The declarative base every model inherits from, and the naming convention applied to
every constraint.
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
# `ck` interpolates constraint_name, so every CheckConstraint still needs one: an
# unnamed check would render as `ck_segments_` and collide with the next.
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
