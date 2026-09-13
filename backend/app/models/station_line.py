"""
Which lines serve a station, and whether the platform is step-free.

WHY THIS EXISTS
    Station-to-line is many-to-many, and it is the relationship the whole
    (station, line) node expansion in the engine depends on. It is also how
    the frontend answers "what lines are here" without a graph traversal.

WHAT THE 2021 VERSION DID
    Where:  train_stations.db, `stations` table
    How:    There was no join table. Line membership was implied by which
            connection rows happened to exist.
    Wrong:  "Which lines serve this station" was not a query you could write.
            The relationship was in the data all along — the audit found 486
            station rows for 346 stations, one per (station, line) — but
            undeclared, so it had to be rediscovered by string deduplication
            on every search.

WHAT CHANGED AND WHY
    Those 198 duplicate rows, made explicit. Declared once, queryable, and
    with somewhere to hang accessibility.

WHAT'S NEW
    step_free_to_platform. The old database had no accessibility data of any
    kind.
"""

from sqlalchemy import ForeignKey, false
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StationLine(Base):
    """A line calling at a station."""

    __tablename__ = "station_lines"

    # Composite primary key. A station serves a line once or not at all, and
    # saying so here removes the need for a separate unique constraint.
    station_id: Mapped[int] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True
    )
    line_id: Mapped[int] = mapped_column(
        ForeignKey("lines.id", ondelete="CASCADE"), primary_key=True
    )

    # Here rather than on Station, because step-free access is a property of
    # the station and line together. Green Park is step-free to some platforms
    # and not others; a flag on stations would force one answer for a station
    # with two. Defaults to false: absence of evidence is not step-free.
    #
    # server_default as well as the Python default, so the guarantee survives
    # a bulk insert that bypasses the ORM — which is exactly what a seed
    # script tends to do. tests/models/test_schema.py inserts via raw SQL to
    # prove that path.
    step_free_to_platform: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )
