/**
 * Ask the API for a journey whenever the question changes.
 *
 * WHY THIS EXISTS
 *     Keeps the fetching and the cancellation out of the components, so App
 *     is about layout and RoutePanel is about rendering an answer. Same
 *     { data, loading, error } shape as useStations and useNetwork, so App
 *     handles all three the same way rather than learning a third convention.
 *
 * NO 2021 EQUIVALENT
 *     The old project's search wrote into its own attributes and the Tkinter
 *     window read them back out of the same object. Nothing was asynchronous,
 *     so nothing could arrive in the wrong order.
 *
 * WHAT'S NEW
 *     An answer is stored with the question it answers, and only shown while
 *     the two still match. docs/DECISIONS.md records the Phase 3 version of
 *     this bug: a slow answer for "fastest" landing after a fast one for
 *     "step-free" and overwriting it, so the page shows a route for a
 *     question the user changed a second ago and nothing looks broken enough
 *     to report.
 *
 *     useStations solves it by discarding late answers. This is stricter -
 *     a stale answer cannot be rendered even if it does arrive, because it no
 *     longer matches the question on screen - and it means `loading` is
 *     derived rather than a third flag that can disagree with the other two.
 */

import { useEffect, useState } from 'react'
import { planRoute } from '../api'

/**
 * @param {object | null} origin Station object, or null if none is chosen.
 * @param {object | null} destination Station object, or null.
 * @param {string} objective One of fastest, fewest_changes, step_free.
 * @returns {{route: object | null, loading: boolean, error: string | null}}
 *   route is null until both ends are chosen and an answer has arrived. A
 *   route that does not exist is still a route object, carrying found: false
 *   and a reason - see api.js.
 */
export function useRoute(origin, destination, objective) {
  // The whole answer in one piece of state, tagged with the question. Three
  // separate flags could disagree with each other; these cannot.
  const [answer, setAnswer] = useState(null)

  const originId = origin?.naptan_id ?? null
  const destinationId = destination?.naptan_id ?? null

  // Null when half the question is missing, which is also the signal that
  // there is nothing to ask and nothing to show.
  const question =
    originId && destinationId ? `${originId}|${destinationId}|${objective}` : null

  useEffect(() => {
    if (!question) return

    const controller = new AbortController()

    planRoute(
      { origin: originId, destination: destinationId, objective },
      controller.signal,
    )
      .then((route) => {
        if (controller.signal.aborted) return
        setAnswer({ question, route, error: null })
      })
      .catch((err) => {
        // An abort is this hook's own doing, not a failure to report.
        if (controller.signal.aborted || err.name === 'AbortError') return
        setAnswer({ question, route: null, error: err.message })
      })

    // Abandoning the request is the cleanup, so it happens on every change of
    // question and on unmount without either being handled separately.
    return () => controller.abort()
  }, [question, originId, destinationId, objective])

  // Only an answer to the question currently on screen counts. Anything else
  // is a leftover, and loading is exactly the state of having a question
  // without one.
  const current = answer?.question === question ? answer : null

  return {
    route: current?.route ?? null,
    loading: question !== null && current === null,
    error: current?.error ?? null,
  }
}
