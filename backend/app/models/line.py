"""Lines, and the set of transport modes a line can belong to."""

import enum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


# A native Postgres enum rather than a lookup table: four values, a fixed set, no
# attributes of their own, so a table would be a join for nothing. The cost is that
# adding a value later needs an explicit ALTER TYPE in a migration, which is acceptable
# for a set this stable.
class TransportMode(enum.Enum):
    """The kinds of service a line can be."""

    TUBE = "tube"
    OVERGROUND = "overground"
    DLR = "dlr"
    ELIZABETH = "elizabeth"


# SQLAlchemy persists a Python enum by its *name* by default, which would store "TUBE".
# values_callable makes it store the value instead, so the column holds "tube" and is
# readable in psql without a decoder ring.
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

    # Hex, for the frontend. Not nullable: a line the map cannot draw is not useful.
    colour: Mapped[str] = mapped_column(
        String(7),
        comment="Hex from TfL design standards. Not served by the API.",
    )
