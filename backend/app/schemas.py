"""
Pydantic models for what goes over the wire.

WHY THIS EXISTS
    The HTTP contract and the internal objects are two different things that
    change for different reasons. This file is the deliberate translation
    step between them: requests are validated into these models before any
    handler runs, and responses are serialised out of them.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, GUI class
    How:    There was no wire format. The Tkinter GUI read the same objects
            the rest of the program used and rendered them directly, so
            nothing was ever validated or converted.
    Wrong:  Not wrong for a desktop program, but it left the display coupled
            to internal representation — which is how the sentinel 9999999
            from the routing code ended up being compared against inside
            GUI.Find_shortest_path to decide what to draw.

WHAT CHANGED AND WHY
    A response model is a published contract. Renaming a field on an internal
    object no longer silently breaks a client, and an internal field added
    for debugging is not exposed by accident. From Phase 6 this is also half
    of the engine boundary: the engine returns its own frozen dataclasses and
    routes.py converts them into the schemas here. No engine function returns
    a Pydantic model.

WHAT'S NEW
    All of it. The 2021 project had no clients, so it had nothing to promise
    anyone.
"""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """What GET /health returns."""

    # Literal rather than str so the set of possible values is part of the
    # published schema and shows up in the generated OpenAPI docs.
    status: Literal["ok", "degraded"] = Field(
        description="ok when every dependency is reachable, degraded otherwise."
    )
    database: Literal["ok", "unreachable"] = Field(
        description="Result of a SELECT 1 against Postgres, run per request."
    )
    version: str = Field(description="Application version.")
