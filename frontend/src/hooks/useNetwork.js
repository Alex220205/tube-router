/**
 * The whole network, fetched once when the page opens.
 *
 * WHY THIS EXISTS
 *     The map cannot draw anything without every station and every link, and
 *     the route panel needs line names and colours. One fetch, held here, so
 *     nothing below has to ask twice.
 *
 * NO 2021 EQUIVALENT
 *     The old project rebuilt its graph from SQL on every single search and
 *     threw it away afterwards, in the same process as the window drawing it.
 *     Nothing was ever fetched, because nothing was ever remote.
 *
 * WHAT'S NEW
 *     It retries, and that is not a nicety.
 *
 *     This is the only request the entire page depends on, and it fires the
 *     instant the page opens - which on a freshly started stack is while the
 *     API container is still coming up. Measured: the API took about six
 *     seconds to answer /health at all, and once it did, /network came back
 *     in 0.42 seconds even with a cold cache.
 *
 *     So the failure was never a slow response. It was one attempt, made too
 *     early, with nothing behind it. The page then rendered with no map,
 *     line names as their codes and every colour grey, while the route
 *     planner carried on working perfectly - because that is a different
 *     request, made later, by which time the API was up. See ISSUES.md #26.
 *
 *     A person's instinct on seeing that is to reload, which works, and
 *     which is exactly what the page should have done for them.
 */

import { useCallback, useEffect, useState } from 'react'
import { fetchNetwork } from '../api'

// When to try again after a failure, in milliseconds. Five attempts spread
// over fifteen seconds, front loaded so a stack that is nearly ready is not
// kept waiting, and long enough at the end to cover a cold container.
//
// Measured against a real restart rather than picked: six seconds to a
// healthy API, so three attempts land inside that window and two more follow
// if something is genuinely slow.
const RETRY_DELAYS_MS = [500, 1500, 3500, 7500]

/**
 * @returns {{network: object | null, loading: boolean, error: string | null,
 *   retry: () => void}}
 */
export function useNetwork() {
  const [network, setNetwork] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Bumped to start the effect again. A counter rather than a boolean,
  // because a second manual retry has to be distinguishable from the first.
  const [attempt, setAttempt] = useState(0)

  const retry = useCallback(() => {
    setLoading(true)
    setError(null)
    setAttempt((n) => n + 1)
  }, [])

  useEffect(() => {
    // The component can unmount before this settles - React's StrictMode
    // guarantees it in development by mounting twice - and setting state
    // afterwards is a warning and a leak.
    let cancelled = false
    let timer = null

    function attemptFetch(tries) {
      fetchNetwork()
        .then((payload) => {
          if (cancelled) return
          setNetwork(payload)
          setError(null)
          setLoading(false)
        })
        .catch((err) => {
          if (cancelled) return

          const delay = RETRY_DELAYS_MS[tries]
          if (delay !== undefined) {
            // Still trying, so the page keeps saying so. Reporting an error
            // between attempts would show a failure that is about to fix
            // itself.
            timer = setTimeout(() => attemptFetch(tries + 1), delay)
            return
          }

          setError(err.message)
          setLoading(false)
        })
    }

    attemptFetch(0)

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
    // `attempt` only: the network changes when the seed runs, not while
    // somebody is looking at it, so this is once per mount plus once per
    // manual retry.
  }, [attempt])

  return { network, loading, error, retry }
}
