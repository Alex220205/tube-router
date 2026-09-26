/** What is near a station, fetched only once somebody asks. */

import { useEffect, useState } from 'react'
import { fetchPlaces } from '../api'

export function usePlaces(naptanId, kind, enabled) {
  const [answer, setAnswer] = useState(null)

  // Null means there is nothing to ask, which covers both "no destination yet" and
  // "nobody has opened the section".
  const question = enabled && naptanId ? `${naptanId}|${kind}` : null

  useEffect(() => {
    if (!question) return

    const controller = new AbortController()

    fetchPlaces(naptanId, kind, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return
        setAnswer({ question, payload, error: null })
      })
      .catch((err) => {
        // An abort is this hook's own doing, not a failure to report.
        if (controller.signal.aborted || err.name === 'AbortError') return
        setAnswer({ question, payload: null, error: err.message })
      })

    return () => controller.abort()
  }, [question, naptanId, kind])

  const current = answer?.question === question ? answer : null

  return {
    places: current?.payload?.places ?? [],
    // Defaults to true so that nothing is hidden while the first answer is still in
    // flight. The section only disappears once the server has actually said it cannot
    // look.
    available: current?.payload?.available ?? true,
    loading: question !== null && current === null,
    error: current?.error ?? null,
  }
}
