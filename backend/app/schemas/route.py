"""
The wire format for a planned journey.

WHY THIS EXISTS
    Engine dataclasses are never returned from an endpoint. These are what
    routes/route.py converts them into, and that conversion is half of the
    engine boundary - the half that stops Pydantic, FastAPI and OpenAPI
    concerns leaking backwards into a package that declares no dependencies.

    It is also where station *names* arrive. The engine speaks in NaPTAN ids
    because it must not care what anything is called; a client rendering a
    route needs "Green Park", not "940GZZLUGPK".

WHAT THE 2021 VERSION DID
    Where:  database[works].py lines 860-880, GUI.Find_shortest_path
    How:    There was no wire format, because there was no wire. The search
            wrote into Traversal's own attributes and the Tkinter window read
            them back out of the same object, then compared the result against
            the literal 9999999 at lines 868 and 876 to decide what to draw.
    Wrong:  A magic number invented by the algorithm had become part of the
            contract with the interface. Any caller that forgot to check it
            rendered 9999999 as a journey time - two and a half months.

WHAT CHANGED AND WHY
    A route that does not exist is a different shape, not a special number.
    RouteResponse carries `found`, and a client that ignores it gets None
    where it wanted legs rather than a plausible-looking duration.

WHAT'S NEW
    Legs. The old result was a flat list of station names with no record of
    which line each hop was on, so it could not say where you change. A line
    on a map does not tell you that either; the leg list is the actual answer.
"""

from pydantic import BaseModel, ConfigDict, Field

from tube_engine import REASONS


class RouteRequest(BaseModel):
    """A journey to plan.

    Attributes mirror tube_engine.RouteQuery, but this is a separate class on
    purpose: the engine's types must not grow Pydantic validators, and this
    one must not grow engine behaviour.
    """

    model_config = ConfigDict(from_attributes=False)

    origin: str = Field(
        min_length=1,
        description="NaPTAN id to start from, e.g. 940GZZLUOXC.",
    )
    destination: str = Field(
        min_length=1,
        description="NaPTAN id to finish at.",
    )
    objective: str = Field(
        default="fastest",
        description="One of fastest, fewest_changes, step_free.",
    )
    avoid_lines: list[str] = Field(
        default_factory=list,
        description="TfL line codes the route may not use, e.g. ['central'].",
    )


class StationStop(BaseModel):
    """One station on a leg, with the name a client will draw."""

    id: str = Field(description="NaPTAN id.")
    name: str = Field(description="TfL commonName, verbatim.")


class LegPublic(BaseModel):
    """An unbroken run on one line."""

    line: str = Field(description="TfL line code, e.g. victoria.")
    seconds: int = Field(
        description=(
            "Time on this line. Excludes the change that follows it - "
            "interchange time belongs to the route total, not to either leg."
        )
    )
    stations: list[StationStop] = Field(
        description="Every station passed through, in order, both ends included."
    )


class RouteResponse(BaseModel):
    """A planned journey, or a stated reason there is none.

    `found` is the discriminator rather than an HTTP status, because "those
    two stations are not connected" is a successful answer to a well-formed
    question - the same reasoning that made an empty station search a 200 in
    Phase 3. A 404 would conflate it with "that endpoint does not exist", and
    a 500 would claim the service is broken when it is working correctly.
    """

    found: bool = Field(description="False when no route exists.")
    reason: str | None = Field(
        default=None,
        description=(
            "Why there is no route: "
            + ", ".join(sorted(REASONS))
            + ". Null when found is true."
        ),
    )
    total_seconds: int = Field(
        default=0, description="Riding plus changing, end to end."
    )
    changes: int = Field(default=0, description="How many times you change line.")
    step_free: bool = Field(
        default=False,
        description=(
            "True when the origin platform, every change used, and the "
            "destination platform are all step-free."
        ),
    )
    legs: list[LegPublic] = Field(
        default_factory=list,
        description="One per unbroken run on a line. Empty when found is false.",
    )
    avoided_for_disruption: list[str] = Field(
        default_factory=list,
        description=(
            "Lines excluded ENTIRELY because TfL reports no trains running on "
            "them. Populated whether or not a route was found, so a caller can "
            "tell a strange-looking journey from a broken one - and can tell "
            "'nowhere to go' from 'nowhere to go while the Piccadilly is shut'."
        ),
    )
    partly_closed: list[str] = Field(
        default_factory=list,
        description=(
            "Lines with one stretch shut. The rest of the line is running and "
            "the route may well use it, so these are NOT in "
            "avoided_for_disruption - saying 'avoiding the Piccadilly, no "
            "trains running' on a journey whose first leg is the Piccadilly is "
            "a page contradicting itself."
        ),
    )
