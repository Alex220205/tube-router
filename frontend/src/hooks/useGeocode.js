/** Turning what somebody typed into stations they could use. */

import { useCallback, useRef, useState } from 'react'
import { geocodePlace } from '../api'

export function useGeocode() {
  const [answer, setAnswer] = useState(null)
  const [asking, setAsking] = useState(null)

  // Held so a second search can abandon the first. Not state: nothing renders from it,
  // and setting state here would restart the effect it belongs to.
  const inFlight = useRef(null)

  const search = useCallback((text) => {
    const query = text.trim()
    if (!query) return

    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    setAsking(query)

    geocodePlace(query, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return
        setAnswer({ query, payload, error: null })
      })
      .catch((err) => {
        if (controller.signal.aborted || err.name === 'AbortError') return
        setAnswer({ query, payload: null, error: err.message })
      })
  }, [])

  const reset = useCallback(() => {
    inFlight.current?.abort()
    inFlight.current = null
    setAsking(null)
    setAnswer(null)
  }, [])

  const current = answer?.query === asking ? answer : null

  return {
    results: current?.payload?.results ?? [],
    // Defaults true so nothing is hidden while the first answer is in flight. It only
    // becomes false once the server has said it could not look at all.
    available: current?.payload?.available ?? true,
    query: asking,
    loading: asking !== null && current === null,
    error: current?.error ?? null,
    search,
    reset,
  }
}
