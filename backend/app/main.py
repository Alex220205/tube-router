"""
The FastAPI application. Builds the app, applies middleware, mounts the API.

WHY THIS EXISTS
    One place where the application is assembled, and deliberately nothing
    else. No endpoints are defined here — they live in api/ and arrive
    through api/router.py — so this file stays short as the project grows.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, module level and the GUI class
    How:    There was no application object and no entry point in this sense.
            The file defined classes and then built a Tkinter window, so
            importing it started the program.
    Wrong:  Nothing could be imported without side effects, which is another
            reason none of it was testable: to get at a function you had to
            launch the user interface.

WHAT CHANGED AND WHY
    Importing this module constructs an app object and does nothing else. No
    server starts, no window opens, no connection is made. uvicorn runs it in
    production; the test suite imports it and drives it in-process without a
    server at all.

WHAT'S NEW
    CORS. The frontend runs on a different port from the API, which makes
    every request cross-origin, so the browser sends a preflight OPTIONS
    first and blocks the real request if the answer does not name its origin.
    The allowed list comes from config rather than being a wildcard.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from .config import get_settings

settings = get_settings()

app = FastAPI(
    title="Tube Router API",
    version=settings.version,
    summary="London Underground journey planning.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
