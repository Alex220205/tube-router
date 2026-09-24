"""
Lines, and the set of transport modes a line can belong to.

WHY THIS EXISTS
    A line is the thing a segment belongs to and the thing you change between
    at an interchange. Both of those relationships are what make
    fewest-changes routing expressible at all.

WHAT THE 2021 VERSION DID
    Where:  train_stations.db, `lines` table
    How:    (line_id, name, service_status). Eleven rows.
    Wrong:  service_status held live values like "Severe Delays", and the
            application deleted every row and reinserted it on launch -
            Line.DeleteLinedatabase followed by Line.AddLinedatabase. That is
            a cache wearing a table's clothing: the persistent store rewritten
            at startup for data with a lifetime of minutes.

WHAT CHANGED AND WHY
    service_status is gone; live status arrives in Redis in Phase 7, where
    volatile data belongs. `code` is unique and not null, which the old table
    had no way to guarantee.

WHAT'S NEW
    `mode` and `colour`. The old data was tube plus a London Overground row
    with no topology behind it, so a mode was never needed. `colour` has no
    TfL API source and comes from their published design standards as a map
    in the seed.
"""

import enum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


# A native Postgres enum rather than a lookup table: four values, a fixed
# set, no attributes of their own, so a table would be a join for nothing.
# The cost is that adding a value later needs an explicit ALTER TYPE in a
# migration, which is acceptable for a set this stable.
#
# Only TUBE is used in Phase 2 - the network is seeded tube-first - but the
# others are declared now so adding them is data rather than a migration.
class TransportMode(enum.Enum):
    """The kinds of service a line can be."""

    TUBE = "tube"
    OVERGROUND = "overground"
    DLR = "dlr"
    ELIZABETH = "elizabeth"


# SQLAlchemy persists a Python enum by its *name* by default, which would
# store "TUBE". values_callable makes it store the value instead, so the
# column holds "tube" and is readable in psql without a decoder ring.
TRANSPORT_MODE = Enum(
    TransportMode,
    name="transport_mode",
    values_callable=lambda members: [m.value for m in members],
)


class Line(Base):
    """A single line - Victoria, Central, the Elizabeth line."""

    __tablename__ = "lines"

    id: Mapped[int] = mapped_column(
        primary_key=True, comment="Surrogate identifier for this line."
    )

    # TfL's own line identifier, which doubles as our stable code. The Phase 1
    # brief had a separate tfl_id column; now that TfL is the seed source the
    # two would hold identical values on every row, and two columns that are
    # always equal is a consistency bug waiting to happen.
    code: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        comment="TfL line id, e.g. 'victoria'. Also our stable code.",
    )

    name: Mapped[str] = mapped_column(
        String(128), comment="Display name as TfL gives it, e.g. 'Victoria'."
    )
    mode: Mapped[TransportMode] = mapped_column(
        TRANSPORT_MODE, comment="Kind of service: tube, overground, dlr or elizabeth."
    )

    # Hex, for the frontend. Not nullable: a line the map cannot draw is not
    # useful.
    colour: Mapped[str] = mapped_column(
        String(7),
        comment="Hex from TfL design standards. Not served by the API.",
    )
