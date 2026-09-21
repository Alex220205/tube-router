"""
The wire format for turning typed text into a station.

WHY THIS EXISTS
    Everything else in this service assumes you already know which station
    you want, which is exactly the knowledge a visitor does not have. This is
    the boundary where "British Museum" becomes "Tottenham Court Road", and
    the boundary is where the promise gets written down.

NO 2021 EQUIVALENT
    The old project's station entry was a Tkinter field over a list of names
    held in the same process. There was nothing to resolve and nothing that
    could resolve it.

WHAT'S NEW
    `results` is a list, and that is the entire design.

    "High Street" matches seven places in Britain. "British Museum" matches
    one. Returning the best guess would make those two look identical to the
    client and would silently plan a journey to the wrong one - the failure
    this project has argued against since Phase 3, where an empty search had
    to be a 200 rather than a 404 so that "no matches" and "broken request"
    could be told apart.

    So every match comes back with the address Google formatted for it, and a
    person picks. One match is not a special case in the wire format; it is a
    list of length one, and the client may resolve it without asking.

    Each match carries its own nearest stations rather than the caller
    joining them afterwards, because the join is PostGIS and the client has
    no coordinates and no index.
"""

from pydantic import BaseModel, Field


class NearbyStation(BaseModel):
    """A station near a resolved place, and how far."""

    naptan_id: str = Field(description="TfL station id, e.g. 940GZZLUTCR.")
    name: str = Field(description="Station name, as TfL writes it.")
    metres: int = Field(
        description=(
            "Straight line distance from the place. Not a walking distance: "
            "this is ST_Distance over geography, and the page says so."
        )
    )


class GeocodeMatch(BaseModel):
    """One place Google recognised, with the stations nearest to it."""

    address: str = Field(
        description=(
            "Google's formatted address. This is what distinguishes one "
            "match from another on screen, so it is the thing a user reads "
            "when choosing, not a label we invent."
        )
    )
    latitude: float = Field(description="WGS84.")
    longitude: float = Field(description="WGS84.")
    stations: list[NearbyStation] = Field(
        default_factory=list, description="Nearest first."
    )


class GeocodeResponse(BaseModel):
    """What a typed destination resolved to, or an honest inability to say."""

    available: bool = Field(
        description=(
            "False when no key is configured or Google could not be reached. "
            "`results` is then empty because we did not look, NOT because "
            "nothing matched. The same distinction schemas/places.py draws, "
            "and for the same reason: an empty answer and a broken request "
            "must not look the same."
        )
    )
    query: str = Field(description="What was typed, echoed back.")
    results: list[GeocodeMatch] = Field(
        default_factory=list,
        description=(
            "Most confident first. Empty with available true means Google "
            "recognised nothing, which is a real answer."
        ),
    )
