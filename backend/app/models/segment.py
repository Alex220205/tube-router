"""A ride between two adjacent stations on one line."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Segment(Base):
    """One directional hop between adjacent stations on a line."""

    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("line_id", "origin_station_id", "destination_station_id"),
        # A zero-second hop tells the router a journey is free, which is worse than a
        # missing hop: it produces a confident wrong answer.
        CheckConstraint("seconds > 0", name="seconds_positive"),
        CheckConstraint(
            "origin_station_id <> destination_station_id",
            name="origin_differs_from_destination",
        ),
        Index("ix_segments_origin_station_id", "origin_station_id"),
        Index("ix_segments_line_id", "line_id"),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, comment="Surrogate identifier for this segment."
    )
    line_id: Mapped[int] = mapped_column(
        ForeignKey("lines.id", ondelete="CASCADE"),
        comment="The line this hop is on. Part of its identity.",
    )

    origin_station_id: Mapped[int] = mapped_column(
        ForeignKey("stations.id"), comment="Station this hop departs from."
    )
    destination_station_id: Mapped[int] = mapped_column(
        ForeignKey("stations.id"), comment="Station this hop arrives at."
    )

    # Seconds, not minutes: in whole minutes most adjacent stations are 1 or 2 apart,
    # which leaves "fastest route" almost nothing to choose between.
    seconds: Mapped[int] = mapped_column(comment="Ride time in seconds. Must be > 0.")
