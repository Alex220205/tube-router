"""
WS /ws/status - live line status pushed as it changes.

WHY THIS EXISTS
    Polling /status from the browser would work, and it would mean every open
    tab asking every few seconds for an answer that changes maybe twice an
    hour. A socket costs one connection and sends only when something has
    actually happened.

    The interesting part is not the socket, it is **Redis pub/sub behind it**.
    The poller runs in one worker; a browser may be connected to another. An
    in-process broadcast would work perfectly with one worker and silently
    fail with two, which is the kind of thing that is only discovered when the
    service is busy enough to need two.

NO 2021 EQUIVALENT
    The old project was a Tkinter window reading SQLite in the same process.
    There was nothing to push to and nothing to push from - status was fetched
    once at launch and never changed again while the program ran.

WHAT'S NEW
    The current picture is sent immediately on connect, before any subscription
    traffic. A client that connected during a quiet spell would otherwise sit
    blank until the next change, which could be an hour - and a page showing
    nothing is indistinguishable from a page whose socket is broken.
"""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core import cache
from app.services import status_poller

router = APIRouter(tags=["status"])


@router.websocket("/ws/status")
async def status_socket(websocket: WebSocket) -> None:
    """Send the current status, then every change until the client leaves."""
    await websocket.accept()

    try:
        # Immediately, before subscribing. A client that connects on a quiet
        # day would otherwise show nothing until the next change, and a blank
        # page looks exactly like a broken one.
        await websocket.send_json(await status_poller.current())

        async with cache.subscription(status_poller.STATUS_CHANNEL) as messages:
            async for payload in messages:
                await websocket.send_json(payload)

    except WebSocketDisconnect:
        # The ordinary ending. A closed tab is not an error.
        return
    except (OSError, RuntimeError, asyncio.CancelledError):
        # Redis unreachable, or the server shutting down. The client keeps the
        # last picture it was given rather than the connection hanging open
        # with nothing behind it, and the socket is closed below.
        return
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()
