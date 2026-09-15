/**
 * Subscribe to live line status for as long as the page is open.
 *
 * WHY THIS EXISTS
 *     Phase 7 built the poller, the pub/sub and the WebSocket endpoint, and
 *     nothing has ever connected to it. This is the client.
 *
 * WHAT THE 2021 VERSION DID
 *     Where:  database[works].py, lines.service_status
 *     How:    Status was read from SQLite, which was emptied and refilled on
 *             launch. The window read it once.
 *     Wrong:  The value was as old as the process. Start the program at nine
 *             and the "live" status still said nine o'clock at lunchtime,
 *             with nothing on screen to say so.
 *
 * WHAT'S NEW
 *     There is no companion fetch of GET /status here, and that is a decision
 *     rather than an omission. routes/ws.py sends the current picture
 *     immediately on connect, before subscribing, for exactly the reason a
 *     fetch would have been for - so adding one would be two requests racing
 *     to set the same state, which is harmless until the day it is not.
 */

import { useEffect, useState } from 'react'
import { openStatusSocket } from '../api'

/**
 * @returns {object | null} The latest StatusResponse, or null before the
 *   socket has said anything. Null and `as_of: null` are different: the first
 *   means nobody has answered yet, the second means the server answered and
 *   does not know - and both render as unavailable rather than as fine.
 */
export function useLiveStatus() {
  const [status, setStatus] = useState(null)

  useEffect(() => {
    const socket = openStatusSocket(setStatus)

    // Closing is the cleanup, so a page that unmounts does not leave a
    // connection open on the server holding a Redis subscription behind it.
    return () => socket.close()
  }, [])

  return status
}
