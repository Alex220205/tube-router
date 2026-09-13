"""
The cost of changing from one line to another at a station.

WHY THIS EXISTS
    This is the table that makes "fewest changes" a question the router can
    answer. With a row per line pair, a change is an edge with a cost, so the
    search can count it and price it — which is what the (station, line) node
    expansion in Phase 5 is built on.

NO 2021 EQUIVALENT
    Changing line had no representation at all. Not a missing column, a
    missing idea: docs/AUDIT.md found no interchange table, no walking times
    and no accessibility data anywhere in the file. That is why the old router
    could neither count changes nor weight them, and why its graph treated
    every station as a single node with no notion of which line you arrived
    on.

WHAT'S NEW
    Stored rather than derived from station_lines. Deriving would give every
    line pair at a station the same walking time, and the walk between the
    Northern and the Central at Bank is nothing like Circle to District at
    Victoria.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Interchange(Base):
    """One directional change between two lines at a station."""

    __tablename__ = "interchanges"
    __table_args__ = (
        UniqueConstraint("station_id", "from_line_id", "to_line_id"),
        CheckConstraint("seconds > 0", name="seconds_positive"),
        # Changing from a line to itself is not a change. Same reasoning as
        # the self-loop check on segments: a row that cannot mean anything
        # should not be insertable. Generating interchanges from the
        # cross-product of lines at a station produces these by default, so
        # the constraint catches the generator rather than the human.
        CheckConstraint("from_line_id <> to_line_id", name="lines_differ"),
        Index("ix_interchanges_station_id", "station_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE")
    )

    # Directional, like segments. Northern to Central at Bank is not
    # necessarily the same walk as Central to Northern — different platforms,
    # different stairs, sometimes a different passage entirely.
    from_line_id: Mapped[int] = mapped_column(ForeignKey("lines.id"))
    to_line_id: Mapped[int] = mapped_column(ForeignKey("lines.id"))

    seconds: Mapped[int] = mapped_column()

    # Step-free for this particular change, which is not the same as either
    # platform being step-free on its own — the route between them is what
    # matters.
    step_free: Mapped[bool] = mapped_column(default=False, server_default=false())
