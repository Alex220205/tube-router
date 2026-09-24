"""
Wire format for the whole drawable network.

WHY THIS EXISTS
    Phase 8's map needs every station and every link before it can draw
    anything. This is that, in one response.

NO 2021 EQUIVALENT
    The old project drew no map. Its equivalent of a network was a dict of
    dicts rebuilt from SQL on every search and discarded afterwards, which is
    why nothing could ever ask a question about the graph as a whole - not
    even whether it was connected. It was not: 244 of 346 stations.

WHAT'S NEW
    Segments carry station *ids*, not nested station objects. Oxford Circus
    is on three lines and appears in a dozen segments; nesting would repeat
    it every time and make the payload several times larger for no gain. The
    client joins once against the stations list.
"""

from pydantic import BaseModel, Field

from .lines import LinePublic
from .stations import StationPublic


class NetworkSegment(BaseModel):
    """One directional hop between adjacent stations."""

    line_id: int = Field(description="Which line this hop is on.")
    origin_station_id: int = Field(description="Departs from.")
    destination_station_id: int = Field(description="Arrives at.")
    seconds: int = Field(description="Ride time in seconds. Always > 0.")


# Its own class rather than a field on StationPublic, because the search box
# and the station detail page use that one and neither reads accessibility.
# A field nobody reads is worse than its absence - see CODE_STYLE.md section
# 10 - and putting it here keeps the cost with the only caller that wants
# it.
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
