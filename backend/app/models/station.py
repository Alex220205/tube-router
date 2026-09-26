"""Stations, and the complexes that group physically connected ones."""

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

    # TfL's hubNaptanCode - HUBBAN for Bank/Monument. Its presence is what makes
    # complexes derivable from the source rather than a hand-curated list of special
    # cases. Nullable because most stations belong to no hub.
    tfl_hub_id: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        comment="TfL hubNaptanCode, e.g. 'HUBBAN'. Null if no hub.",
    )


class Station(Base):
    """One physical station."""

    __tablename__ = "stations"
    __table_args__ = (
        # Explicit rather than GeoAlchemy2's automatic spatial_index, so the index is
        # visible to autogenerate and named by our convention instead of appearing from
        # a DDL event listener.
        Index("ix_stations_location", "location", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, comment="Surrogate identifier for this station."
    )

    # Unique but not the primary key: TfL reissues and retires codes, and a changed code
    # would cascade through every foreign key in the schema.
    naptan_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        comment="NaPTAN code from TfL. The external identity.",
    )

    name: Mapped[str] = mapped_column(
        String(255),
        comment="TfL commonName verbatim. Never corrected here.",
    )

    # geography, not two floats. As floats, "stations within 500 metres" is a full table
    # scan with haversine arithmetic in Python; as geography with the GiST index above
    # it is an indexed query. 4326 is WGS84, the system GPS uses.
    location: Mapped[str] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        comment="WGS84 point (SRID 4326). GiST indexed.",
    )

    complex_id: Mapped[int | None] = mapped_column(
        ForeignKey("station_complexes.id", ondelete="SET NULL"),
        comment="Interchange complex this station belongs to, if any.",
    )
