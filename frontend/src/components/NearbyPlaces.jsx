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
 *     `available: false` is reported as one quiet line rather than as an
 *     error. A missing key or an unreachable Google is not a fault the
 *     reader can act on, and the route above is unaffected either way.
 *
 *     The first version unmounted the whole section on `available: false`,
 *     on the grounds that silence was the honest answer. It was, and it was
 *     also unusable: you can only learn the answer by opening the section,
 *     so clicking it made the thing you clicked vanish. From the outside
 *     that is indistinguishable from a dead button, which is exactly how it
 *     was reported.
 *
 *     Nothing that responds to a click may disappear as a result of it. The
 *     silence is still there - it is just one sentence long instead of
 *     zero, and it stays where your eye already is.
 */

import { useEffect, useRef, useState } from 'react'
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
  { value: 'food', label: 'Food' },
  { value: 'coffee', label: 'Coffee' },
  { value: 'pubs', label: 'Pubs' },
  { value: 'museums', label: 'Museums' },
  { value: 'see', label: 'To see' },
]

/**
 * A distance a person can act on. Metres up to a kilometre, then one decimal
 * place, because "1400 m" is arithmetic and "1.4 km" is a decision.
 *
 * @param {number | null | undefined} metres
 * @returns {string}
 */
function walk(metres) {
  if (metres === null || metres === undefined) return ''
  return metres < 1000 ? `${metres} m` : `${(metres / 1000).toFixed(1)} km`
}

/**
 * @param {object} props
 * @param {{id: string, name: string} | null} props.destination The last
 *   station of the last leg, or null when there is no journey to speak of.
 */
export default function NearbyPlaces({ destination }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState(KINDS[0].value)
  const container = useRef(null)

  // The one hook here that costs money, so `open` gates it rather than
  // merely hiding what it returned.
  const { places, available, loading, error } = usePlaces(
    destination?.id ?? null,
    kind,
    open,
  )

  // This section is the last thing in a panel that scrolls, so opening it
  // adds content below the fold and the click appears to do nothing at all.
  //
  // scrollIntoView CANNOT be used for this, which the first version learned
  // the expensive way. It scrolls every scrollable ancestor, and `overflow:
  // hidden` does not make an element unscrollable - it only stops the *user*
  // scrolling it. So opening this section scrolled the page shell as well as
  // the panel, pushed the whole card 108px off the top of a laptop screen,
  // and left no way to bring it back: the shell ignores the wheel, because
  // it is overflow-hidden.
  //
  // So the panel's own scroller is found and adjusted by hand. Nothing else
  // moves, by construction rather than by asking politely with `nearest`.
  useEffect(() => {
    if (!open) return

    const element = container.current
    const scroller = element?.closest('.overflow-y-auto')
    if (!element || !scroller) return

    const box = element.getBoundingClientRect()
    const frame = scroller.getBoundingClientRect()

    // Only when it is actually out of view, and only by as much as it takes.
    if (box.bottom > frame.bottom) {
      scroller.scrollTop += box.bottom - frame.bottom
    } else if (box.top < frame.top) {
      scroller.scrollTop -= frame.top - box.top
    }
  }, [open])

  // No legs means no destination. Oxford Circus to Oxford Circus is a valid
  // answer with an empty leg list, and it is in docs/TEST_JOURNEYS.md as a
  // case that must not throw.
  if (!destination) return null

  const listId = 'nearby-places'
  const unavailable = open && !loading && !available

  return (
    <div ref={container} className="border-tfl-line mt-4 border-t pt-3">
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
          {/* The station, above the categories rather than below them.
              It sat under the chips at first and never changed when they
              did, which read as a bug: the same photograph over Food,
              Coffee and Pubs looks like a picture that failed to update.
              It is a picture of the station exit and always was, so it
              belongs above the thing that filters the list, with a caption
              that says which it is.

              Loaded by the browser from our own API, so the key stays on the
              server. onError hides it rather than leaving a broken image
              icon: a station Google has never driven past is ordinary, and
              the endpoint answers 404 for it on purpose. */}
          {!unavailable && (
            <figure className="mb-2">
              <img
                src={streetViewUrl(destination.id)}
                alt={`Street view outside ${shortName(destination.name)} station`}
                className="border-tfl-line w-full border object-cover"
                onError={(event) => {
                  event.currentTarget.closest('figure').style.display = 'none'
                }}
              />
              <figcaption className="text-tfl-grey mt-1 text-[11px]">
                Outside {shortName(destination.name)} station
              </figcaption>
            </figure>
          )}

          {/* A radio group rather than buttons, for the same reason
              ObjectiveToggle is one: these are five values of one setting,
              and a screen reader should say so.

              Hidden when we could not look at all. Offering five categories
              that each change nothing is the same defect as ISSUES.md #23 in
              a smaller form: a control that responds to being used by doing
              nothing visible. */}
          <div className={`flex flex-wrap gap-1 ${unavailable ? 'hidden' : ''}`}>
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

          {loading && <p className="text-tfl-grey mt-2 text-sm">Looking…</p>}

          {/* "Could not look", not "could not find". The server says this
              when it has no Google key or could not reach Google, and
              neither is something the reader can do anything about - so it
              is stated once, plainly, and not dressed as an error. */}
          {unavailable && (
            <p className="text-tfl-grey mt-2 text-sm">
              Places are not available right now.
            </p>
          )}

          {error && (
            <p className="text-tfl-grey mt-2 text-sm">
              Could not load places right now.
            </p>
          )}

          {/* An empty list here is a different statement from the one above:
              we looked, and there was nothing within 500m. */}
          {!loading && !error && available && places.length === 0 && (
            <p className="text-tfl-grey mt-2 text-sm">Nothing listed within 1.5km.</p>
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
                  <p className="text-tfl-grey text-xs">
                    {/* How far, first, because it is the thing that decides
                        whether the rest matters. The search reaches 1.5km so
                        that outer stations return anything at all, which
                        means a result can be a fifteen minute walk and the
                        row has to say so. */}
                    {walk(place.metres)}
                    {place.rating && place.metres ? ' · ' : ''}
                    {place.rating ? place.rating.toFixed(1) : ''}
                    {/* The count is not decoration. A 5.0 from two people
                        and a 4.3 from nine hundred are different claims, and
                        only one of them is worth crossing London for. */}
                    {place.rating && place.ratings
                      ? ` from ${place.ratings} ratings`
                      : ''}
                  </p>
                </li>
              ))}
            </ul>
          )}

          {!unavailable && places.length > 0 && (
            <p className="text-tfl-grey mt-2 text-[11px]">
              Nearest first, within 1.5km. Distances are straight line. From Google.
            </p>
          )}
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
