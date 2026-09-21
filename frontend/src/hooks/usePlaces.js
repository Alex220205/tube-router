/**
 * What is near a station, fetched only once somebody asks.
 *
 * WHY THIS EXISTS
 *     The one hook in this project whose request costs money. Everything
 *     else here is a read of our own database; this reaches Google, and
 *     Google bills per call.
 *
 *     That changes the design in one specific way: `enabled`. The section
 *     this feeds is collapsed by default, and nothing is requested until it
 *     is opened. A hook that fetched on mount would spend a call on every
 *     route anyone plans, whether or not they ever looked.
 *
 * NO 2021 EQUIVALENT
 *     The old project called Places synchronously from the Tkinter event
 *     loop, with no caching, no cancellation and no concept of a request the
 *     user had already moved past.
 *
 * WHAT'S NEW
 *     The answer is stored with the question it answers, exactly as
 *     useRoute does - see docs/DECISIONS.md, Phase 8b. Change the
 *     destination or the category and a late reply for the old one simply
 *     stops matching, instead of overwriting the new one with restaurants
 *     near somewhere you are no longer going.
 */

import { useEffect, useState } from 'react'
import { fetchPlaces } from '../api'

/**
 * @param {string | null} naptanId The station to look around, or null.
 * @param {string} kind Category, e.g. "restaurant".
 * @param {boolean} enabled Whether to ask at all. False while the section is
 *   collapsed, which is what keeps an unopened panel free.
 * @returns {{places: Array, available: boolean, loading: boolean,
 *   error: string | null}}
 */
export function usePlaces(naptanId, kind, enabled) {
  const [answer, setAnswer] = useState(null)

  // Null means there is nothing to ask, which covers both "no destination
  // yet" and "nobody has opened the section".
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
    // Defaults to true so that nothing is hidden while the first answer is
    // still in flight. The section only disappears once the server has
    // actually said it cannot look.
    available: current?.payload?.available ?? true,
    loading: question !== null && current === null,
    error: current?.error ?? null,
  }
}
