/**
 * Whether the API is up, and whether it can reach Postgres.
 *
 * WHY THIS EXISTS
 *     **Not currently mounted.** It was the corner card on the map until it
 *     was taken off for looking like a debug panel on a page meant to look
 *     like a journey planner. Kept whole, working and tested rather than
 *     deleted, because the thing it shows is worth showing somewhere - an
 *     about page, a footer, a deploy check - and reconstructing it later from
 *     a diff would cost more than a file that already works.
 *
 *     Drop it back in with `<ApiStatus />`. It fetches its own health and
 *     holds its own state, so nothing else has to know about it.
 *
 * NO 2021 EQUIVALENT
 *     The old project was one process reading SQLite. There was no service to
 *     be up or down, and nothing that could be running while its database was
 *     not.
 *
 * WHAT'S NEW
 *     The distinction this exists for. **Degraded** means the API answered and
 *     told us Postgres is unreachable; **unreachable** means the API itself
 *     did not answer. They look almost identical on screen and send you to
 *     completely different places to fix them, so the page never conflates
 *     them - which is the one thing its tests actually check.
 */

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
        // The component can unmount before the request settles - in
        // development, React's StrictMode guarantees it by mounting twice.
        // Setting state afterwards is a warning and a leak.
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
