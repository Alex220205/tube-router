/**
 * What TfL says is wrong with the network right now, why, and which colour is
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
 *
 *     The wording itself is coloured, from lib/severity.js. The bands are
 *     the backend's own sets, so the colour says what the router did:
 *     maroon is a line it refused outright, red is a line it used around the
 *     closed stretch, and anything warmer is a line it used normally.
 *
 *     Because the wording is what carries the colour, the palette is chosen
 *     for contrast on white rather than to match TfL's posters - their amber
 *     is 1.8:1 and unreadable at this size. MapKey lists all seven bands and
 *     what each one means, since a colour nobody has been told about is
 *     decoration.
 *
 *     And a disrupted row opens. TfL's `reason` is the only text anywhere
 *     that says why, when and for how long - "no service between Earls Court
 *     and Ealing Broadway, Saturday 19 and Sunday 20 September, use Mildmay
 *     Line services" - and it was being fetched, stored, pushed over the
 *     WebSocket and then dropped on the floor.
 */

import { useState } from 'react'
import { band, worstFirst } from '../lib/severity'
import { shortName } from '../lib/station-name'

// TfL's severity for Good Service, on their 0-20 scale. The same constant the
// backend keeps in services/status.py - anything else is worth a row here.
const GOOD_SERVICE = 10

const UNKNOWN_COLOUR = '#7f7f7f'

/**
 * When the poller last managed to ask TfL. Local time and to the minute:
 * seconds imply a precision that a 30 second poll does not have.
 *
 * @param {string} isoTimestamp
 * @returns {string}
 */
function checkedAt(isoTimestamp) {
  const when = new Date(isoTimestamp)
  if (Number.isNaN(when.getTime())) return ''
  return when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * @param {object} props
 * @param {object | null} props.status The latest StatusResponse, or null
 *   before the socket has said anything.
 * @param {Array} props.lines The network's lines, for names and colours. The
 *   status payload carries a line code and nothing else.
 * @param {Array} props.stations The network's stations, to turn the NaPTAN
 *   ids in `affected_stops` into names someone can read.
 */
export default function LineStatus({ status, lines, stations }) {
  const [expanded, setExpanded] = useState(false)

  // Which line's detail is open, held as one code rather than a set, so
  // opening another closes the first by construction. Same reasoning as the
  // route panel's legs, recorded in docs/DECISIONS.md.
  const [openLine, setOpenLine] = useState(null)

  const byCode = new Map((lines ?? []).map((line) => [line.code, line]))
  const nameByNaptan = new Map(
    (stations ?? []).map((station) => [station.naptan_id, station.name]),
  )

  // Null status means nothing has answered yet; a null as_of means the server
  // answered and does not know. Both are "unknown", and neither is "fine".
  const known = Boolean(status?.as_of)
  const reported = known ? status.lines : []
  const disrupted = reported.filter((line) => line.severity !== GOOD_SERVICE)

  // Expanded, every line the network has - not just the ones TfL mentioned -
  // so the legend is complete even when the poller has said nothing. Ordered
  // by line code there, because a legend you read a colour out of should not
  // rearrange itself every thirty seconds.
  const rows = expanded
    ? (lines ?? []).map((line) => {
        const live = reported.find((s) => s.line_code === line.code)
        return {
          line_code: line.code,
          severity: known ? (live?.severity ?? GOOD_SERVICE) : null,
          description: live?.description,
          reason: live?.reason,
          affected_stops: live?.affected_stops ?? [],
        }
      })
    : worstFirst(disrupted)

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
        <p className="text-tfl-grey mb-1.5">Status unavailable - colours only.</p>
      )}

      {rows.length > 0 && (
        <ul className="space-y-1">
          {rows.map((line) => (
            <Row
              key={line.line_code}
              line={line}
              network={byCode.get(line.line_code)}
              nameByNaptan={nameByNaptan}
              asOf={status?.as_of}
              open={openLine === line.line_code}
              onToggle={() =>
                setOpenLine(openLine === line.line_code ? null : line.line_code)
              }
            />
          ))}
        </ul>
      )}

      {/* Said once at the bottom rather than on every row. A timestamp is
          reassurance that the panel is live, and eleven copies of it is
          eleven copies of one fact. */}
      {known && (
        <p className="text-tfl-grey mt-1.5 text-[11px]">
          Checked {checkedAt(status.as_of)}
        </p>
      )}
    </div>
  )
}

/**
 * One line. A coloured edge for the severity band, the line's own colour for
 * the legend, and its detail underneath when there is any and it is open.
 */
function Row({ line, network, nameByNaptan, asOf, open, onToggle }) {
  const severity = band(line.severity)

  // Only a row with something to say is a control. A line running normally
  // has no reason text and no affected stops, and dressing it as a button
  // that opens onto nothing is worse than leaving it as a row.
  const stops = line.affected_stops ?? []
  const detailed = Boolean(line.reason) || stops.length > 0
  const detailId = `line-status-${line.line_code}`

  const label = (
    <>
      <span
        className="size-2.5 shrink-0"
        style={{ backgroundColor: network?.colour ?? UNKNOWN_COLOUR }}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 text-left">
        <span className="font-medium">{network?.name ?? line.line_code}</span>{' '}
        {/* The status in its band's colour. Expanded, a line TfL has not
            mentioned is running normally, and saying so beats a blank space
            next to its name. */}
        <span className="font-medium" style={{ color: severity.colour }}>
          {line.description ?? (line.severity === null ? '' : 'Good Service')}
        </span>
      </span>
    </>
  )

  return (
    <li>
      {detailed ? (
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={detailId}
          className="hover:bg-tfl-paper -mx-1 flex w-full items-baseline gap-1.5 px-1 py-0.5"
        >
          {label}
          <Chevron open={open} />
        </button>
      ) : (
        <span className="flex items-baseline gap-1.5 py-0.5">{label}</span>
      )}

      {detailed && open && (
        <div id={detailId} className="text-tfl-grey mt-0.5 mb-1.5 space-y-1.5">
          {/* TfL's own wording, not a summary of it. It is the only text
              anywhere that says why, when and what to do instead, and
              rewriting it would mean guessing at the bits it leaves out. */}
          {line.reason && <p className="text-tfl-ink">{line.reason}</p>}

          {stops.length > 0 && (
            <p>
              <span className="font-medium">Affected stations ({stops.length}):</span>{' '}
              {stops
                .map((id) => shortName(nameByNaptan.get(id) ?? id))
                .sort()
                .join(', ')}
            </p>
          )}

          {asOf && <p className="text-[11px]">TfL, as of {checkedAt(asOf)}</p>}
        </div>
      )}
    </li>
  )
}

/** The disclosure arrow, pointing along when closed and down when open. */
function Chevron({ open }) {
  return (
    <svg
      viewBox="0 0 10 10"
      width="9"
      height="9"
      aria-hidden="true"
      className={`text-tfl-grey shrink-0 self-center ${open ? 'rotate-90' : ''}`}
    >
      <path d="M3 1l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}
