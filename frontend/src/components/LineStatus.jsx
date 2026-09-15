/**
 * What TfL says is wrong with the network right now.
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
 *     Only disrupted lines are listed. Eleven rows all saying Good Service is
 *     noise that teaches people not to look, which is the opposite of what a
 *     status panel is for.
 */

// TfL's severity for Good Service, on their 0-20 scale. The same constant the
// backend keeps in services/status.py - anything else is worth a row here.
const GOOD_SERVICE = 10

/**
 * @param {object} props
 * @param {object | null} props.status The latest StatusResponse, or null
 *   before the socket has said anything.
 * @param {Array} props.lines The network's lines, for names and colours. The
 *   status payload carries a line code and nothing else.
 */
export default function LineStatus({ status, lines }) {
  // Null status means nothing has answered yet; a null as_of means the server
  // answered and does not know. Both are "unknown", and neither is "fine".
  if (!status?.as_of) {
    return <p className="text-gray-500">Line status unavailable</p>
  }

  const disrupted = status.lines.filter((line) => line.severity !== GOOD_SERVICE)

  if (disrupted.length === 0) {
    return <p className="text-green-700">Good service on all lines</p>
  }

  const byCode = new Map((lines ?? []).map((line) => [line.code, line]))

  return (
    <ul className="space-y-1">
      {disrupted.map((line) => (
        <li key={line.line_code} className="flex items-baseline gap-1.5">
          <span
            className="size-2 shrink-0 rounded-full"
            style={{ backgroundColor: byCode.get(line.line_code)?.colour ?? '#7f7f7f' }}
            aria-hidden="true"
          />
          <span className="font-medium">
            {byCode.get(line.line_code)?.name ?? line.line_code}
          </span>
          <span className="text-gray-500">{line.description}</span>
        </li>
      ))}
    </ul>
  )
}
