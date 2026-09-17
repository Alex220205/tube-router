/**
 * What TfL says is wrong with the network right now, and which colour is
 * which line.
 *
 * WHY THIS EXISTS
 *     A route that avoids the Piccadilly line looks like a bug unless the
 *     page says the Piccadilly line is shut. This is the other half of
 *     RoutePanel's `avoided_for_disruption`.
 *
 * WHAT THE 2021 VERSION DID
 *     Printed whatever sentence was in the database into a Tkinter label, for
 *     every line, with no timestamp. Status and the router never met: nothing
 *     could ask whether a line was actually running, because the value was
 *     only ever prose.
 *
 * WHAT'S NEW
 *     Three states, not two. docs/PHASE_8B.md has the reasoning; the short
 *     version is that "we do not know" and "everything is fine" are different
 *     answers, and schemas/status.py says so explicitly - `as_of` is null when
 *     the poller has not run or Redis is unreachable, and the instruction
 *     there is to "render that as unknown, not as good".
 *
 *     Collapsed it lists only what is disrupted, because eleven rows saying
 *     Good Service is noise that teaches people not to look. Expanded it
 *     lists all eleven with their colours, which is the only place on the page
 *     that says what colour the Metropolitan is - and someone who has never
 *     used the Underground has no other way to read the map.
 */

import { useState } from 'react'

// TfL's severity for Good Service, on their 0-20 scale. The same constant the
// backend keeps in services/status.py - anything else is worth a row here.
const GOOD_SERVICE = 10

const UNKNOWN_COLOUR = '#7f7f7f'

/**
 * @param {object} props
 * @param {object | null} props.status The latest StatusResponse, or null
 *   before the socket has said anything.
 * @param {Array} props.lines The network's lines, for names and colours. The
 *   status payload carries a line code and nothing else.
 */
export default function LineStatus({ status, lines }) {
  const [expanded, setExpanded] = useState(false)

  const byCode = new Map((lines ?? []).map((line) => [line.code, line]))

  // Null status means nothing has answered yet; a null as_of means the server
  // answered and does not know. Both are "unknown", and neither is "fine".
  const known = Boolean(status?.as_of)
  const reported = known ? status.lines : []
  const disrupted = reported.filter((line) => line.severity !== GOOD_SERVICE)

  // Expanded, every line the network has - not just the ones TfL mentioned -
  // so the legend is complete even when the poller has said nothing.
  const rows = expanded
    ? (lines ?? []).map((line) => ({
        line_code: line.code,
        description: reported.find((s) => s.line_code === line.code)?.description,
      }))
    : disrupted

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <h2 className="text-tfl-grey font-bold tracking-wider uppercase">
          Line status
        </h2>

        {/* Named, not an icon. "All lines" says what you get; a chevron does
            not, and this is the control someone unfamiliar with the network
            most needs to find. */}
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="text-tfl-blue hover:text-tfl-blue-dark shrink-0 font-medium underline underline-offset-2"
        >
          {expanded ? 'Show less' : 'All lines'}
        </button>
      </div>

      {!known && !expanded && <p className="text-tfl-grey">Line status unavailable</p>}

      {known && !expanded && disrupted.length === 0 && (
        <p className="text-tfl-green font-medium">Good service on all lines</p>
      )}

      {!known && expanded && (
        <p className="text-tfl-grey mb-1.5">
          Status unavailable - colours only.
        </p>
      )}

      {rows.length > 0 && (
        <ul className="space-y-1">
          {rows.map((line) => (
            <li key={line.line_code} className="flex items-baseline gap-1.5">
              <span
                className="mt-1 size-2.5 shrink-0"
                style={{
                  backgroundColor: byCode.get(line.line_code)?.colour ?? UNKNOWN_COLOUR,
                }}
                aria-hidden="true"
              />
              <span className="font-medium">
                {byCode.get(line.line_code)?.name ?? line.line_code}
              </span>
              {/* Expanded, a line TfL has not mentioned is running normally.
                  Saying so beats a blank space next to its name. */}
              <span className="text-tfl-grey">
                {line.description ?? (known ? 'Good Service' : '')}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
