/**
 * Fetch the whole tube network, once.
 *
 * WHY THIS EXISTS
 *     The map needs every station and segment before it can draw anything, so
 *     unlike useStations there is no query and nothing to debounce - it runs
 *     once and holds the answer for the life of the page.
 *
 *     Same { data, loading, error } shape as useStations returns, so App.jsx
 *     handles it the way it already handles the other two rather than
 *     learning a third convention.
 *
 * NO 2021 EQUIVALENT
 *     Nothing to fetch. The old project read SQLite in the same process, and
 *     had no coordinates to draw with in any case.
 */

import { useEffect, useState } from 'react'
import { fetchNetwork } from '../api'

/**
 * @returns {{network: object | null, loading: boolean, error: string | null}}
 *   network is null until the first response arrives.
 */
export function useNetwork() {
  const [network, setNetwork] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    // The component can unmount before this settles - React's StrictMode
    // guarantees it in development by mounting twice - and setting state
    // afterwards is a warning and a leak.
    let cancelled = false

    fetchNetwork()
      .then((payload) => {
        if (cancelled) return
        setNetwork(payload)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // Empty deps: once per mount. The network changes when the seed runs, not
    // while someone is looking at it.
  }, [])

  return { network, loading, error }
}
