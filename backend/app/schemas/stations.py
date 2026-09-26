"""Wire formats for stations."""

from pydantic import BaseModel, ConfigDict, Field


class StationPublic(BaseModel):
    """A station as it appears in a list."""

    # Rows arrive as dicts from the service layer rather than as ORM objects, which
    # from_attributes would expect.
    model_config = ConfigDict(from_attributes=False)

    id: int = Field(description="Surrogate identifier.")
    naptan_id: str = Field(description="NaPTAN code, e.g. 940GZZLUOXC.")
    name: str = Field(description="TfL commonName, verbatim, suffix included.")
    lat: float = Field(description="WGS84 latitude.")
    lon: float = Field(description="WGS84 longitude.")


class StationLineInfo(BaseModel):
    """One line calling at a station, with its accessibility."""

    code: str = Field(description="TfL line id, e.g. victoria.")
    name: str = Field(description="Display name.")
    colour: str = Field(description="Hex colour for the map.")
    step_free_to_platform: bool = Field(
        description="Step-free street to platform, for this line specifically."
    )


class StationRead(StationPublic):
    """One station, with everything the detail view needs."""

    lines: list[StationLineInfo] = Field(
        default_factory=list, description="Lines calling here."
    )
    complex_name: str | None = Field(
        default=None,
        description="Interchange complex, e.g. 'Bank and Monument'. Null for most.",
    )
