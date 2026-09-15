"""
Wire formats for stations.

WHY THIS EXISTS
    The HTTP contract and the database rows are different things that change
    for different reasons. These are the translation, and the reason renaming
    a model column does not silently break the frontend.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, the GUI class
    How:    There was no wire format. Tkinter read the same objects the rest
            of the program used and rendered them directly.
    Wrong:  Not wrong for a desktop program, but it is how the sentinel
            9999999 from the routing code ended up being compared against
            inside GUI.Find_shortest_path to decide what to draw.

WHAT CHANGED AND WHY
    Two shapes rather than one. A search returns dozens of stations and a
    detail view returns one, and sending each station's full line membership
    in a list of fifty would be most of the payload for something the list
    never shows.

WHAT'S NEW
    Coordinates as plain floats. The column is geography(Point, 4326), which
    has no JSON representation - services/stations.py unpacks it and these
    say what comes out.
"""

from pydantic import BaseModel, ConfigDict, Field


class StationPublic(BaseModel):
    """A station as it appears in a list."""

    # Rows arrive as dicts from the service layer rather than as ORM objects,
    # which from_attributes would expect.
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
