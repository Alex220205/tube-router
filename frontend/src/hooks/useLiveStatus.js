/** Subscribe to live line status for as long as the page is open. */

import { useEffect, useState } from 'react'
import { openStatusSocket } from '../api'

export function useLiveStatus() {
  const [status, setStatus] = useState(null)

  useEffect(() => {
    const socket = openStatusSocket(setStatus)

    // Closing is the cleanup, so a page that unmounts does not leave a connection open
    // on the server holding a Redis subscription behind it.
    return () => socket.close()
  }, [])

  return status
}
