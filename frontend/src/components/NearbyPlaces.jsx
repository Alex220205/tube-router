/**
 * What is near where you are going.
 *
 * WHY THIS EXISTS
 *     A journey planner that stops at the station has answered a narrower
 *     question than the one people actually have. This is the far end of the
 *     journey: you have arrived, what is here.
 *
 * WHAT THE 2021 VERSION DID
 *     Where:  database[works].py, lines 239 and 276
 *     How:    Called Google Places with the API key written into the URL as
 *             a literal, synchronously, from the Tkinter event loop, and put
 *             the result straight into a label.
 *     Wrong:  The key was in the source and is therefore in every commit
 *             that file ever appeared in. There was no timeout, so a slow
 *             answer from Google froze the entire window with nothing on
 *             screen to say why. And it ran whether or not anybody wanted it.
 *
 * WHAT CHANGED AND WHY
 *     The key never reaches the browser. This asks our own API, which holds
 *     the credential, looks the station's coordinates up in Postgres and
 *     caches the answer - so the browser cannot even name a place to search
 *     near, only a station id.
 *
 *     Nothing is requested until the section is opened. Google bills per
 *     call, and a panel that fetches on mount spends money on every route
 *     anyone plans, including the ones nobody scrolls down to.
 *
 * WHAT'S NEW
 *     `available: false` renders nothing at all. Not an error, not "none
 *     found" - nothing. A missing key or an unreachable Google is not a
 *     fault the reader can act on, and the route above is unaffected either
 *     way, so the honest response is silence.
 *
 *     That is the opposite of how LineStatus treats an unknown state, and
 *     the two are reconcilable: a missing line status can send someone to a
 *     platform with no trains, and a missing restaurant list cannot mislead
 *     anyone about anything.
 */

import { useState } from 'react'
import { streetViewUrl } from '../api'
import { usePlaces } from '../hooks/usePlaces'
import { shortName } from '../lib/station-name'

// One array, the way OBJECTIVES works in ObjectiveToggle.jsx, so a sixth
// category is a data change rather than a code change.
//
// The backend keeps its own copy and rejects anything else with a 400. The
// duplication is deliberate: a client is not a place to enforce what gets
// sent to a paid API.
const KINDS = [
  { value: 'restaurant', label: 'Food' },
  { value: 'cafe', label: 'Coffee' },
  { value: 'bar', label: 'Pubs' },
  { value: 'museum', label: 'Museums' },
  { value: 'tourist_attraction', label: 'To see' },
]

/**
 * @param {object} props
 * @param {{id: string, name: string} | null} props.destination The last
 *   station of the last leg, or null when there is no journey to speak of.
 */
export default function NearbyPlaces({ destination }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState(KINDS[0].value)

  // The one hook here that costs money, so `open` gates it rather than
  // merely hiding what it returned.
  const { places, available, loading, error } = usePlaces(
    destination?.id ?? null,
    kind,
    open,
  )

  // No legs means no destination. Oxford Circus to Oxford Circus is a valid
  // answer with an empty leg list, and it is in docs/TEST_JOURNEYS.md as a
  // case that must not throw.
  if (!destination) return null

  // The server could not look. Say nothing rather than explaining a
  // credential problem to somebody who wanted a sandwich.
  if (open && !loading && !available) return null

  const listId = 'nearby-places'

  return (
    <div className="border-tfl-line mt-4 border-t pt-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={listId}
        className="hover:bg-tfl-paper -mx-1 flex w-full items-center gap-2 px-1 py-0.5 text-left"
      >
        <span className="text-tfl-grey min-w-0 flex-1 text-xs font-bold tracking-wider uppercase">
          Near {shortName(destination.name)}
        </span>
        <Chevron open={open} />
      </button>

      {open && (
        <div id={listId} className="mt-2">
          {/* A radio group rather than buttons, for the same reason
              ObjectiveToggle is one: these are five values of one setting,
              and a screen reader should say so. */}
          <div className="flex flex-wrap gap-1">
            {KINDS.map((option) => (
              <label
                key={option.value}
                className={`cursor-pointer border px-2 py-1 text-xs ${
                  kind === option.value
                    ? 'border-tfl-blue bg-tfl-blue font-medium text-white'
                    : 'border-tfl-line hover:border-tfl-grey'
                }`}
              >
                <input
                  type="radio"
                  name="place-kind"
                  value={option.value}
                  checked={kind === option.value}
                  onChange={() => setKind(option.value)}
                  className="sr-only"
                />
                {option.label}
              </label>
            ))}
          </div>

          {/* Loaded by the browser, from our own API. onError hides it
              rather than leaving a broken image icon: a station Google has
              never photographed is ordinary, and the endpoint answers 404
              for it on purpose. */}
          <img
            src={streetViewUrl(destination.id)}
            alt=""
            className="border-tfl-line mt-2 w-full border object-cover"
            onError={(event) => {
              event.currentTarget.style.display = 'none'
            }}
          />

          {loading && <p className="text-tfl-grey mt-2 text-sm">Looking…</p>}

          {error && (
            <p className="text-tfl-grey mt-2 text-sm">
              Could not load places right now.
            </p>
          )}

          {/* An empty list here is a real answer, unlike the unavailable
              case above: we looked and there was nothing within 500m. */}
          {!loading && !error && places.length === 0 && (
            <p className="text-tfl-grey mt-2 text-sm">
              Nothing listed within a few minutes' walk.
            </p>
          )}

          {places.length > 0 && (
            <ul className="border-tfl-line mt-2 divide-y">
              {places.map((place, index) => (
                // Index as the key, as with the route legs: the list is
                // replaced wholesale by the next answer and never reordered.
                <li key={index} className="py-1.5">
                  <p className="text-sm font-medium">{place.name}</p>
                  {place.address && (
                    <p className="text-tfl-grey text-xs">{place.address}</p>
                  )}
                  {place.rating && (
                    <p className="text-tfl-grey text-xs">
                      {place.rating.toFixed(1)}
                      {/* The count is not decoration. A 5.0 from two people
                          and a 4.3 from nine hundred are different claims,
                          and only one of them is worth crossing London for. */}
                      {place.ratings ? ` from ${place.ratings} ratings` : ''}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}

          <p className="text-tfl-grey mt-2 text-[11px]">
            Nearest first, within 500m. From Google.
          </p>
        </div>
      )}
    </div>
  )
}

/** The disclosure arrow, pointing along when closed and down when open. */
function Chevron({ open }) {
  return (
    <svg
      viewBox="0 0 10 10"
      width="10"
      height="10"
      aria-hidden="true"
      className={`text-tfl-grey shrink-0 ${open ? 'rotate-90' : ''}`}
    >
      <path d="M3 1l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}
