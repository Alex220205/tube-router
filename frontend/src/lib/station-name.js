/**
 * Station names as a person would say them.
 *
 * WHY THIS EXISTS
 *     TfL's commonName is "Oxford Circus Underground Station" and that is
 *     what the database stores, verbatim, because docs/DECISIONS.md decided
 *     in Phase 1 that names are never corrected on the way in - a correction
 *     map is a second source of truth that goes stale silently.
 *
 *     The suffix is right for storage and wrong for a list of twenty of them,
 *     where it is the same eighteen characters on every row and the part that
 *     differs gets pushed out of view. So the trimming happens here, on the
 *     way to the screen, and the stored value is untouched.
 *
 *     One function rather than a `.replace()` at each call site, because
 *     three of them drifting apart is how a station ends up spelled two ways
 *     on one page.
 *
 * NO 2021 EQUIVALENT
 *     The old project's station names came from a hand-typed table and were
 *     already short, inconsistently. docs/AUDIT.md lists the cost: names that
 *     did not match TfL's, so nothing could be reconciled against the real
 *     network.
 */

// Only these two, and only at the end. "Underground" appears mid-name in
// nothing on the network, but anchoring the match means it could never matter.
const SUFFIXES = [' Underground Station', ' DLR Station', ' Rail Station']

/**
 * @param {string} name TfL's commonName, as stored.
 * @returns {string} The name without its station-type suffix. Unchanged if it
 *   has none, which is true of a few - "Waterloo" is just "Waterloo".
 */
export function shortName(name) {
  if (!name) return ''

  for (const suffix of SUFFIXES) {
    if (name.endsWith(suffix)) return name.slice(0, -suffix.length)
  }

  return name
}
