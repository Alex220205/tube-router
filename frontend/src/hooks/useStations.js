/** Search stations as the user types. */

import { useEffect, useRef, useState } from 'react'
import { fetchStations } from '../api'

// Long enough that a normal typing burst is one request, short enough that the list
// does not feel like it is lagging behind the keyboard.
const DEBOUNCE_MS = 250

export function useStations(query) {
  // One piece of state, tagged with the query it answers. Three separate values -
  // stations, loading, error - could each belong to a different query; this cannot.
  const [answer, setAnswer] = useState(null)
  const controller = useRef(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      // Abandon whatever is still in flight. Its answer is for a query the user has
      // already moved past.
      controller.current?.abort()
      const current = new AbortController()
      controller.current = current

      fetchStations(query, current.signal)
        .then((results) => {
          if (current.signal.aborted) return
          setAnswer({ query, stations: results, error: null })
        })
        .catch((err) => {
          // An abort is this hook's own doing, not a failure to report.
          if (current.signal.aborted || err.name === 'AbortError') return
          setAnswer({ query, stations: [], error: err.message })
        })
    }, DEBOUNCE_MS)

    return () => clearTimeout(timer)
  }, [query])

  // Only an answer to the text currently in the box counts. Anything else is a
  // leftover, and "loading" is exactly the state of having text without an answer to it
  // - which starts at the keystroke, not 250ms later when the request goes out.
  const current = answer?.query === query ? answer : null

  return {
    stations: current?.stations ?? [],
    loading: current === null,
    error: current?.error ?? null,
  }
}
