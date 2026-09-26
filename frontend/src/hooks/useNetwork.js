/** The whole network, fetched once when the page opens. */

import { useCallback, useEffect, useState } from 'react'
import { fetchNetwork } from '../api'

// When to try again after a failure, in milliseconds. Five attempts spread over fifteen
// seconds, front loaded so a stack that is nearly ready is not kept waiting, and long
// enough at the end to cover a cold container.
const RETRY_DELAYS_MS = [500, 1500, 3500, 7500]

export function useNetwork() {
  const [network, setNetwork] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Bumped to start the effect again. A counter rather than a boolean, because a second
  // manual retry has to be distinguishable from the first.
  const [attempt, setAttempt] = useState(0)

  const retry = useCallback(() => {
    setLoading(true)
    setError(null)
    setAttempt((n) => n + 1)
  }, [])

  useEffect(() => {
    // The component can unmount before this settles - React's StrictMode guarantees it
    // in development by mounting twice - and setting state afterwards is a warning and
    // a leak.
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
            // Still trying, so the page keeps saying so. Reporting an error between
            // attempts would show a failure that is about to fix itself.
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
    // `attempt` only: the network changes when the seed runs, not while somebody is
    // looking at it, so this is once per mount plus once per manual retry.
  }, [attempt])

  return { network, loading, error, retry }
}
