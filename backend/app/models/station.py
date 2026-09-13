"""
Stations, and the complexes that group physically connected ones.

WHY THIS EXISTS
    Everything else in the schema points at a station. Getting its identity
    right — one row per physical station, with a stable external key and a
    real location — is what the rest of the model rests on.

WHAT THE 2021 VERSION DID
    Where:  train_stations.db, `stations` table
    How:    (station_id, name). Two columns, 486 rows.
    Wrong:  Three things, all confirmed in docs/AUDIT.md.
            1. 486 rows for 346 actual stations, because it was secretly one
               row per (station, line) — King's Cross appears six times —
               with nothing in the schema saying so. Traversal.Create_graph
               had to rediscover the grouping by deduplicating name strings
               at lines 476-480, on every single search.
            2. No coordinates. The `train_stations` table meant to hold them
               was malformed and empty.
            3. No external identifier. Stations were keyed by name string
               alone, which makes every join to an outside dataset a fuzzy
               string match.

WHAT CHANGED AND WHY
    A station is a station. The station-to-line relationship is the explicit
    station_lines table, so the grouping is declared rather than rediscovered.
    NaPTAN gives a real external key, and location is a PostGIS geography
    column that cannot be null.

WHAT'S NEW
    station_complexes. Bank and Monument are one interchange under two names,
    and without this they are either one station — wrong, separate platforms
    and a real walk — or two unrelated stations, which is wrong in the other
    direction because you can change between them.
"""

from geoalchemy2 import Geography
from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StationComplex(Base):
    """A group of stations that share an interchange."""

    __tablename__ = "station_complexes"

    id: Mapped[int] = mapped_column(
        primary_key=True, comment="Surrogate identifier for this complex."
    )
    name: Mapped[str] = mapped_column(
        String(255), comment="Name of the complex, e.g. 'Bank and Monument'."
    )

    # TfL's hubNaptanCode — HUBBAN for Bank/Monument. Its presence is what
    # makes complexes derivable from the source rather than a hand-curated
    # list of special cases. Nullable because most stations belong to no hub.
    tfl_hub_id: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        comment="TfL hubNaptanCode, e.g. 'HUBBAN'. Null if no hub.",
    )


class Station(Base):
    """One physical station."""

    __tablename__ = "stations"
    __table_args__ = (
        # Explicit rather than GeoAlchemy2's automatic spatial_index, so the
        # index is visible to autogenerate and named by our convention
        # instead of appearing from a DDL event listener.
        Index("ix_stations_location", "location", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, comment="Surrogate identifier for this station."
    )

    # Not null, unlike the Phase 1 brief. That had it nullable because the
    # 2021 data has no external identifier at all. Seeding from TfL means
    # every station arrives with a NaPTAN code, and a nullable column that is
    # never null invites code to handle a case that cannot occur.
    #
    # Unique but not the primary key: TfL reissues and retires codes, and a
    # changed code would cascade through every foreign key in the schema.
    naptan_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        comment="NaPTAN code from TfL. The external identity.",
    )

    # TfL's commonName, verbatim, including the "Underground Station" suffix.
    # Trimming for display is the frontend's job; the database stores what the
    # authority says. See docs/DECISIONS.md on why there is no correction map.
    name: Mapped[str] = mapped_column(
        String(255),
        comment="TfL commonName verbatim. Never corrected here.",
    )

    # geography, not two floats. As floats, "stations within 500 metres" is a
    # full table scan with haversine arithmetic in Python; as geography with
    # the GiST index above it is an indexed query. 4326 is WGS84, the system
    # GPS uses.
    location: Mapped[str] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        comment="WGS84 point (SRID 4326). GiST indexed.",
    )

    complex_id: Mapped[int | None] = mapped_column(
        ForeignKey("station_complexes.id", ondelete="SET NULL"),
        comment="Interchange complex this station belongs to, if any.",
    )
