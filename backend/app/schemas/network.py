"""Wire format for the whole drawable network."""

from pydantic import BaseModel, Field

from .lines import LinePublic
from .stations import StationPublic


class NetworkSegment(BaseModel):
    """One directional hop between adjacent stations."""

    line_id: int = Field(description="Which line this hop is on.")
    origin_station_id: int = Field(description="Departs from.")
    destination_station_id: int = Field(description="Arrives at.")
    seconds: int = Field(description="Ride time in seconds. Always > 0.")


class NetworkStation(StationPublic):
    """A station as the map needs it: position plus whether it is accessible."""

    step_free: bool = Field(
        description=(
            "True when at least one platform here can be reached from the "
            "street without stairs. The database records this per line, "
            "because a platform is what is accessible - the Jubilee at "
            "Westminster is step-free and the District is not - so this is "
            "the OR across the lines that serve the station, which is the "
            "question a map marker answers."
        )
    )


class NetworkResponse(BaseModel):
    """Everything needed to draw the network."""

    stations: list[NetworkStation] = Field(description="Every station.")
    segments: list[NetworkSegment] = Field(description="Every directional hop.")
    lines: list[LinePublic] = Field(description="Every line, with colours.")
