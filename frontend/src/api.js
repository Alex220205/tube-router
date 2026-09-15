/**
 * Wrappers around fetch for the Tube Router API.
 *
 * WHY THIS EXISTS
 *     Components should ask for data, not assemble URLs. Keeping the base
 *     URL and the error handling here means there is one place to change
 *     when either does, and components stay about rendering.
 *
 * NO 2021 EQUIVALENT
 *     The old project had no client and no server - the GUI called methods
 *     on objects in the same process. Everything here exists because the
 *     browser and the data are now in different places.
 *
 * WHAT'S NEW
 *     The base URL is read from the environment rather than written into the
 *     source. VITE_API_URL is substituted at build time, which is what keeps
 *     "works on my laptop" out of the bundle.
 */

// Vite replaces import.meta.env.VITE_API_URL at build time. The fallback is
// for `npm test` and `npm run dev` without a .env, not for anything shipped.
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// fetch has no default timeout. A server that accepts the connection and then
// never answers leaves the page waiting indefinitely, showing "Checking…"
// forever with no error and nothing to distinguish it from a slow network -
// the one failure mode that looks identical to success in progress.
const TIMEOUT_MS = 5000

/**
 * GET a JSON endpoint.
 *
 * @param {string} path Path beginning with a slash, e.g. "/health".
 * @param {AbortSignal} [signal] Cancels the request if the caller loses
 *   interest - a search superseded by more typing, for example.
 * @returns {Promise<object>} The parsed response body.
 * @throws {Error} If the request times out, fails, or returns a non-2xx status.
 */
async function getJson(path, signal) {
  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      // Two reasons to give up: the server never answered, or the user has
      // typed past this request and its answer is already stale. `any`
      // combines them so whichever fires first wins.
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(TIMEOUT_MS)])
        : AbortSignal.timeout(TIMEOUT_MS),
    })
  } catch (cause) {
    // A timeout arrives as a DOMException named TimeoutError, whose own
    // message says only that the operation was aborted. Rewriting it here
    // means the page can say which request gave up and after how long.
    if (cause.name === 'TimeoutError') {
      // { cause } keeps the original DOMException reachable. Replacing an
      // error with a friendlier one should not destroy the evidence.
      throw new Error(`GET ${path} timed out after ${TIMEOUT_MS}ms`, { cause })
    }
    throw cause
  }

  if (!response.ok) {
    // The status matters to the caller - a 404 and a 503 mean different
    // things - so it goes in the message rather than being flattened into a
    // generic failure.
    throw new Error(`GET ${path} failed: ${response.status}`)
  }

  return response.json()
}

/**
 * Fetch service health.
 *
 * @returns {Promise<{status: string, database: string, version: string}>}
 */
export function fetchHealth() {
  return getJson('/health')
}

/**
 * Search stations by name.
 *
 * @param {string} query Substring of the station name. Blank returns all.
 * @param {AbortSignal} [signal] Cancels a request the user has typed past.
 * @returns {Promise<Array<{id: number, naptan_id: string, name: string,
 *   lat: number, lon: number}>>}
 */
export function fetchStations(query, signal) {
  const params = new URLSearchParams()
  if (query) params.set('q', query)
  return getJson(`/stations?${params}`, signal)
}

/**
 * Fetch every line, with its colour.
 *
 * @returns {Promise<Array<{id: number, code: string, name: string,
 *   colour: string, mode: string}>>}
 */
export function fetchLines() {
  return getJson('/lines')
}
