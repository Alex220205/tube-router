/**
 * TfL's 21 severity levels, grouped into the six things they mean to someone
 * planning a journey.
 *
 * WHY THIS EXISTS
 *     The panel showed every disrupted line the same colour, so "Minor
 *     Delays" and "Planned Closure" looked identical at a glance and the one
 *     that changes your journey was indistinguishable from the one that does
 *     not.
 *
 *     It is here rather than inside the component for the reason
 *     CODE_STYLE.md section 11 gives: this is a function of its input and
 *     nothing else, and logic buried in a component is logic that cannot be
 *     tested. The component renders; this decides.
 *
 * NO 2021 EQUIVALENT
 *     The old project stored status as a sentence and printed it. There was
 *     no severity number, so there was nothing to band and nothing that could
 *     have changed a route.
 *
 * WHAT'S NEW
 *     The bands are the backend's sets, not a second opinion. `NOT_RUNNING`
 *     and `PARTIAL` in backend/app/services/status.py decide whether the
 *     router drops a line or only the closed stretch of it, and CLOSED and
 *     PART_CLOSED below are the same numbers.
 *
 *     That is the point of the colour rather than a nicety: black means the
 *     router refused the line, red means it refused part of it, and anything
 *     warmer means it used the line normally. A panel whose colours disagreed
 *     with the router would explain a journey that had not happened.
 *
 *     The colours are chosen to be readable as text rather than to match
 *     TfL's poster palette, because the wording itself is what gets coloured.
 *     See BANDS below.
 */

// Straight from TfL's /Line/Meta/Severity, read rather than remembered. The
// first version of the backend's equivalent was written from the values that
// had been seen in the wild and missed two of them entirely.
//
// Severity is 0-20 and LOWER is worse, which is why none of this can be a
// comparison against a threshold.

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
// ONE COLOUR EACH, and every one of them is chosen to be read as words on
// white rather than to match a poster. That is not the obvious choice and it
// is the right one here, because the colour IS the wording: "Part Closure"
// is printed in its band's colour, and nothing else on the row carries it.
//
// So TfL's own amber and orange cannot be used. Amber on white is about
// 1.8:1 and orange about 3.0:1, against the 4.5:1 ordinary text needs, which
// would make the two most common disruptions the two hardest to read.
// Darkened versions of both are below. Every value is measured on white, not
// eyeballed:
//
//   good    #007a33   4.9:1      part     #dc241f   4.9:1
//   info    #0019a8  13.1:1      closed   #7a0d0a  11.1:1
//   minor   #8a5a00   5.9:1      unknown  #6f777b   4.6:1
//   bad     #b34700   5.5:1
//
// Closed is a deep maroon rather than the near-black it started as. Black
// was defensible as "the line is gone" and unreadable as a code: the line
// name beside it is also near-black, so the one status that matters most
// looked like the one status nobody had coloured.
//
// The progression is deliberate. Green, blue, amber, orange, red, maroon:
// warmer as it gets worse, and darker at the end. Someone who cannot
// separate amber from orange still has `label`, and the panel prints TfL's
// own wording next to it. Colour is never the only thing carrying the
// meaning, which is the rule the step-free ring follows in TubeMap.jsx.
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
 * without telling anyone, and the safe reading of a level we do not know is
 * "the line is running and there is something to read", not "we have lost
 * contact with the service". `unknown` is reserved for having no status at
 * all, which is a different failure and gets a different colour.
 *
 * @param {number | null | undefined} severity TfL's 0-20 level.
 * @returns {{key: string, label: string, colour: string, rank: number}}
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
 * Worst first, so the line that has stopped is above the one running two
 * minutes late. Ties keep the order they arrived in, which is by line code.
 *
 * @param {Array} rows Anything carrying a `severity`.
 * @returns {Array} A new array. The input is not modified.
 */
export function worstFirst(rows) {
  return [...rows].sort((a, b) => band(b.severity).rank - band(a.severity).rank)
}
