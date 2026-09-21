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
 *     The planner top left, where reading starts. The map key and line
 *     status bottom right, stacked in one column: reference material you
 *     read once, kept away from the one panel that changes size.
 *
 *     Which corner is not arbitrary, and the empty one is the lesson. The
 *     API status card used to sit bottom left, where the planner grew over
 *     the top of it; the key went there next and the same thing happened to
 *     it. Nothing goes under the planner.
 *
 *     TfL's palette, from their published standards. The line colours are
 *     NOT here: those come out of the database with the network, so a line
 *     changing colour is a reseed rather than a frontend change.
 */

import { useState } from 'react'
import LineStatus from './components/LineStatus'
import MapKey from './components/MapKey'
import ObjectiveToggle, { OBJECTIVES } from './components/ObjectiveToggle'
import RoutePanel from './components/RoutePanel'
import StationSearch from './components/StationSearch'
import TubeMap from './components/TubeMap'
import { useLiveStatus } from './hooks/useLiveStatus'
import { useNetwork } from './hooks/useNetwork'
import { useRoute } from './hooks/useRoute'

export default function App() {
  const [mapError, setMapError] = useState(null)

  // Whether the planner is out of the way. The map is the thing worth looking
  // at once a route is on it, and on a laptop the panel covers a quarter of
  // the network including most of west London.
  //
  // The map itself is unaffected: its container is the full window either
  // way, with the cards floating over it, so nothing is resized and MapLibre
  // is never told anything changed. Hiding a panel that was only ever on top
  // is the cheapest possible version of this.
  const [plannerHidden, setPlannerHidden] = useState(false)
  const {
    network,
    loading: networkLoading,
    error: networkError,
    retry: retryNetwork,
  } = useNetwork()

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

  // fixed inset-0, not h-screen w-screen. 100vw INCLUDES the scrollbar on
  // Windows, so the moment anything makes one appear this element is wider
  // than the visible page and the bottom-right card sits past the right edge,
  // clipped away. inset-0 on a fixed element is exactly the viewport, with no
  // such arithmetic.
  //
  // overflow-CLIP, not overflow-hidden, and the difference is not cosmetic.
  // `hidden` still creates a scroll container: it stops the *user* scrolling,
  // and scripts and the browser itself scroll it freely. So focusing anything
  // inside - a chip's sr-only radio, say - let the browser scroll this shell
  // 108px to bring it into view, taking the whole planner off the top of a
  // laptop screen with no way to bring it back, because the wheel does
  // nothing on an overflow-hidden element.
  //
  // `clip` creates no scroll container at all. Nothing can scroll it: not
  // focus, not scrollIntoView, not anything added later. See ISSUES.md #27.
  return (
    <main className="bg-tfl-paper text-tfl-ink fixed inset-0 overflow-clip font-sans">
      <TubeMap network={network} route={route} onError={setMapError} />

      {/* Everything below floats over the map. pointer-events-none on the
          wrapper and auto on each card, so dragging the map still works in
          the gaps between them.
 
          Each card is positioned in its own corner rather than laid out in a
          shared column. They used to be flex children of one flex-col, which
          meant the planner's max-height claimed the whole column and left the
          status panel whatever was over - so on a short screen the expanded
          line list was cut off, and hiding the planner "fixed" it. Two cards
          in two corners cannot compete for the same height. */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute top-4 left-4">
          {/* The planner. Bordered rather than shadowed: TfL's own material
              is flat and high contrast, and a soft drop shadow over a pale
              map reads as a web dashboard rather than as signage. */}
          {/* Standing in for the whole panel, so the way back is where the
              thing that left used to be. A control that reappears somewhere
              else is a control people hunt for. */}
          {plannerHidden && (
            <button
              type="button"
              onClick={() => setPlannerHidden(false)}
              className="bg-tfl-blue hover:bg-tfl-blue-dark pointer-events-auto px-4 py-2.5 text-sm font-bold text-white shadow-xl"
            >
              Show planner
            </button>
          )}

          {/* Hidden with CSS rather than unmounted. The search boxes hold
              what you typed in their own state, so taking them out of the
              tree throws it away: hiding the planner with two stations
              chosen and showing it again left both boxes blank, while the
              route below was still planned from stations the page no longer
              displayed. display:none keeps them mounted and their state
              intact. */}
          <div className={plannerHidden ? 'hidden' : undefined}>
            <div className="border-tfl-ink/10 pointer-events-auto flex max-h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-sm flex-col overflow-hidden border bg-white shadow-xl">
              <header className="bg-tfl-blue flex items-start justify-between gap-3 px-4 py-3 text-white">
                <div>
                  <h1 className="text-lg leading-tight font-bold tracking-tight">
                    Tube Router
                  </h1>
                  <p className="text-xs text-white/70">
                    Plan a journey on the London Underground
                  </p>
                </div>

                {/* Named rather than an icon. A pair of arrows means "full
                    screen" to some people and "fit to window" to others, and
                    the two are different things. */}
                <button
                  type="button"
                  onClick={() => setPlannerHidden(true)}
                  className="shrink-0 border border-white/30 px-2 py-1 text-xs font-medium whitespace-nowrap hover:bg-white/15"
                >
                  Hide
                </button>
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
                  stations={network?.stations}
                />

                {networkLoading && (
                  <p className="text-tfl-grey mt-3 text-sm">Loading the network…</p>
                )}
                {/* Only after the retries in useNetwork have all failed, so
                    this means "it is really not there" rather than "the
                    container is still starting". Offering the button is the
                    point: without one the only way back is a page reload,
                    which is a thing a user has to think of. */}
                {networkError && (
                  <div className="border-tfl-red bg-tfl-red/5 mt-3 border-l-4 px-3 py-2">
                    <p className="text-tfl-red text-sm font-medium">
                      Could not load the network: {networkError}
                    </p>
                    <button
                      type="button"
                      onClick={retryNetwork}
                      className="border-tfl-red text-tfl-red hover:bg-tfl-red mt-2 border px-3 py-1 text-xs font-medium hover:text-white"
                    >
                      Try again
                    </button>
                  </div>
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
          </div>
        </div>

        {/* Bottom right, both of them, stacked in one column anchored to the
            corner so they grow upwards as they expand.

            The key started bottom left, which is empty and looked like the
            obvious home for it. It is not: the planner above it has no fixed
            height, and a long route pushes it down to within a few pixels of
            the bottom of the window - so expanding the key covered the amber
            disruption bar at the foot of the route. These two cannot collide
            with each other, because sharing a column means the browser lays
            them out rather than letting them overlap, and max-h with
            overflow on each is what a short window does instead of clipping.

            They also belong together. Both are read once and then ignored:
            what the marks mean, and what the railway is doing. */}
        <div className="absolute right-4 bottom-4 flex max-h-[calc(100vh-2rem)] flex-col items-end gap-3">
          <div className="border-tfl-ink/10 pointer-events-auto max-w-xs min-h-0 overflow-y-auto border bg-white/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
            <MapKey lines={network?.lines} />
          </div>

          <div className="border-tfl-ink/10 pointer-events-auto max-w-xs min-h-0 overflow-y-auto border bg-white/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
            <LineStatus
              status={status}
              lines={network?.lines}
              stations={network?.stations}
            />
          </div>
        </div>
      </div>
    </main>
  )
}
