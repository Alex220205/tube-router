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
 *
 *     Phase 8b adds POST and a WebSocket. The timeout and abort handling was
 *     GET-only and is now shared by both verbs rather than copied, because
 *     two copies of a timeout is two places for one of them to be forgotten.
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
 * Call a JSON endpoint.
 *
 * @param {string} method HTTP verb, used in the URL and in error messages -
 *   "POST /route failed" says more than "request failed".
 * @param {string} path Path beginning with a slash, e.g. "/health".
 * @param {object} [options]
 * @param {object} [options.body] Sent as JSON. Omitted entirely for GET,
 *   rather than sent as an empty object.
 * @param {AbortSignal} [options.signal] Cancels the request if the caller
 *   loses interest - a search superseded by more typing, for example.
 * @returns {Promise<object>} The parsed response body.
 * @throws {Error} If the request times out, fails, or returns a non-2xx status.
 */
async function request(method, path, { body, signal } = {}) {
  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      // Two reasons to give up: the server never answered, or the user has
      // moved past this request and its answer is already stale. `any`
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
      throw new Error(`${method} ${path} timed out after ${TIMEOUT_MS}ms`, { cause })
    }
    throw cause
  }

  if (!response.ok) {
    // The status matters to the caller - a 404 and a 503 mean different
    // things - so it goes in the message rather than being flattened into a
    // generic failure.
    throw new Error(`${method} ${path} failed: ${response.status}`)
  }

  return response.json()
}

/**
 * Fetch service health.
 *
 * @returns {Promise<{status: string, database: string, version: string}>}
 */
export function fetchHealth() {
  return request('GET', '/health')
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
  return request('GET', `/stations?${params}`, { signal })
}

/**
 * Fetch every line, with its colour.
 *
 * @returns {Promise<Array<{id: number, code: string, name: string,
 *   colour: string, mode: string}>>}
 */
export function fetchLines() {
  return request('GET', '/lines')
}

/**
 * The whole tube network: every station, segment and line.
 *
 * Sent whole rather than paginated because a map cannot draw a partial
 * network - pages would be individually useless. A few hundred KB, fetched
 * once per page load.
 *
 * @returns {Promise<{stations: Array, segments: Array, lines: Array}>}
 *   Segments carry station and line *ids*, not coordinates: Oxford Circus is
 *   on three lines and in a dozen segments, and nesting it each time would
 *   repeat it for no gain. src/lib/network-geojson.js does the join.
 */
export function fetchNetwork() {
  return request('GET', '/network')
}

/**
 * Plan a journey.
 *
 * @param {{origin: string, destination: string, objective: string}} query
 *   NaPTAN ids, and one of "fastest", "fewest_changes", "step_free".
 * @param {AbortSignal} [signal] Cancels an answer the user has moved past.
 * @returns {Promise<object>} A RouteResponse. Note that `found: false` comes
 *   back as a 200 with a reason, not as an error - "those two stations are
 *   not connected" is a successful answer to a well-formed question, and the
 *   backend documents that choice at schemas/route.py.
 */
export function planRoute(query, signal) {
  return request('POST', '/route', { body: query, signal })
}

/**
 * What is near a station.
 *
 * @param {string} naptanId TfL's station id, e.g. 940GZZLUHR5.
 * @param {string} kind One of the categories the backend allows. It keeps
 *   the authoritative list and answers 400 for anything else - a client is
 *   not a place to enforce what reaches a paid API.
 * @param {AbortSignal} [signal]
 * @returns {Promise<{available: boolean, places: Array}>} `available` is
 *   false when the server has no Google key or could not reach Google. The
 *   empty list then means "we did not look", not "there is nothing there",
 *   and the page renders nothing at all rather than an error.
 */
export function fetchPlaces(naptanId, kind, signal) {
  return request('GET', `/places/${encodeURIComponent(naptanId)}?kind=${kind}`, {
    signal,
  })
}

/**
 * Where to find a photograph of a station's exit.
 *
 * Builds a string and fetches nothing: it is an `<img src>`, so the browser
 * does the request. Pointed at our own API rather than at Google, because
 * the key stays on the server - a signed Google URL in the page is a key in
 * the page.
 *
 * @param {string} naptanId
 * @returns {string}
 */
export function streetViewUrl(naptanId) {
  return `${BASE_URL}/places/${encodeURIComponent(naptanId)}/streetview`
}

/**
 * Subscribe to live line status.
 *
 * The socket sends the current picture on connect, before any change - so
 * there is no companion call to GET /status here. Fetching as well would be
 * two requests racing to set the same state, which is harmless until the day
 * it is not.
 *
 * @param {(status: object) => void} onStatus Called with a StatusResponse,
 *   first on connect and then whenever TfL's answer changes.
 * @returns {WebSocket} Close it to unsubscribe.
 */
export function openStatusSocket(onStatus) {
  // http -> ws and https -> wss in one substitution, so a deployment behind
  // TLS does not open an insecure socket that the browser then blocks.
  const socket = new WebSocket(`${BASE_URL.replace(/^http/, 'ws')}/ws/status`)

  socket.addEventListener('message', (event) => {
    onStatus(JSON.parse(event.data))
  })

  return socket
}
