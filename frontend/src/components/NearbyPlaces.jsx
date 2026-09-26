/** What is near where you are going. */

import { useEffect, useRef, useState } from 'react'
import { streetViewUrl } from '../api'
import { STEP_FREE } from './MapKey'
import { usePlaces } from '../hooks/usePlaces'
import { shortName } from '../lib/station-name'

/**
 * Where a recommendation should send somebody.
 *
 * Its own site first, because that is where the opening hours and the menu are.
 * Google Maps second, because it is effectively always there, and a row that cannot
 * be followed up is a row that stops halfway.
 */
function linkFor(place) {
  return place.website ?? place.maps_url ?? null
}

// One array, the way OBJECTIVES works in ObjectiveToggle.jsx, so a sixth category is a
// data change rather than a code change.
const KINDS = [
  { value: 'food', label: 'Food' },
  { value: 'coffee', label: 'Coffee' },
  { value: 'pubs', label: 'Pubs' },
  { value: 'museums', label: 'Museums' },
  { value: 'see', label: 'To see' },
]

/**
 * A distance a person can act on. Metres up to a kilometre, then one decimal place,
 * because "1400 m" is arithmetic and "1.4 km" is a decision.
 *
 * @param {number | null | undefined} metres
 * @returns {string}
 */
function walk(metres) {
  if (metres === null || metres === undefined) return ''
  return metres < 1000 ? `${metres} m` : `${(metres / 1000).toFixed(1)} km`
}

export default function NearbyPlaces({ destination }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState(KINDS[0].value)
  const container = useRef(null)

  // The one hook here that costs money, so `open` gates it rather than merely hiding
  // what it returned.
  const { places, available, loading, error } = usePlaces(
    destination?.id ?? null,
    kind,
    open,
  )

  // This section is the last thing in a panel that scrolls, so opening it adds content
  // below the fold and the click appears to do nothing at all.
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
          {/* The station, above the categories rather than below them. It sat under
              the chips at first and never changed when they did, which read as a
              bug: the same photograph over Food, Coffee and Pubs looks like a
              picture that failed to update. */}
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

          {/* A radio group rather than buttons, for the same reason ObjectiveToggle
              is one: these are five values of one setting, and a screen reader
              should say so. */}
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

          {/* "Could not look", not "could not find". The server says this when it
              has no Google key or could not reach Google, and neither is something
              the reader can do anything about - so it is stated once, plainly, and
              not dressed as an error. */}
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

          {/* An empty list here is a different statement from the one above: we
              looked, and there was nothing within 500m. */}
          {!loading && !error && available && places.length === 0 && (
            <p className="text-tfl-grey mt-2 text-sm">Nothing listed within 1.5km.</p>
          )}

          {places.length > 0 && (
            <ul className="border-tfl-line mt-2 divide-y">
              {places.map((place, index) => (
                // Index as the key, as with the route legs: the list is replaced
                // wholesale by the next answer and never reordered.
                <li key={index} className="py-1.5">
                  <p className="flex items-center gap-1.5 text-sm font-medium">
                    {/* The same blue ring the map draws on a step-free station and
                        the key explains, because it is the same claim at the other
                        end of the journey: you can get in. */}
                    {place.wheelchair_entrance && (
                      <span
                        title="Step-free entrance, according to Google"
                        className="inline-block shrink-0 rounded-full bg-white"
                        style={{
                          width: 9,
                          height: 9,
                          border: `2.5px solid ${STEP_FREE}`,
                        }}
                      />
                    )}
                    {/* A link when there is somewhere to go, plain text when there
                        is not, rather than a dead link that looks live. noreferrer
                        as well as noopener: the first stops the opened page
                        reaching back through window.opener, the second stops it
                        being told where its visitor came from. */}
                    {linkFor(place) ? (
                      <a
                        href={linkFor(place)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:text-tfl-blue underline decoration-transparent underline-offset-2 hover:decoration-current"
                      >
                        {place.name}
                      </a>
                    ) : (
                      place.name
                    )}
                  </p>
                  {place.address && (
                    <p className="text-tfl-grey text-xs">{place.address}</p>
                  )}
                  <p className="text-tfl-grey text-xs">
                    {/* How far, first, because it is the thing that decides whether
                        the rest matters. The search reaches 1.5km so that outer
                        stations return anything at all, which means a result can be
                        a fifteen minute walk and the row has to say so. */}
                    {walk(place.metres)}
                    {place.rating && place.metres ? ' · ' : ''}
                    {place.rating ? place.rating.toFixed(1) : ''}
                    {/* The count is not decoration. A 5.0 from two people and a 4.3
                        from nine hundred are different claims, and only one of them
                        is worth crossing London for. */}
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
              Nearest first, within 1.5km. Distances are straight line. Names link out.
              From Google.
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
