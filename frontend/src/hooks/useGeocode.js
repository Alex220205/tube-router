/**
 * Turning what somebody typed into stations they could use.
 *
 * WHY THIS EXISTS
 *     The station search is free: it reads our own database and debounces on
 *     every keystroke. This one costs money on every call, so it cannot work
 *     that way, and the difference is the whole reason it is a separate hook
 *     rather than a branch inside useStations.
 *
 *     Nothing is requested until somebody asks. `search(text)` is called from
 *     a click or an Enter, never from typing.
 *
 * NO 2021 EQUIVALENT
 *     The old project could only plan between names that were already in its
 *     own table. A destination it had not heard of was not a journey.
 *
 * WHAT'S NEW
 *     The answer is stored with the question it answers, as useRoute and
 *     usePlaces do - see docs/DECISIONS.md, Phase 8b. Search for one place,
 *     change your mind, search for another, and a slow reply for the first
 *     cannot land on top of the second.
 *
 *     `reset` exists because this is a mode the user enters and leaves. The
 *     other hooks in this project answer a question that is always on screen;
 *     this one answers a question that can be abandoned, and leaving its
 *     results behind would show matches for text that is no longer in the
 *     box.
 */

import { useCallback, useRef, useState } from 'react'
import { geocodePlace } from '../api'

/**
 * @returns {{results: Array, available: boolean, query: string | null,
 *   loading: boolean, error: string | null, search: (text: string) => void,
 *   reset: () => void}}
 */
export function useGeocode() {
  const [answer, setAnswer] = useState(null)
  const [asking, setAsking] = useState(null)

  // Held so a second search can abandon the first. Not state: nothing
  // renders from it, and setting state here would restart the effect it
  // belongs to.
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
    // Defaults true so nothing is hidden while the first answer is in
    // flight. It only becomes false once the server has said it could not
    // look at all.
    available: current?.payload?.available ?? true,
    query: asking,
    loading: asking !== null && current === null,
    error: current?.error ?? null,
    search,
    reset,
  }
}
