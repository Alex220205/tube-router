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
 *     Three cards in three corners, and which corner is not arbitrary. The
 *     planner is top left where reading starts. Line status is bottom right,
 *     because it is about the railway and you look at it when a route
 *     surprises you. API status is top right and deliberately the smallest
 *     thing on screen - it is diagnostics, and it used to sit bottom left
 *     where the planner panel grew over the top of it.
 *
 *     TfL's palette, from their published standards. The line colours are
 *     NOT here: those come out of the database with the network, so a line
 *     changing colour is a reseed rather than a frontend change.
 */

import { useEffect, useState } from 'react'
import { fetchHealth } from './api'
import LineStatus from './components/LineStatus'
import ObjectiveToggle, { OBJECTIVES } from './components/ObjectiveToggle'
import RoutePanel from './components/RoutePanel'
import StationSearch from './components/StationSearch'
import TubeMap from './components/TubeMap'
import { useLiveStatus } from './hooks/useLiveStatus'
import { useNetwork } from './hooks/useNetwork'
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
  const [mapError, setMapError] = useState(null)
  const { network, loading: networkLoading, error: networkError } = useNetwork()

  // The question being asked. Held here because both ends of a journey have
  // to be known in one place to ask for a route, and neither search box has
  // any business knowing about the other.
  const [origin, setOrigin] = useState(null)
  const [destination, setDestination] = useState(null)
  const [objective, setObjective] = useState(OBJECTIVES[0].value)

  const {
    route,
    loading: routeLoading,
    error: routeError,
  } = useRoute(origin, destination, objective)

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
    <main className="bg-tfl-paper text-tfl-ink relative h-screen w-screen overflow-hidden font-sans">
      <TubeMap network={network} route={route} onError={setMapError} />

      {/* Everything below floats over the map. pointer-events-none on the
          wrapper and auto on each card, so dragging the map still works in
          the gaps between them. */}
      <div className="pointer-events-none absolute inset-0 flex flex-col p-4">
        <div className="flex items-start justify-between gap-4">
          {/* The planner. Bordered rather than shadowed: TfL's own material
              is flat and high contrast, and a soft drop shadow over a pale
              map reads as a web dashboard rather than as signage. */}
          <div className="border-tfl-ink/10 pointer-events-auto flex max-h-[calc(100vh-2rem)] w-full max-w-sm flex-col overflow-hidden border bg-white shadow-xl">
            <header className="bg-tfl-blue px-4 py-3 text-white">
              <h1 className="text-lg leading-tight font-bold tracking-tight">
                Tube Router
              </h1>
              <p className="text-xs text-white/70">
                Plan a journey on the London Underground
              </p>
            </header>

            <div className="overflow-y-auto px-4 pt-1 pb-4">
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
                <p className="text-tfl-grey mt-3 text-sm">Loading the network…</p>
              )}
              {networkError && (
                <p className="text-tfl-red mt-3 text-sm font-medium">
                  Could not load the network: {networkError}
                </p>
              )}

              {/* A map that fails silently is a white rectangle nobody can
                  diagnose. Whatever MapLibre reports goes here. */}
              {mapError && (
                <p className="border-tfl-red bg-tfl-red/5 text-tfl-red mt-3 border-l-4 px-3 py-2 text-sm">
                  The map could not be drawn: {mapError}
                </p>
              )}
            </div>
          </div>

          {/* Top right, and the smallest thing on screen. It proves the stack
              is connected, which is worth being able to see and is not worth
              any more room than this. */}
          <div className="border-tfl-ink/10 pointer-events-auto border bg-white/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
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
        </div>

        {/* Bottom right. About the railway rather than about this service,
            which is why it does not share a corner with the one above. */}
        <div className="mt-auto flex justify-end">
          <div className="border-tfl-ink/10 pointer-events-auto max-w-xs border bg-white/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
            <h2 className="text-tfl-grey mb-1 font-bold tracking-wider uppercase">
              Line status
            </h2>
            <LineStatus status={status} lines={network?.lines} />
          </div>
        </div>
      </div>
    </main>
  )
}
