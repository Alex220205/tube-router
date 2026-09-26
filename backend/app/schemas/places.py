"""The wire format for what is near a station."""

from pydantic import BaseModel, Field


class Place(BaseModel):
    """One result, flattened out of Google's nested shape."""

    name: str = Field(description="The place's display name, e.g. Dishoom.")
    address: str | None = Field(
        default=None,
        description="Formatted address. Null when Google did not supply one.",
    )
    rating: float | None = Field(
        default=None,
        description="Google's 1 to 5 rating. Null when nobody has rated it.",
    )
    ratings: int | None = Field(
        default=None,
        description=(
            "How many ratings that average is over. A 5.0 from two people "
            "and a 4.3 from nine hundred are different claims."
        ),
    )
    metres: int | None = Field(
        default=None,
        description=(
            "Straight line distance from the station, in metres. Not a "
            "walking distance: Google does not return one from a nearby "
            "search, and asking for a real one is a second billed call per "
            "result. The page labels it as straight line."
        ),
    )
    wheelchair_entrance: bool | None = Field(
        default=None,
        description=(
            "True when Google records a wheelchair accessible entrance. "
            "NULL means nobody has recorded anything, which is not the same "
            "as false and must not be rendered as one: most places on Earth "
            "have no accessibility data, and telling a wheelchair user that "
            "a restaurant is inaccessible on the strength of missing data is "
            "a confident lie about a real business. The page marks true and "
            "says nothing at all for null."
        ),
    )
    website: str | None = Field(
        default=None,
        description=(
            "The place's own site. Null when it has none, which is common - "
            "a market stall or a park has no website and is not diminished "
            "by that."
        ),
    )
    maps_url: str | None = Field(
        default=None,
        description=(
            "The place's page on Google Maps. Effectively always present, "
            "which is why it is carried alongside `website` rather than "
            "instead of it: together they are a link on every row."
        ),
    )


class PlacesResponse(BaseModel):
    """What is near one station, or an honest statement that we cannot say."""

    available: bool = Field(
        description=(
            "False when no key is configured or Google could not be reached. "
            "The list is then empty because we did not look, NOT because "
            "there is nothing there. Render nothing at all, not an error and "
            "not 'none found'."
        )
    )
    station: str = Field(description="NaPTAN id the search was centred on.")
    kind: str = Field(
        description=(
            "Which category was asked for: food, coffee, pubs, museums or "
            "see. A category, not a Google place type - each expands to "
            "several of those server side."
        )
    )
    places: list[Place] = Field(
        default_factory=list,
        description="Nearest first. Empty is meaningful only when available is true.",
    )
