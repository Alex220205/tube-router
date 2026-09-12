/**
 * Wrappers around fetch for the Tube Router API.
 *
 * WHY THIS EXISTS
 *     Components should ask for data, not assemble URLs. Keeping the base
 *     URL and the error handling here means there is one place to change
 *     when either does, and components stay about rendering.
 *
 * NO 2021 EQUIVALENT
 *     The old project had no client and no server — the GUI called methods
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

/**
 * GET a JSON endpoint.
 *
 * @param {string} path Path beginning with a slash, e.g. "/health".
 * @returns {Promise<object>} The parsed response body.
 * @throws {Error} If the request fails or the status is not 2xx.
 */
async function getJson(path) {
  const response = await fetch(`${BASE_URL}${path}`)

  if (!response.ok) {
    // The status matters to the caller — a 404 and a 503 mean different
    // things — so it goes in the message rather than being flattened into a
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
