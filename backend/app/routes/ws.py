"""WS /ws/status - live line status pushed as it changes."""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core import cache
from app.services import status_poller

router = APIRouter(prefix="/ws", tags=["status"])


# There is no authentication and nothing is read from the client. This is a broadcast of
# public information, and a socket that ignores whatever is sent to it cannot be talked
# into doing anything.
@router.websocket("/status")
async def status_socket(websocket: WebSocket) -> None:
    """Send the current status, then every change until the client leaves."""
    await websocket.accept()

    try:
        # Immediately, before subscribing. A client that connects on a quiet day would
        # otherwise show nothing until the next change, and a blank page looks exactly
        # like a broken one.
        await websocket.send_json(await status_poller.current())

        async with cache.subscription(status_poller.STATUS_CHANNEL) as messages:
            async for payload in messages:
                await websocket.send_json(payload)

    except WebSocketDisconnect:
        # The ordinary ending. A closed tab is not an error.
        return
    except (OSError, RuntimeError, asyncio.CancelledError):
        # Redis unreachable, or the server shutting down. The client keeps the last
        # picture it was given rather than the connection hanging open with nothing
        # behind it, and the socket is closed below.
        return
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()
