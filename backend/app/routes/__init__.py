"""
Endpoints, one module per resource.

WHY THIS EXISTS
    main.py includes each router here by name, so that file reads as an index
    of what the service serves. Each module owns its path prefix and nothing
    else.

NO 2021 EQUIVALENT
    There were no endpoints. The old project was a Tkinter window, and its
    equivalent of routing was a method call.

WHAT'S NEW
    COMMON_RESPONSES lives here rather than being redeclared in every route
    module. Four copies of the same dict is four places to forget when a
    status is added, and the generated OpenAPI page is the thing that
    suffers — silently.
"""

# Merged into every route's `responses`, so the generated docs list what a
# client can actually receive rather than only the happy path.
COMMON_RESPONSES: dict[int | str, dict[str, str]] = {
    400: {"description": "Bad Request"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    500: {"description": "Internal Server Error"},
    503: {"description": "Service Unavailable"},
}
