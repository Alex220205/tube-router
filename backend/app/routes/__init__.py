"""Endpoints, one module per resource."""

# Merged into every route's `responses`, so the generated docs list what a client can
# actually receive rather than only the happy path.
COMMON_RESPONSES: dict[int | str, dict[str, str]] = {
    400: {"description": "Bad Request"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    500: {"description": "Internal Server Error"},
    503: {"description": "Service Unavailable"},
}
