"""
SQLAlchemy models — the database schema as Python.

WHY THIS EXISTS
    One declarative definition of every table, which Alembic compares against
    the live database to generate migrations, and which the query layer uses
    to build SQL. Without it the schema would exist only in migration files
    and there would be nothing to check the database against.

WHAT THE 2021 VERSION DID
    Where:  train_stations.db, and SQL string literals scattered through
            database[works].py
    How:    Four tables created by hand, presumably in a GUI tool, with the
            application referring to them through inline SQL strings.
    Wrong:  Three things.
            1. There was no definition of the schema anywhere in version
               control, so it could not be reviewed, reproduced or checked.
               docs/AUDIT.md records the consequence: the train_stations
               table was created with the commas missing, so SQLite parsed it
               as a single column named `longitude` whose declared type was
               the literal string "REAL\\n latitude REAL\\n name TEXT". No
               error was raised and it sat empty for five years.
            2. There were no constraints. Foreign keys were declared but
               SQLite does not enforce them unless PRAGMA foreign_keys is set
               per connection, which the application never did. Every
               guarantee lived in application code, and the application did
               not enforce them either.
            3. One table silently meant something other than its name.
               `stations` held 486 rows for 346 stations because it was
               really one row per (station, line) — King's Cross appears six
               times. Nothing said so, so Traversal.Create_graph had to
               rediscover it at runtime by deduplicating name strings at
               lines 476-480, on every single search.

WHAT CHANGED AND WHY
    The schema is code, reviewed in a pull request and applied by migration.
    A malformed definition fails at import rather than silently producing a
    table that is not what it looks like.

    Every table carries constraints, because their absence is the direct
    cause of the 12 zero-duration links and two detached Central line
    branches the audit found. The station/line relationship is an explicit
    join table rather than something rediscovered per search.

WHAT'S NEW
    A naming convention on the metadata. Postgres invents names for
    constraints you do not name, and those names vary with how the constraint
    was created — so a later migration that wants to drop or alter one has
    nothing reliable to reference and ends up carrying a name someone looked
    up in psql. Fixing that costs one MetaData argument before any table
    exists, and a migration renaming every constraint in the database
    afterwards.
"""

import enum

from geoalchemy2 import Geography
from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Applied to every constraint and index that is not explicitly named.
#
#   ix  index                 ix_stations_name
#   uq  unique constraint     uq_lines_code
#   ck  check constraint      ck_segments_seconds_positive
#   fk  foreign key           fk_segments_line_id_lines
#   pk  primary key           pk_stations
#
# `ck` interpolates constraint_name, so every CheckConstraint still has to be
# given one — an unnamed check would render as `ck_segments_` and collide with
# the next unnamed check on the same table.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every model in the schema.

    Alembic's env.py points `target_metadata` at `Base.metadata`, so a model
    that does not inherit from this is invisible to autogenerate — which
    produces an empty migration rather than an error.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TransportMode(enum.Enum):
    """The kinds of service a line can be.

    A native Postgres enum rather than a lookup table: four values, a fixed
    set, no attributes of their own, so a table would be a join for nothing.
    The cost is that adding a value later needs an explicit ALTER TYPE in a
    migration, which is acceptable for a set this stable.

    Only TUBE is used in Phase 2 — the network is seeded tube-first — but the
    others are declared now so adding them is data rather than a migration.
    """

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
    """A single line — Victoria, Central, the Elizabeth line.

    Changed from 2021: the old `lines` table was (line_id, name,
    service_status). service_status held values like "Severe Delays" and the
    application deleted every row and reinserted it on launch
    (Line.DeleteLinedatabase then Line.AddLinedatabase). That is a cache
    wearing a table's clothing — volatile data in a persistent store,
    rewritten at startup for something with a lifetime of minutes. Live
    status moves to Redis in Phase 7.
    """

    __tablename__ = "lines"

    id: Mapped[int] = mapped_column(primary_key=True)

    # TfL's own line identifier, which doubles as our stable code. The Phase 1
    # brief had a separate tfl_id column; now that TfL is the seed source the
    # two would hold identical values on every row, and two columns that are
    # always equal is a consistency bug waiting to happen.
    code: Mapped[str] = mapped_column(String(64), unique=True)

    name: Mapped[str] = mapped_column(String(128))
    mode: Mapped[TransportMode] = mapped_column(TRANSPORT_MODE)

    # Hex, for the frontend. TfL does not serve line colours through the API,
    # so this comes from their published design standards as a map in the
    # seed. Not nullable: a line the map cannot draw is not useful.
    colour: Mapped[str] = mapped_column(String(7))


