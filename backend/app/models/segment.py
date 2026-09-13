"""
A ride between two adjacent stations on one line.

WHY THIS EXISTS
    The edges of the graph. Everything the routing engine does is a sequence
    of these plus the interchanges between them.

WHAT THE 2021 VERSION DID
    Where:  train_stations.db, `connections` table
    How:    (connection_id, line_id, start_station, end_station, travel_time),
            356 rows, travel_time in integer minutes.
    Wrong:  The data was better than the code that read it. line_id was
            present and correct on all 356 rows — docs/AUDIT.md confirms zero
            nulls and zero orphans — and Create_graph's loop at lines 505-515
            read k[2], k[3] and k[4] and never touched k[1]. That single
            omission is why fewest-changes routing was never possible.

            The table itself had no constraints: 12 links were stored as zero
            minutes, and two Central line branches were left disconnected from
            the rest of the network with nothing able to notice.

WHAT CHANGED AND WHY
    The line is part of the segment's identity, in the unique constraint
    rather than an afterthought. Durations are seconds and must be positive.
    Rows are directional.

WHAT'S NEW
    Nothing conceptually — this is the one table the 2021 schema got broadly
    right. What is new is that it is now impossible to put nonsense in it.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Segment(Base):
    """One directional hop between adjacent stations on a line."""

    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("line_id", "origin_station_id", "destination_station_id"),
        # The most valuable constraint in the schema. The audit found 12 links
        # stored as zero minutes — Embankment to Charing Cross on both the
        # Bakerloo and the Northern among them. A zero-weight edge tells a
        # router the journey is free, which is worse than a missing edge
        # because it produces a confident wrong answer.
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

    # Directional: one row per direction, so a normal link between adjacent
    # stations is two rows. The network genuinely is not symmetric — the
    # Piccadilly line runs one way round the Heathrow terminal loop — and
    # storing it undirected pushes those exceptions into application logic
    # instead of data. The audit confirmed the 2021 data was undirected: 356
    # distinct pairs, none with a reverse row.
    origin_station_id: Mapped[int] = mapped_column(
        ForeignKey("stations.id"), comment="Station this hop departs from."
    )
    destination_station_id: Mapped[int] = mapped_column(
        ForeignKey("stations.id"), comment="Station this hop arrives at."
    )

    # Seconds, not minutes. The old column was minutes, which put 81% of the
    # network on either 1 or 2 and left "fastest route" almost nothing to
    # discriminate on.
    seconds: Mapped[int] = mapped_column(comment="Ride time in seconds. Must be > 0.")
