/** The journey, written out. */

import { useState } from 'react'
import { INK, STEP_FREE } from './MapKey'
import NearbyPlaces from './NearbyPlaces'
import { shortName } from '../lib/station-name'

// One sentence per reason the engine can give. Written for a traveller, not copied from
// the wire: "disconnected" is a correct description of a graph and tells a person
// nothing.
const REASONS = {
  unknown_origin: 'We do not have that starting station.',
  unknown_destination: 'We do not have that destination.',
  disconnected: 'No route between these two stations.',
}

// The same case, with the one piece of advice that actually helps. Step-free routing
// fails far more often than the network is genuinely disconnected - only 101 of 272
// stations have an accessible line at all - and "try another objective" is a remedy,
// where "no route" is a dead end.
const NO_STEP_FREE = 'No step-free route between these two stations.'

/**
 * Minutes, or hours and minutes. Seconds are below the precision of anything this
 * estimate is built from and printing them would imply otherwise.
 */
function duration(seconds) {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min`

  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} hr` : `${hours} hr ${rest} min`
}

export default function RoutePanel({
  route,
  loading,
  error,
  objective,
  lines,
  stations,
}) {
  // Which leg is open, stored with the route it belongs to.
  const [opened, setOpened] = useState(null)
  const openLeg = opened?.route === route ? opened.index : null
  if (error) {
    return (
      <p className="border-tfl-red bg-tfl-red/5 text-tfl-red mt-5 border-l-4 px-3 py-2 text-sm">
        Could not plan a route: {error}
      </p>
    )
  }

  if (loading) {
    return <p className="text-tfl-grey mt-5 text-sm">Planning…</p>
  }

  if (!route) return null

  if (!route.found) {
    const message =
      route.reason === 'disconnected' && objective === 'step_free'
        ? NO_STEP_FREE
        : (REASONS[route.reason] ?? 'No route.')

    return (
      <div className="border-tfl-line mt-5 border-t pt-4">
        <p className="text-sm font-medium">{message}</p>
        <Disruption route={route} lines={lines} />
      </div>
    )
  }

  const byCode = new Map((lines ?? []).map((line) => [line.code, line]))

  // NaPTAN ids of the step-free stations. Rebuilt each render rather than memoised: it
  // is 272 rows once per answer, and a useMemo here would cost more to read than it
  // saves.
  const stepFree = new Set(
    (stations ?? []).filter((s) => s.step_free).map((s) => s.naptan_id),
  )

  return (
    <div className="border-tfl-line mt-5 border-t pt-4">
      <div className="flex items-baseline gap-2">
        <p className="text-2xl leading-none font-bold">
          {duration(route.total_seconds)}
        </p>
        <p className="text-tfl-grey text-sm">
          {route.changes === 0
            ? 'direct'
            : `${route.changes} change${route.changes === 1 ? '' : 's'}`}
        </p>
      </div>

      {/* Stated only when true. "Not step-free" on a journey nobody asked to be
          step-free is a warning about a thing that was never promised. */}
      {route.step_free && (
        <p className="text-tfl-green mt-1 text-xs font-bold tracking-wide uppercase">
          Step-free throughout
        </p>
      )}

      <ol className="mt-4 space-y-3">
        {route.legs.map((leg, index) => {
          const line = byCode.get(leg.line)
          const stops = leg.stations.length - 1
          const open = openLeg === index
          const listId = `route-leg-${index}-stations`

          return (
            // Index as the key: legs have no id, and a journey's legs are only ever
            // replaced wholesale by a new answer, never reordered.
            <li key={index} className="flex gap-3">
              {/* The line's own colour, straight from the database. This is the one
                  place the page is unmistakably about the Tube rather than about
                  transport in general. */}
              <span
                className="mt-0.5 w-1.5 shrink-0"
                style={{ backgroundColor: line?.colour ?? '#6f777b' }}
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                {/* The summary IS the control. A separate "show stops" link would
                    put two targets on one leg, and the thing people aim at is the
                    leg. */}
                <button
                  type="button"
                  onClick={() => setOpened(open ? null : { route, index })}
                  aria-expanded={open}
                  aria-controls={listId}
                  className="hover:bg-tfl-paper -mx-1 flex w-full items-start gap-2 px-1 py-0.5 text-left"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-bold">
                      {line?.name ?? leg.line}
                    </span>
                    <span className="mt-0.5 block text-sm">
                      {shortName(leg.stations[0].name)}
                      <span className="text-tfl-grey"> to </span>
                      {shortName(leg.stations.at(-1).name)}
                    </span>
                    <span className="text-tfl-grey mt-0.5 block text-xs">
                      {stops} stop{stops === 1 ? '' : 's'} · {duration(leg.seconds)}
                    </span>
                  </span>
                  <Chevron open={open} />
                </button>

                {/* Unmounted when closed rather than hidden with a class. */}
                {open && (
                  <LegStations
                    id={listId}
                    label={line?.name ?? leg.line}
                    stations={leg.stations}
                    stepFree={stepFree}
                  />
                )}
              </div>
            </li>
          )
        })}
      </ol>

      <Disruption route={route} lines={lines} />

      {/* The far end of the journey. Last station of the last leg, or null when
          there are no legs at all - Oxford Circus to Oxford Circus is a valid
          answer with an empty leg list. */}
      <NearbyPlaces destination={route.legs.at(-1)?.stations.at(-1) ?? null} />
    </div>
  )
}

