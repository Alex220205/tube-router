"""
Wire format for lines.

WHY THIS EXISTS
    The map legend and the objective toggle both need the lines, and both
    need the colour. One shape serves them.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, `lines` table
    How:    (line_id, name, service_status), read straight into the GUI.
    Wrong:  service_status was live data in a persistent table, deleted and
            reinserted on every launch. It is absent here; live status
            arrives over a websocket in Phase 7.

WHAT CHANGED AND WHY
    `colour` and `mode`, neither of which the old table had. Colour has no
    TfL API source and comes from their design standards, which is why it is
    a hardcoded map in the seed rather than fetched.
"""

from pydantic import BaseModel, Field


class LinePublic(BaseModel):
    """A line as the frontend needs it."""

    id: int = Field(description="Surrogate identifier.")
    code: str = Field(description="TfL line id, e.g. victoria.")
    name: str = Field(description="Display name, e.g. Victoria.")
    colour: str = Field(description="Hex colour from TfL design standards.")
    mode: str = Field(description="tube, overground, dlr or elizabeth.")
