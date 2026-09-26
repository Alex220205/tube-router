"""The cost of changing from one line to another at a station."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Interchange(Base):
    """One directional change between two lines at a station."""

    __tablename__ = "interchanges"
    __table_args__ = (
        UniqueConstraint("station_id", "from_line_id", "to_line_id"),
        CheckConstraint("seconds > 0", name="seconds_positive"),
        # Changing from a line to itself is not a change. Same reasoning as the
        # self-loop check on segments: a row that cannot mean anything should not be
        # insertable.
        CheckConstraint("from_line_id <> to_line_id", name="lines_differ"),
        Index("ix_interchanges_station_id", "station_id"),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, comment="Surrogate identifier for this interchange."
    )
    station_id: Mapped[int] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"),
        comment="Station where the change happens.",
    )

    # Directional, like segments. Northern to Central at Bank is not necessarily the
    # same walk as Central to Northern - different platforms, different stairs,
    # sometimes a different passage entirely.
    from_line_id: Mapped[int] = mapped_column(
        ForeignKey("lines.id"), comment="Line being left."
    )
    to_line_id: Mapped[int] = mapped_column(
        ForeignKey("lines.id"), comment="Line being joined."
    )

    seconds: Mapped[int] = mapped_column(
        comment="Walk time between platforms, seconds. Must be > 0."
    )

    # Step-free for this particular change, which is not the same as either platform
    # being step-free on its own - the route between them is what matters.
    step_free: Mapped[bool] = mapped_column(
        default=False,
        server_default=false(),
        comment="Step-free for this change. False when unknown.",
    )
