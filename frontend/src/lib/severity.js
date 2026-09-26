/**
 * TfL's 21 severity levels, grouped into the six things they mean to someone
 * planning a journey.
 */

// Straight from TfL's /Line/Meta/Severity, read rather than remembered.

/** Part of the line is shut. Mirrors PARTIAL in services/status.py. */
const PART_CLOSED = new Set([
  3, // Part Suspended
  5, // Part Closure
  11, // Part Closed
])

/** The whole line is shut. NOT_RUNNING minus the three above. */
const CLOSED = new Set([
  1, // Closed
  2, // Suspended
  4, // Planned Closure
  16, // Not Running
  20, // Service Closed
])

/** Running, but worse than usual. */
const BAD = new Set([
  6, // Severe Delays
  7, // Reduced Service
  8, // Bus Service
])

/** Running normally. */
const GOOD = new Set([
  10, // Good Service
  18, // No Issues
])

/** Running, with something worth knowing. Everything else lands here. */
const MINOR = 9 // Minor Delays

// The seven bands.
//
// ONE COLOUR EACH, and every one of them is chosen to be read as words on white rather
// than to match a poster. That is not the obvious choice and it is the right one here,
// because the colour IS the wording: "Part Closure" is printed in its band's colour,
// and nothing else on the row carries it.
export const BANDS = {
  good: { label: 'Good service', colour: '#007a33', rank: 0 },
  info: { label: 'Running, with a notice', colour: '#0019a8', rank: 1 },
  minor: { label: 'Minor delays', colour: '#8a5a00', rank: 2 },
  bad: { label: 'Badly delayed', colour: '#b34700', rank: 3 },
  part: { label: 'Partly closed', colour: '#dc241f', rank: 4 },
  closed: { label: 'Closed', colour: '#7a0d0a', rank: 5 },
  unknown: { label: 'Unknown', colour: '#6f777b', rank: 6 },
}

/** The bands in the order a reader should meet them: fine, then worse. */
export const BAND_ORDER = ['good', 'info', 'minor', 'bad', 'part', 'closed']

/**
 * Which band a severity falls in.
 *
 * Unrecognised numbers are `info` rather than `unknown`: TfL can add a level
 * without telling anyone, and the safe reading of a level we do not know is "the
 * line is running and there is something to read", not "we have lost contact with
 * the service".
 */
export function band(severity) {
  if (severity === null || severity === undefined) {
    return { key: 'unknown', ...BANDS.unknown }
  }
  if (GOOD.has(severity)) return { key: 'good', ...BANDS.good }
  if (severity === MINOR) return { key: 'minor', ...BANDS.minor }
  if (BAD.has(severity)) return { key: 'bad', ...BANDS.bad }
  if (PART_CLOSED.has(severity)) return { key: 'part', ...BANDS.part }
  if (CLOSED.has(severity)) return { key: 'closed', ...BANDS.closed }
  return { key: 'info', ...BANDS.info }
}

/**
 * Worst first, so the line that has stopped is above the one running two minutes
 * late. Ties keep the order they arrived in, which is by line code.
 */
export function worstFirst(rows) {
  return [...rows].sort((a, b) => band(b.severity).rank - band(a.severity).rank)
}
