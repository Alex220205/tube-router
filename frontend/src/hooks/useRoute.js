/** Ask the API for a journey whenever the question changes. */

import { useEffect, useState } from 'react'
import { planRoute } from '../api'

export function useRoute(origin, destination, objective) {
  // The whole answer in one piece of state, tagged with the question. Three separate
  // flags could disagree with each other; these cannot.
  const [answer, setAnswer] = useState(null)

  const originId = origin?.naptan_id ?? null
  const destinationId = destination?.naptan_id ?? null

  // Null when half the question is missing, which is also the signal that there is
  // nothing to ask and nothing to show.
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

    // Abandoning the request is the cleanup, so it happens on every change of question
    // and on unmount without either being handled separately.
    return () => controller.abort()
  }, [question, originId, destinationId, objective])

  // Only an answer to the question currently on screen counts. Anything else is a
  // leftover, and loading is exactly the state of having a question without one.
  const current = answer?.question === question ? answer : null

  return {
    route: current?.route ?? null,
    loading: question !== null && current === null,
    error: current?.error ?? null,
  }
}
