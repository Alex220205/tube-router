/** Whether the API is up, and whether it can reach Postgres. */

import { useEffect, useState } from 'react'
import { fetchHealth } from '../api'

const LOADING = 'loading'
const REACHED = 'reached'
const UNREACHABLE = 'unreachable'

/** A small panel reporting whether the API and its database are answering. */
export default function ApiStatus() {
  const [state, setState] = useState(LOADING)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    fetchHealth()
      .then((payload) => {
        // The component can unmount before the request settles - in development,
        // React's StrictMode guarantees it by mounting twice. Setting state afterwards
        // is a warning and a leak.
        if (cancelled) return
        setHealth(payload)
        setState(REACHED)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message)
        setState(UNREACHABLE)
      })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="border-tfl-ink/10 border bg-white/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
      <h2 className="text-tfl-grey mb-1 font-bold tracking-wider uppercase">
        API status
      </h2>

      {state === LOADING && <p>Checking…</p>}

      {state === UNREACHABLE && (
        <div>
          <p className="text-tfl-red font-bold">API unreachable</p>
          <p className="text-tfl-grey mt-0.5">{error}</p>
        </div>
      )}

      {state === REACHED && (
        <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
          <dt className="text-tfl-grey">Status</dt>
          <dd
            className={
              health.status === 'ok'
                ? 'text-tfl-green font-medium'
                : 'text-tfl-red font-medium'
            }
          >
            {health.status}
          </dd>

          <dt className="text-tfl-grey">Database</dt>
          <dd
            className={
              health.database === 'ok'
                ? 'text-tfl-green font-medium'
                : 'text-tfl-red font-medium'
            }
          >
            {health.database}
          </dd>

          <dt className="text-tfl-grey">Version</dt>
          <dd>{health.version}</dd>
        </dl>
      )}
    </div>
  )
}
