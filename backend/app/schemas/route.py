"""The wire format for a planned journey."""

from pydantic import BaseModel, ConfigDict, Field

from tube_engine import REASONS


# Attributes mirror tube_engine.RouteQuery, but this is a separate class on purpose: the
# engine's types must not grow Pydantic validators, and this one must not grow engine
# behaviour.
class RouteRequest(BaseModel):
    """A journey to plan."""

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
    """A planned journey, or a stated reason there is none."""

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