/**
 * Every station on one leg, in order.
 *
 * Scrolls inside itself rather than growing the panel. Google Maps scrolls the
 * whole sheet because the sheet is the whole screen; this is one card in the corner
 * of a map, and a nineteen station list that scrolls the panel pushes the legs
 * below it off the bottom, which defeats the only reason to have an accordion.
 */
function LegStations({ id, label, stations, stepFree }) {
  return (
    <ol
      id={id}
      aria-label={`Stops on the ${label} leg`}
      className="border-tfl-line mt-1.5 max-h-64 overflow-y-auto border-l pl-3"
    >
      {stations.map((station, index) => {
        const end = index === 0 || index === stations.length - 1

        return (
          // Index as the key, as with the legs above: the list is replaced wholesale by
          // the next answer and is never reordered.
          <li key={index} className="flex items-center gap-2 py-1 text-sm">
            <Stop end={end} stepFree={stepFree.has(station.id)} />
            <span className={end ? 'font-medium' : 'text-tfl-grey'}>
              {shortName(station.name)}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

/**
 * One stop. The two ends of a leg are drawn heavier than the stations between them,
 * because the ends are where you do something - the same distinction the map makes
 * with `major` on its route station layer.
 */
function Stop({ end, stepFree }) {
  const size = end ? 9 : 7

  // Three weights, and the last one that applies wins: a step-free ring has to read at
  // a glance, and the end of a leg is drawn heavier than a station passed through.
  let width = 1.5
  if (end) width = 2
  if (stepFree) width = 2.5

  return (
    <span
      className="inline-block shrink-0 rounded-full bg-white"
      style={{
        width: size,
        height: size,
        border: `${width}px solid ${stepFree ? STEP_FREE : INK}`,
      }}
      aria-hidden="true"
    />
  )
}

/** The disclosure arrow, pointing along when closed and down when open. */
function Chevron({ open }) {
  return (
    <svg
      viewBox="0 0 10 10"
      width="10"
      height="10"
      aria-hidden="true"
      className={`text-tfl-grey mt-1.5 shrink-0 ${open ? 'rotate-90' : ''}`}
    >
      <path d="M3 1l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

/** Why the journey may look strange. Nothing at all when nothing is disrupted. */
function Disruption({ route, lines }) {
  const byCode = new Map((lines ?? []).map((line) => [line.code, line]))
  const name = (code) => byCode.get(code)?.name ?? code

  const shut = route.avoided_for_disruption ?? []
  const partial = route.partly_closed ?? []
  if (shut.length === 0 && partial.length === 0) return null

  return (
    <div className="mt-4 space-y-2">
      {shut.length > 0 && (
        <p className="border-tfl-amber bg-tfl-amber/10 border-l-4 px-3 py-2 text-xs">
          Avoiding {shut.map(name).join(', ')} - no trains running.
        </p>
      )}
      {partial.length > 0 && (
        <p className="border-tfl-amber bg-tfl-amber/10 border-l-4 px-3 py-2 text-xs">
          {partial.map(name).join(', ')} {partial.length === 1 ? 'is' : 'are'} part
          closed. This route avoids the closed section.
        </p>
      )}
    </div>
  )
}
