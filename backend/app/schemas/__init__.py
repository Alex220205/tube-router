"""Pydantic models for what goes over the wire, one module per resource."""

from .health import HealthResponse

__all__ = ["HealthResponse"]
