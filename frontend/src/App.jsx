/**
 * The application shell. In Phase 0 it reports whether the API is healthy.
 *
 * WHY THIS EXISTS
 *     Proof that the three parts of the stack are actually connected: the
 *     browser reaches the API, the API reaches Postgres, and CORS is
 *     configured correctly. A page that renders without talking to anything
 *     would prove none of that.
 *
 * NO 2021 EQUIVALENT
 *     The old project drew a Tkinter window in the same process as its data.
 *     There was nothing to connect, and therefore nothing that could be
 *     disconnected without anyone noticing.
 *
 * WHAT'S NEW
 *     The map, objective toggle and route panel arrive in Phase 8. The
 *     search box below is Phase 3, and is the first part of this project a
 *     person can actually use.
 */

import { useEffect, useState } from 'react'
import { fetchHealth } from './api'
import StationSearch from './components/StationSearch'

// Three distinct outcomes, and the difference between the last two matters:
// "degraded" means the API answered and told us Postgres is down;
// "unreachable" means the API itself did not answer. They look similar on
// screen and have completely different causes.
const LOADING = 'loading'
const REACHED = 'reached'
const UNREACHABLE = 'unreachable'

export default function App() {
  const [state, setState] = useState(LOADING)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    fetchHealth()
      .then((payload) => {
        // The component can unmount before the request settles — in
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
    <main className="mx-auto max-w-xl p-8 font-sans">
      <h1 className="text-2xl font-semibold">Tube Router</h1>
      <p className="mt-1 text-sm text-gray-500">Phase 0 — scaffold</p>

      <section className="mt-6 rounded-lg border border-gray-200 p-4">
        <h2 className="text-sm font-medium tracking-wide text-gray-500 uppercase">
          API status
        </h2>

        {state === LOADING && <p className="mt-2">Checking…</p>}

        {state === UNREACHABLE && (
          <div className="mt-2">
            <p className="font-medium text-red-600">API unreachable</p>
            <p className="mt-1 text-sm text-gray-500">{error}</p>
          </div>
        )}

        {state === REACHED && (
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
            <dt className="text-gray-500">Status</dt>
            <dd
              className={health.status === 'ok' ? 'text-green-700' : 'text-amber-700'}
            >
              {health.status}
            </dd>

            <dt className="text-gray-500">Database</dt>
            <dd
              className={health.database === 'ok' ? 'text-green-700' : 'text-amber-700'}
            >
              {health.database}
            </dd>

            <dt className="text-gray-500">Version</dt>
            <dd>{health.version}</dd>
          </dl>
        )}
      </section>

      <StationSearch />
    </main>
  )
}
