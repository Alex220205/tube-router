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
 *     Legs, so changes are visible. `found` instead of a magic number. And
 *     `avoided_for_disruption`, which is Phase 7 arriving on screen: a
 *     journey that silently takes a strange path is indistinguishable from a
 *     bug, so the page says why.
 */

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
    return <p className="mt-4 text-sm text-red-600">Could not plan a route: {error}</p>
  }

  if (loading) {
    return <p className="mt-4 text-sm text-gray-500">Planning…</p>
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
      <div className="mt-4 border-t border-gray-100 pt-3">
        <p className="text-sm">{message}</p>
        <AvoidedLines codes={route.avoided_for_disruption} lines={lines} />
      </div>
    )
  }

  const byCode = new Map((lines ?? []).map((line) => [line.code, line]))

  return (
    <div className="mt-4 border-t border-gray-100 pt-3">
      <p className="text-lg font-semibold">
        {duration(route.total_seconds)}
        <span className="ml-2 text-sm font-normal text-gray-500">
          {route.changes === 0
            ? 'direct'
            : `${route.changes} change${route.changes === 1 ? '' : 's'}`}
        </span>
      </p>

      {/* Stated only when true. "Not step-free" on a journey nobody asked to
          be step-free is a warning about a thing that was never promised. */}
      {route.step_free && (
        <p className="mt-0.5 text-xs text-green-700">Step-free throughout</p>
      )}

      <ol className="mt-3 space-y-3">
        {route.legs.map((leg, index) => {
          const line = byCode.get(leg.line)
          const stops = leg.stations.length - 1

          return (
            // Index as the key: legs have no id, and a journey's legs are
            // only ever replaced wholesale by a new answer, never reordered.
            <li key={index} className="flex gap-2">
              <span
                className="mt-1 w-1 shrink-0 rounded"
                style={{ backgroundColor: line?.colour ?? '#7f7f7f' }}
                aria-hidden="true"
              />
              <div className="min-w-0">
                <p className="text-sm font-medium">{line?.name ?? leg.line}</p>
                <p className="text-sm text-gray-600">
                  {leg.stations[0].name} to {leg.stations.at(-1).name}
                </p>
                <p className="mt-0.5 text-xs text-gray-400">
                  {stops} stop{stops === 1 ? '' : 's'} · {duration(leg.seconds)}
                </p>
              </div>
            </li>
          )
        })}
      </ol>

      <AvoidedLines codes={route.avoided_for_disruption} lines={lines} />
    </div>
  )
}

/**
 * Why the journey may look strange. Nothing at all when nothing was avoided.
 *
 * @param {{codes: Array<string>, lines: Array}} props
 */
function AvoidedLines({ codes, lines }) {
  if (!codes || codes.length === 0) return null

  const byCode = new Map((lines ?? []).map((line) => [line.code, line]))
  const names = codes.map((code) => byCode.get(code)?.name ?? code)

  return (
    <p className="mt-3 rounded bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
      Avoiding {names.join(', ')} - no trains running.
    </p>
  )
}
