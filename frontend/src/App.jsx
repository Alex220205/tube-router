/**
 * The application shell: a map, with everything else floating over it.
 *
 * WHY THIS EXISTS
 *     Somewhere to assemble the pieces. The layout is the point of this file
 *     and the reason Tailwind was chosen in Phase 0 - docs/DECISIONS.md made
 *     the case as "a full-bleed map canvas with panels floating on top of it,
 *     which is absolute positioning over a fixed-size container", and this is
 *     the first phase where that is what it actually is.
 *
 * NO 2021 EQUIVALENT
 *     The old project drew a Tkinter window in the same process as its data.
 *     There was nothing to connect, and therefore nothing that could be
 *     disconnected without anyone noticing.
 *
 * WHAT'S NEW
 *     Two stations instead of one search box. This file holds the pair
 *     because both ends of a journey have to be known in one place to ask for
 *     a route, and neither search box has any business knowing about the
 *     other.
 */

import { useEffect, useState } from 'react'
import { fetchHealth } from './api'
import LineStatus from './components/LineStatus'
import ObjectiveToggle, { OBJECTIVES } from './components/ObjectiveToggle'
import RoutePanel from './components/RoutePanel'
import StationSearch from './components/StationSearch'
import TubeMap from './components/TubeMap'
import { useNetwork } from './hooks/useNetwork'
import { useLiveStatus } from './hooks/useLiveStatus'
import { useRoute } from './hooks/useRoute'

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
  const { network, loading: networkLoading, error: networkError } = useNetwork()

  // The question being asked. Held here because both ends of a journey have
  // to be known in one place to ask for a route, and neither search box has
  // any business knowing about the other.
  const [origin, setOrigin] = useState(null)
  const [destination, setDestination] = useState(null)
  const [objective, setObjective] = useState(OBJECTIVES[0].value)

  const { route, loading: routeLoading, error: routeError } = useRoute(
    origin,
    destination,
    objective,
  )

  // Opened once and left open. The first message is the current picture, so
  // there is nothing to fetch alongside it - see hooks/useLiveStatus.js.
  const status = useLiveStatus()

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
    <main className="relative h-screen w-screen overflow-hidden font-sans">
      <TubeMap network={network} route={route} />

      {/* Everything below floats over the map. pointer-events-none on the
          wrapper and auto on each card, so dragging the map still works in
          the gaps between them. */}
      <div className="pointer-events-none absolute inset-0 p-4">
        <div className="pointer-events-auto flex max-h-full w-full max-w-sm flex-col overflow-y-auto rounded-lg bg-white/95 p-4 shadow-lg backdrop-blur">
          <h1 className="text-xl font-semibold">Tube Router</h1>
          <p className="mt-0.5 text-sm text-gray-500">
            Plan a journey on the London Underground
          </p>

          <StationSearch
            id="origin"
            label="From"
            selected={origin}
            onSelect={setOrigin}
          />
          <StationSearch
            id="destination"
            label="To"
            selected={destination}
            onSelect={setDestination}
          />

          <ObjectiveToggle value={objective} onChange={setObjective} />

          <RoutePanel
            route={route}
            loading={routeLoading}
            error={routeError}
            objective={objective}
            lines={network?.lines}
          />

          {networkLoading && (
            <p className="mt-3 text-sm text-gray-500">Loading the network…</p>
          )}
          {networkError && (
            <p className="mt-3 text-sm text-red-600">
              Could not load the network: {networkError}
            </p>
          )}
        </div>

        {/* Bottom right, opposite the health card. It is about the railway
            rather than about this service, and the two being told apart at a
            glance is the point of them not sharing a corner. */}
        <div className="pointer-events-auto absolute right-4 bottom-4 max-w-xs rounded-lg bg-white/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
          <h2 className="mb-1 font-medium tracking-wide text-gray-500 uppercase">
            Line status
          </h2>
          <LineStatus status={status} lines={network?.lines} />
        </div>

        {/* Bottom left, small. It proves the stack is connected, which is
            worth being able to see and not worth leading with. */}
        <div className="pointer-events-auto absolute bottom-4 left-4 rounded-lg bg-white/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
          <h2 className="font-medium tracking-wide text-gray-500 uppercase">
            API status
          </h2>

          {state === LOADING && <p className="mt-1">Checking…</p>}

          {state === UNREACHABLE && (
            <div className="mt-1">
              <p className="font-medium text-red-600">API unreachable</p>
              <p className="mt-0.5 text-gray-500">{error}</p>
            </div>
          )}

          {state === REACHED && (
            <dl className="mt-1 grid grid-cols-2 gap-x-3">
              <dt className="text-gray-500">Status</dt>
              <dd
                className={health.status === 'ok' ? 'text-green-700' : 'text-amber-700'}
              >
                {health.status}
              </dd>

              <dt className="text-gray-500">Database</dt>
              <dd
                className={
                  health.database === 'ok' ? 'text-green-700' : 'text-amber-700'
                }
              >
                {health.database}
              </dd>

              <dt className="text-gray-500">Version</dt>
              <dd>{health.version}</dd>
            </dl>
          )}
        </div>
      </div>
    </main>
  )
}
