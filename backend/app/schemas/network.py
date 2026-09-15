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


class NetworkResponse(BaseModel):
    """Everything needed to draw the network."""

    stations: list[StationPublic] = Field(description="Every station.")
    segments: list[NetworkSegment] = Field(description="Every directional hop.")
    lines: list[LinePublic] = Field(description="Every line, with colours.")
