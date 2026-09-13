"""
Collects every endpoint router into one for main.py to mount.

WHY THIS EXISTS
    So that adding an endpoint file never means editing main.py. Without this
    aggregator, main.py slowly becomes a list of everything in the project
    and a permanent merge conflict.

NO 2021 EQUIVALENT
    There were no endpoints. The old project was a single Tkinter window, and
    its equivalent of routing was a method call.

WHAT'S NEW
    stations, routes, ws and status join here in Phases 3, 6 and 7. Each is
    one import and one include_router line, and main.py does not change.
"""

from fastapi import APIRouter

from . import health

api_router = APIRouter()
api_router.include_router(health.router)
