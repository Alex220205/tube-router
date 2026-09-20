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
 */

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
 */
export default function RoutePanel({ route, loading, error, objective, lines }) {
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
                <p className="text-sm font-bold">{line?.name ?? leg.line}</p>
                <p className="mt-0.5 text-sm">
                  {shortName(leg.stations[0].name)}
                  <span className="text-tfl-grey"> to </span>
                  {shortName(leg.stations.at(-1).name)}
                </p>
                <p className="text-tfl-grey mt-0.5 text-xs">
                  {stops} stop{stops === 1 ? '' : 's'} · {duration(leg.seconds)}
                </p>
              </div>
            </li>
          )
        })}
      </ol>

      <Disruption route={route} lines={lines} />
    </div>
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
