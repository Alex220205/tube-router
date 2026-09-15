"""
Every model in the schema, re-exported from one place.

WHY THIS EXISTS
    Splitting models across files creates a trap, and this file is the door
    that closes it.

    A model class only registers itself on Base.metadata when its module is
    imported. Alembic's env.py imports `Base` and compares `Base.metadata`
    against the live database - so if a model's module has not been imported
    by then, that table is simply absent from the comparison. Autogenerate
    does not fail. It produces a migration that drops the table, or an empty
    one, and the mistake surfaces later as missing tables in a database
    nobody expected to be wrong.

    Importing every model here means `from app.models import Base` is enough
    to guarantee the metadata is complete, and there is exactly one place to
    add a line when a table is added.

CONSTRAINT
    A new model file MUST be imported here. If it is not, Alembic will
    silently ignore it.
"""

from .base import NAMING_CONVENTION, Base
from .interchange import Interchange
from .line import TRANSPORT_MODE, Line, TransportMode
from .segment import Segment
from .station import Station, StationComplex
from .station_line import StationLine

__all__ = [
    "NAMING_CONVENTION",
    "TRANSPORT_MODE",
    "Base",
    "Interchange",
    "Line",
    "Segment",
    "Station",
    "StationComplex",
    "StationLine",
    "TransportMode",
]
