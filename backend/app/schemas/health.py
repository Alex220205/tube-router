"""Pydantic models for what goes over the wire."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """What GET /health returns."""

    # Literal rather than str so the set of possible values is part of the published
    # schema and shows up in the generated OpenAPI docs.
    status: Literal["ok", "degraded"] = Field(
        description="ok when every dependency is reachable, degraded otherwise."
    )
    database: Literal["ok", "unreachable"] = Field(
        description="Result of a SELECT 1 against Postgres, run per request."
    )
    version: str = Field(description="Application version.")