class StationComplex(Base):
    """A group of stations that share an interchange.

    Bank and Monument are one interchange under two names. Without this they
    are either one station — wrong, they have separate platforms and a real
    walk between them — or two unrelated stations, which is wrong in the
    other direction because you can change between them.

    No 2021 equivalent. The old schema had duplicate station rows and
    Create_graph deduplicated them by string equality at runtime, lines
    476-480, on every search.
    """

    __tablename__ = "station_complexes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))

    # TfL's hubNaptanCode — HUBBAN for Bank/Monument. Its presence is what
    # makes complexes derivable from the source rather than a hand-curated
    # list of special cases. Nullable because most stations belong to no hub.
    tfl_hub_id: Mapped[str | None] = mapped_column(String(64), unique=True)


class Station(Base):
    """One physical station.

    Changed from 2021: `stations` was (station_id, name) and held 486 rows
    for 346 stations, because it was secretly one row per (station, line).
    Here a station is a station; the station-to-line relationship is the
    explicit station_lines table.
    """

    __tablename__ = "stations"
    __table_args__ = (
        # Explicit rather than GeoAlchemy2's automatic spatial_index, so the
        # index is visible to autogenerate and named by our convention
        # instead of appearing from a DDL event listener.
        Index(
            "ix_stations_location",
            "location",
            postgresql_using="gist",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Not null, unlike the Phase 1 brief. That had it nullable because the
    # 2021 data has no external identifier of any kind — the audit confirmed
    # stations are keyed by name string alone. Seeding from TfL means every
    # station arrives with a NaPTAN code, and a nullable column that is never
    # null invites code to handle a case that cannot occur.
    #
    # Unique but not the primary key: TfL reissues and retires codes, and a
    # changed code would cascade through every foreign key in the schema.
    naptan_id: Mapped[str] = mapped_column(String(64), unique=True)

    # TfL's commonName, verbatim, including the "Underground Station" suffix.
    # Trimming for display is the frontend's job; the database stores what the
    # authority says.
    name: Mapped[str] = mapped_column(String(255))

    # geography, not two floats. As floats, "stations within 500 metres" is a
    # full table scan with haversine arithmetic in Python; as geography with
    # the GiST index above it is an indexed query. 4326 is WGS84, the system
    # GPS uses.
    location: Mapped[str] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False)
    )

    complex_id: Mapped[int | None] = mapped_column(
        ForeignKey("station_complexes.id", ondelete="SET NULL")
    )


class Segment(Base):
    """A ride between two adjacent stations on one line.

    Changed from 2021: `connections` was (connection_id, line_id,
    start_station, end_station, travel_time) with travel_time in minutes and
    no constraint on it. line_id was present and correct — the audit
    confirmed all 356 rows — and Create_graph read the row and never looked
    at that field, which is the single reason fewest-changes routing was
    never possible. Here the line is part of the segment's identity.
    """

    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint(
            "line_id",
            "origin_station_id",
            "destination_station_id",
        ),
        # The most valuable constraint in the schema. The audit found 12 links
        # stored as zero minutes — Embankment to Charing Cross on both the
        # Bakerloo and the Northern among them. A zero-weight edge tells a
        # router the journey is free, which is worse than a missing edge
        # because it produces a confident wrong answer. This makes the row
        # impossible to insert.
        CheckConstraint("seconds > 0", name="seconds_positive"),
        CheckConstraint(
            "origin_station_id <> destination_station_id",
            name="origin_differs_from_destination",
        ),
        Index("ix_segments_origin_station_id", "origin_station_id"),
        Index("ix_segments_line_id", "line_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id", ondelete="CASCADE"))

    # Directional: one row per direction, so a normal link between adjacent
    # stations is two rows. The network genuinely is not symmetric — the
    # Piccadilly line runs one way round the Heathrow terminal loop — and
    # storing it undirected pushes those exceptions into application logic
    # instead of data. The audit confirmed the 2021 data was undirected: 356
    # distinct pairs, none with a reverse row.
    origin_station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    destination_station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))

    # Seconds, not minutes. The old column was minutes, which put 81% of the
    # network on either 1 or 2 and left "fastest route" almost nothing to
    # discriminate on.
    seconds: Mapped[int] = mapped_column()
