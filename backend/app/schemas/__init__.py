"""
Pydantic models for what goes over the wire, one module per resource.

WHY THIS EXISTS
    The HTTP contract and the internal objects are two different things that
    change for different reasons. These are the deliberate translation step
    between them: requests are validated into them before any handler runs,
    and responses are serialised out of them.

    From Phase 6 this is also half of the engine boundary. The engine returns
    its own frozen dataclasses and routes/routes.py converts them into the
    schemas here; no engine function ever returns a Pydantic model.

NO 2021 EQUIVALENT
    The Tkinter GUI read the same objects the rest of the program used and
    rendered them directly, so nothing was ever validated or converted. That
    is how the sentinel 9999999 from the routing code ended up being compared
    against inside GUI.Find_shortest_path to decide what to draw.
"""

from .health import HealthResponse

__all__ = ["HealthResponse"]
