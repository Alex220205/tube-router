"""Which lines serve a station, and whether the platform is step-free."""

from sqlalchemy import ForeignKey, false
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StationLine(Base):
    """A line calling at a station."""

    __tablename__ = "station_lines"

    # Composite primary key. A station serves a line once or not at all, and saying so
    # here removes the need for a separate unique constraint.
    station_id: Mapped[int] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"),
        primary_key=True,
        comment="The station this line calls at.",
    )
    line_id: Mapped[int] = mapped_column(
        ForeignKey("lines.id", ondelete="CASCADE"),
        primary_key=True,
        comment="The line calling at that station.",
    )

    # Here rather than on Station, because step-free access is a property of the station
    # and line together. Green Park is step-free to some platforms and not others; a
    # flag on stations would force one answer for a station with two. Defaults to false:
    # absence of evidence is not step-free.
    step_free_to_platform: Mapped[bool] = mapped_column(
        default=False,
        server_default=false(),
        comment="Step-free street to platform. False when unknown.",
    )
