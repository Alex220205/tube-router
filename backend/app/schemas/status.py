"""The wire format for live line status."""

from pydantic import BaseModel, ConfigDict, Field


class LineStatusPublic(BaseModel):
    """What TfL currently says about one line."""

    model_config = ConfigDict(from_attributes=False)

    line_code: str = Field(description="TfL line id, e.g. piccadilly.")
    severity: int = Field(
        description=(
            "TfL's 0-20 severity. Lower is worse. 10 is Good Service. "
            "Sent as the number so a client can distinguish Minor from Severe."
        )
    )
    description: str = Field(description="TfL's own wording, e.g. Severe Delays.")
    reason: str | None = Field(
        default=None, description="The sentence a user reads. Null when all is well."
    )
    affected_stops: list[str] = Field(
        default_factory=list,
        description=(
            "NaPTAN ids of the stations a partial closure covers. Empty when "
            "the line is fine, and empty when the whole line is shut - there "
            "is no part to name then. A client can use it to say WHERE a line "
            "is closed rather than only that it is."
        ),
    )
    running: bool = Field(
        description=(
            "False only when trains are not moving - closed, suspended or "
            "part suspended. Delays are running. This is the flag that "
            "decides whether a route avoids the line."
        )
    )


class StatusResponse(BaseModel):
    """Live status for every tube line, and when it was fetched."""

    as_of: str | None = Field(
        default=None,
        description=(
            "When the poller last heard from TfL, ISO 8601. Null means it has "
            "not run yet or Redis is unreachable - render that as unknown, "
            "not as good."
        ),
    )
    lines: list[LineStatusPublic] = Field(
        default_factory=list,
        description="One per tube line, ordered by code. Empty when as_of is null.",
    )
