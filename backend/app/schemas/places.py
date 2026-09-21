"""
The wire format for what is near a station.

WHY THIS EXISTS
    Same reason schemas/route.py exists: what Google returns and what this
    service promises are two different things, and the boundary is where the
    promise gets written down. Google's Nearby Search answers with nested
    objects, localised display names and a field set that changes with the
    field mask; the page wants a flat row with a name on it.

    It also keeps the field mask honest. Every field below corresponds to one
    path asked for in services/places.py, and Google bills by field, so a
    field here with no reader is money spent on nothing.

NO 2021 EQUIVALENT
    The old project called Places and rendered the result straight into a
    Tkinter label from inside the GUI thread. There was no boundary, no
    schema and nothing that could be tested without a network and a key.

WHAT'S NEW
    `available`, which is the whole reason this file is not just a list.

    Three different situations produce an empty list and they must not look
    the same: no key configured, Google unreachable, and a station with
    genuinely nothing near it. The first two are "we cannot answer" and the
    third is an answer. A client that cannot tell them apart either renders
    an error over a missing credential or claims central London has no
    restaurants.

    This is deliberately the opposite call from schemas/status.py, where an
    unknown state must never render as good service. The difference is what
    a wrong reading costs: a missing line status can send someone to a
    platform with no trains, and a missing restaurant list cannot mislead
    anyone about anything.
"""

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
