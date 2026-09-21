/**
 * Search stations as the user types.
 *
 * WHY THIS EXISTS
 *     Keeps the fetching, the debounce and the cancellation out of the
 *     component, so StationSearch is about rendering and this is about
 *     asking. It also means the awkward part - what happens when answers
 *     come back out of order - is testable without rendering anything.
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
 *     can land after a fast one for "oxford" and overwrite it - the user sees
 *     results for something they finished typing a second ago, and nothing
 *     looks broken enough to report.
 *
 *     And the answer is stored with the question it answers, which the first
 *     version did not do and which the other three fetching hooks already
 *     did. docs/DECISIONS.md said as much in Phase 8b: "this is stricter
 *     than useStations ... worth knowing about when the older one is next
 *     touched."
 *
 *     What it cost, found by an end to end sweep rather than by reading:
 *     for the 250ms between a keystroke and the debounced request, this hook
 *     returned the PREVIOUS query's results with `loading` false. Pick Oxford
 *     Circus, type "heathrow", press Enter at once - and Enter, seeing one
 *     result, picked Oxford Circus. The same window flashed "No stations
 *     match" for text that does match, and let Enter fire a billed geocode
 *     for it. Three wrong answers from one stale value, none of them raising.
 *
 *     Now results for any other query are simply not returned, and `loading`
 *     is true from the keystroke rather than from the request. A stale answer
 *     cannot be shown because it cannot be read. See ISSUES.md #31.
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
  // One piece of state, tagged with the query it answers. Three separate
  // values - stations, loading, error - could each belong to a different
  // query; this cannot.
  const [answer, setAnswer] = useState(null)
  const controller = useRef(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      // Abandon whatever is still in flight. Its answer is for a query the
      // user has already moved past.
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

  // Only an answer to the text currently in the box counts. Anything else is
  // a leftover, and "loading" is exactly the state of having text without an
  // answer to it - which starts at the keystroke, not 250ms later when the
  // request goes out.
  const current = answer?.query === query ? answer : null

  return {
    stations: current?.stations ?? [],
    loading: current === null,
    error: current?.error ?? null,
  }
}
