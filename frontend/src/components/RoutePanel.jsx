/**
 * The journey, written out.
 *
 * WHY THIS EXISTS
 *     A line on a map does not tell you where to change, and where to change
 *     is most of what a traveller needs. The map shows the shape; this says
 *     what to do.
 *
 * WHAT THE 2021 VERSION DID
 *     Where:  GUI.Find_shortest_path
 *     How:    A flat list of station names in a Tkinter label, with no record
 *             of which line each hop was on - the search did not keep it. It
 *             then compared the total against the literal 9999999 to decide
 *             whether to show anything at all.
 *     Wrong:  A journey you cannot follow. "Change at Holborn" was not
 *             expressible, and a caller that forgot the 9999999 check
 *             rendered it as a duration: two and a half months.
 *
 * WHAT'S NEW
 *     Legs, so changes are visible, each stamped with its line's real colour
 *     from the database. `found` instead of a magic number. And
 *     `avoided_for_disruption`, which is Phase 7 arriving on screen: a
 *     journey that silently takes a strange path is indistinguishable from a
 *     bug, so the page says why.
 *
 *     Each leg opens. "Metropolitan, Liverpool Street to Rayners Lane, 14
 *     stops" is the shape of a journey and not the journey: it does not say
 *     whether you go through Baker Street, which is the question someone
 *     standing on a platform actually asks. The stations were already in the
 *     response and were being thrown away - every leg carries its full
 *     ordered list, and this read the first and the last of it.
 *
 *     One leg open at a time, because opening another should close the one
 *     before it.
 */

import { useState } from 'react'
import { INK, STEP_FREE } from './MapKey'
import NearbyPlaces from './NearbyPlaces'
import { shortName } from '../lib/station-name'

// One sentence per reason the engine can give. Written for a traveller, not
// copied from the wire: "disconnected" is a correct description of a graph
// and tells a person nothing.
const REASONS = {
  unknown_origin: 'We do not have that starting station.',
  unknown_destination: 'We do not have that destination.',
  disconnected: 'No route between these two stations.',
}

// The same case, with the one piece of advice that actually helps. Step-free
// routing fails far more often than the network is genuinely disconnected -
// only 101 of 272 stations have an accessible line at all - and "try another
// objective" is a remedy, where "no route" is a dead end.
const NO_STEP_FREE = 'No step-free route between these two stations.'

/**
 * Minutes, or hours and minutes. Seconds are below the precision of anything
 * this estimate is built from and printing them would imply otherwise.
 *
 * @param {number} seconds
 * @returns {string}
 */
function duration(seconds) {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min`

  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} hr` : `${hours} hr ${rest} min`
}

/**
 * @param {object} props
 * @param {object | null} props.route A RouteResponse, or null if there is
 *   nothing to show yet.
 * @param {boolean} props.loading
 * @param {string | null} props.error A transport failure - not the same thing
 *   as a route that does not exist, which arrives as a successful answer.
 * @param {string} props.objective Which objective was asked for, so a failed
 *   step-free search can say so.
 * @param {Array} props.lines The network's lines, for names and colours. The
 *   legs carry a line code and nothing else.
 * @param {Array} props.stations The network's stations, for which of them are
 *   step-free. The legs carry NaPTAN ids and names, and nothing else.
 */
export default function RoutePanel({
  route,
  loading,
  error,
  objective,
  lines,
  stations,
}) {
  // Which leg is open, stored with the route it belongs to.
  //
  // A bare index would survive into the next answer and open leg 2 of a
  // journey that has nothing to do with the one the user was reading. Holding
  // the route alongside it means a new answer simply stops matching, which is
  // the same shape as useRoute holding its answer with the question it
  // answers - see docs/DECISIONS.md, Phase 8b.
  //
  // One index rather than a set of them. "Opening another closes the first"
  // is then true by construction instead of by remembering to close the
  // previous one on every path that opens a new one.
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

  // found: false is a successful answer to a well-formed question, and gets
  // an explanation rather than an error. Rendering nothing here would leave
  // the user unable to tell it from a request that failed - the same
  // reasoning that made an empty station search a 200 in Phase 3.
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

  // NaPTAN ids of the step-free stations. Rebuilt each render rather than
  // memoised: it is 272 rows once per answer, and a useMemo here would cost
  // more to read than it saves.
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

      {/* Stated only when true. "Not step-free" on a journey nobody asked to
          be step-free is a warning about a thing that was never promised. */}
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
            // Index as the key: legs have no id, and a journey's legs are
            // only ever replaced wholesale by a new answer, never reordered.
            <li key={index} className="flex gap-3">
              {/* The line's own colour, straight from the database. This is
                  the one place the page is unmistakably about the Tube
                  rather than about transport in general. */}
              <span
                className="mt-0.5 w-1.5 shrink-0"
                style={{ backgroundColor: line?.colour ?? '#6f777b' }}
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                {/* The summary IS the control. A separate "show stops" link
                    would put two targets on one leg, and the thing people
                    aim at is the leg. */}
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

                {/* Unmounted when closed rather than hidden with a class. The
                    planner is hidden with CSS because its search boxes hold
                    what you typed; this list holds nothing, so there is
                    nothing to preserve and 48 rows of a long journey need not
                    sit in the document while nobody is reading them. */}
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

      {/* The far end of the journey. Last station of the last leg, or null
          when there are no legs at all - Oxford Circus to Oxford Circus is a
          valid answer with an empty leg list. */}
      <NearbyPlaces destination={route.legs.at(-1)?.stations.at(-1) ?? null} />
    </div>
  )
}

/**
 * Every station on one leg, in order.
 *
 * Scrolls inside itself rather than growing the panel. Google Maps scrolls
 * the whole sheet because the sheet is the whole screen; this is one card in
 * the corner of a map, and a nineteen station list that scrolls the panel
 * pushes the legs below it off the bottom, which defeats the only reason to
 * have an accordion.
 *
 * The interchange appears twice on a journey with a change, once as the last
 * station of one leg and once as the first of the next. That is deliberate:
 * you are at Liverpool Street on the Central line and at Liverpool Street on
 * the Metropolitan, and those are two different platforms with a walk
 * between them. It is also what the map draws.
 *
 * @param {{id: string, label: string, stations: Array, stepFree: Set<string>}} props
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
          // Index as the key, as with the legs above: the list is replaced
          // wholesale by the next answer and is never reordered.
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
 * One stop. The two ends of a leg are drawn heavier than the stations
 * between them, because the ends are where you do something - the same
 * distinction the map makes with `major` on its route station layer.
 *
 * A step-free station gets the blue ring, which is the mark MapKey describes
 * and TubeMap draws. The colours come from MapKey so the three cannot drift.
 */
function Stop({ end, stepFree }) {
  const size = end ? 9 : 7
  const width = stepFree ? 2.5 : end ? 2 : 1.5

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

/**
 * Why the journey may look strange. Nothing at all when nothing is disrupted.
 *
 * Two kinds, and conflating them makes the page contradict itself. A line
 * that is wholly shut is not available; a line with one stretch closed is
 * still running, and this route may well be using it. Heathrow Terminal 5 to
 * Epping rides the Piccadilly out to Rayners Lane while the middle of the
 * Piccadilly is closed, and a banner reading "avoiding Piccadilly, no trains
 * running" above a first leg on the Piccadilly is simply wrong.
 *
 * @param {{route: object, lines: Array}} props
 */
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
