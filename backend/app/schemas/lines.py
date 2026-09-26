"""Wire format for lines."""

from pydantic import BaseModel, Field


class LinePublic(BaseModel):
    """A line as the frontend needs it."""

    id: int = Field(description="Surrogate identifier.")
    code: str = Field(description="TfL line id, e.g. victoria.")
    name: str = Field(description="Display name, e.g. Victoria.")
    colour: str = Field(description="Hex colour from TfL design standards.")
    mode: str = Field(description="tube, overground, dlr or elizabeth.")
