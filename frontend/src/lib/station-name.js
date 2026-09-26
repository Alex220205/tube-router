/** Station names as a person would say them. */

// Only these two, and only at the end. "Underground" appears mid-name in nothing on the
// network, but anchoring the match means it could never matter.
const SUFFIXES = [' Underground Station', ' DLR Station', ' Rail Station']

/**
 * @param {string} name TfL's commonName, as stored. @returns {string} The name
 * without its station-type suffix. Unchanged if it has none, which is true of a few
 * - "Waterloo" is just "Waterloo".
 */
export function shortName(name) {
  if (!name) return ''

  for (const suffix of SUFFIXES) {
    if (name.endsWith(suffix)) return name.slice(0, -suffix.length)
  }

  return name
}
