"""The wire format for turning typed text into a station."""

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
