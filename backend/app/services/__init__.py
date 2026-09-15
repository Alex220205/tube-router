"""
Business logic: everything that is neither a route handler nor a table.

WHY THIS EXISTS
    Routes should validate input, call one thing, and shape the response.
    Anything with reasoning in it lives here, so a handler stays readable and
    the logic stays testable without an HTTP client.

NO 2021 EQUIVALENT
    The old project had no layering at all. database[works].py held the data
    access, the routing, the TfL calls and the Tkinter window in one 985-line
    file, which is why none of it could be exercised in isolation.

WHAT'S NEW
    tfl.py      the only file that makes outbound HTTP calls (Phase 2)
    seed.py     pure transforms from TfL payloads to model rows (Phase 2)
    graph_loader.py   rows in, engine Network out (Phase 6) - the boundary
"""
