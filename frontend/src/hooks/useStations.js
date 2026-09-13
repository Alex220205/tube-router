/**
 * Search stations as the user types.
 *
 * WHY THIS EXISTS
 *     Keeps the fetching, the debounce and the cancellation out of the
 *     component, so StationSearch is about rendering and this is about
 *     asking. It also means the awkward part — what happens when answers
 *     come back out of order — is testable without rendering anything.
 *
 * NO 2021 EQUIVALENT
 *     The old project had no client and no server. The Tkinter window read
 *     objects in the same process, so there was nothing asynchronous to get
 *     wrong.
 *
 * WHAT'S NEW
 *     Two things the naive version gets wrong.
 *
 *     Debouncing, so typing "victoria" is one request rather than eight.
 *
 *     Cancellation, which matters more. Without it a slow response for "o"
 *     can land after a fast one for "oxford" and overwrite it — the user sees
 *     results for something they finished typing a second ago, and nothing
 *     looks broken enough to report.
 */

import { useEffect, useRef, useState } from 'react'
import { fetchStations } from '../api'

// Long enough that a normal typing burst is one request, short enough that
// the list does not feel like it is lagging behind the keyboard.
const DEBOUNCE_MS = 250

/**
 * @param {string} query What the user has typed.
 * @returns {{stations: Array, loading: boolean, error: string | null}}
 */
export function useStations(query) {
  const [stations, setStations] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const controller = useRef(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      // Abandon whatever is still in flight. Its answer is for a query the
      // user has already moved past.
      controller.current?.abort()
      const current = new AbortController()
      controller.current = current

      setLoading(true)
      fetchStations(query, current.signal)
        .then((results) => {
          if (current.signal.aborted) return
          setStations(results)
          setError(null)
        })
        .catch((err) => {
          // An abort is this hook's own doing, not a failure to report.
          if (current.signal.aborted || err.name === 'AbortError') return
          setError(err.message)
          setStations([])
        })
        .finally(() => {
          if (!current.signal.aborted) setLoading(false)
        })
    }, DEBOUNCE_MS)

    return () => clearTimeout(timer)
  }, [query])

  return { stations, loading, error }
}
