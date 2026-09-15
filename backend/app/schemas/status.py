"""
The wire format for live line status.

WHY THIS EXISTS
    Same reason schemas/route.py exists: what the poller stores and what a
    client receives are allowed to diverge, and pinning the second one here
    means a change to the first is a failing test rather than a page that
    quietly renders nothing.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, lines.service_status
    How:    A TEXT column holding "Good Service" or "Severe Delays", read
            straight out of SQLite and printed into a Tkinter label.
    Wrong:  There was no format, because there was no boundary - the display
            read the storage directly. The severity was only ever a sentence,
            so nothing could ask "is this line actually running", which is why
            status and the router never met.

WHAT CHANGED AND WHY
    `severity` is the number, `running` is the verdict derived from it, and
    both are sent. A client that only wants to colour a line uses one; the
    router uses the other; neither has to re-derive what the other decided.

WHAT'S NEW
    `as_of`. The old value had no timestamp and no expiry, so a status shown
    on screen could be hours old with nothing to say so. Null here means the
    poller has not run yet, which a page can render honestly as "status
    unavailable" rather than implying everything is fine.
"""

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
