/** A search box over the station list, used once per end of a journey. */

import { useRef, useState } from 'react'
import { shortName } from '../lib/station-name'
import { useGeocode } from '../hooks/useGeocode'
import { useStations } from '../hooks/useStations'

export default function StationSearch({ id, label, selected, onSelect }) {
  const [query, setQuery] = useState('')
  const { stations, loading, error } = useStations(query)

  // Only ever consulted on an explicit press. See hooks/useGeocode.js.
  const places = useGeocode()

  // Derived, not stored. A second piece of state saying "the list is closed" could
  // disagree with the selection it was meant to reflect, and the two going out of step
  // is the whole class of bug this avoids.
  const chosen = Boolean(selected)

  // Held to move focus between the box and the list, which is the one thing in here
  // that cannot be expressed as rendered output.
  const inputRef = useRef(null)
  const listRef = useRef(null)

  // Nothing typed means nothing to choose between. The hook still runs, so the results
  // are already there the moment a character appears.
  const searching = query.trim().length > 0

  function handleChange(event) {
    setQuery(event.target.value)

    // Editing drops the selection. The alternative - keep it until something new is
    // picked - leaves the box reading "Oxfo" while the route below is still from Oxford
    // Circus, which is a lie the user has no way to spot.
    if (selected) onSelect(null)

    // And it drops any place results, which were an answer about text that is no longer
    // in the box.
    places.reset()
  }

  function choose(station) {
    setQuery(shortName(station.name))
    onSelect(station)
    places.reset()
  }

  // A station the geocoder offered. It carries naptan_id and name and no coordinates,
  // which is all the route request needs - the same shape the station search hands
  // over, so onSelect cannot tell where it came from.
  function chooseNearby(station) {
    setQuery(shortName(station.name))
    onSelect({ naptan_id: station.naptan_id, name: station.name })
    places.reset()
  }

  // Moving through the list is moving focus, not tracking a highlighted index in state.
  function focusOption(index) {
    const options = listRef.current?.querySelectorAll('button') ?? []
    if (options.length === 0) return

    // Clamped rather than wrapped. Holding down arrow should stop at the end of the
    // list, not cycle past it with no way to tell you have.
    options[Math.max(0, Math.min(index, options.length - 1))].focus()
  }

  function handleInputKeys(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusOption(0)
      return
    }

    // Enter with exactly one result: there is nothing left to choose between, so typing
    // enough to be unambiguous is the choice. With more than one it deliberately does
    // nothing.
    if (event.key !== 'Enter' || !searching || chosen) return

    if (stations.length === 1) {
      event.preventDefault()
      choose(stations[0])
      return
    }

    // No stations at all means the place search is the only thing being offered, so
    // Enter takes it - the same rule as picking the only result, applied to the only
    // remaining option.
    if (stations.length === 0 && !loading && !error && !places.query) {
      event.preventDefault()
      places.search(query)
    }
  }

  function handleOptionKeys(event, index) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusOption(index + 1)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()

      // Up from the top returns to the box rather than wrapping to the bottom, so the
      // way out of the list is the way you came into it.
      if (index === 0) inputRef.current?.focus()
      else focusOption(index - 1)
    } else if (event.key === 'Escape') {
      inputRef.current?.focus()
    }
  }

  return (
    <section className="mt-4">
      <label
        htmlFor={id}
        className="text-tfl-grey block text-xs font-bold tracking-wider uppercase"
      >
        {label}
      </label>

      <div className="relative mt-1.5">
        {/* A short bar in TfL blue down the side of the active field. It is the
            same device the signage uses to say "this line, here", and it is the one
            thing distinguishing a filled box from an empty one at a glance. */}
        <span
          className={`absolute inset-y-0 left-0 w-1 ${
            chosen ? 'bg-tfl-blue' : 'bg-tfl-line'
          }`}
          aria-hidden="true"
        />
        <input
          id={id}
          ref={inputRef}
          type="search"
          value={query}
          onChange={handleChange}
          onKeyDown={handleInputKeys}
          placeholder="oxford, bank, king's cross…"
          className="border-tfl-line focus:border-tfl-blue focus:ring-tfl-blue/20 w-full border-2 bg-white py-2.5 pr-3 pl-4 text-sm focus:ring-4 focus:outline-none"
          autoComplete="off"
        />
      </div>

      {error && (
        <p className="text-tfl-red mt-2 text-sm font-medium">
          Could not reach the API: {error}
        </p>
      )}

      {searching && loading && !error && (
        <p className="text-tfl-grey mt-2 text-sm">Searching…</p>
      )}

      {/* An empty result is a real answer, not an error. Saying so beats rendering
          an empty box the user has to interpret - and it is also the moment to
          offer the thing that does work, because somebody typing text that is not a
          station name has usually typed a place. */}
      {searching &&
        !loading &&
        !error &&
        !chosen &&
        !places.query &&
        stations.length === 0 && (
          <div className="mt-2">
            <p className="text-tfl-grey text-sm">No stations match “{query}”.</p>
            <button
              type="button"
              onClick={() => places.search(query)}
              className="border-tfl-blue text-tfl-blue hover:bg-tfl-blue mt-1.5 w-full border-2 px-3 py-2 text-sm font-medium hover:text-white"
            >
              Search for a place called “{query}”
            </button>
          </div>
        )}

      {/* Hidden once something is chosen: a list still offering alternatives under
          a filled-in box reads as though the choice did not take. And hidden once a
          place search has been asked for, because that was a deliberate "not
          these". */}
      {searching && !chosen && !places.query && stations.length > 0 && (
        <>
          <ul
            ref={listRef}
            className="border-tfl-line divide-tfl-line mt-1.5 max-h-52 divide-y overflow-y-auto border-2 bg-white"
          >
            {stations.map((station, index) => (
              <li key={station.id}>
                {/* A button, not a clickable li. Tab and the arrow keys reach it,
                    Enter and Space activate it, and screen readers announce it as
                    something that does something - none of which is true of a list
                    item with an onClick. */}
                <button
                  type="button"
                  onClick={() => choose(station)}
                  onKeyDown={(event) => handleOptionKeys(event, index)}
                  className="hover:bg-tfl-blue focus:bg-tfl-blue w-full px-4 py-2.5 text-left text-sm hover:text-white focus:text-white focus:outline-none"
                >
                  {shortName(station.name)}
                </button>
              </li>
            ))}
          </ul>

          {/* Quieter than the offer above - a link, not a button - because here the
              station list is usually the right answer and this is the way out when
              it is not. Outside the list on purpose, so the arrow keys still move
              only between stations. */}
          <button
            type="button"
            onClick={() => places.search(query)}
            className="text-tfl-blue hover:text-tfl-blue-dark mt-1.5 text-xs underline underline-offset-2"
          >
            Not a station? Search for a place called “{query}”
          </button>
        </>
      )}

      {/* Whatever the place search found, whether it was offered because no station
          matched or chosen instead of the ones that did. */}
      {searching && !chosen && places.query && (
        <div className="mt-2">
          {places.loading && <p className="text-tfl-grey text-sm">Looking it up…</p>}

          {/* Could not look, as opposed to looked and found nothing. The reader
              cannot act on a missing credential, so it is said once and plainly. */}
          {!places.loading && !places.available && (
            <p className="text-tfl-grey text-sm">
              Place search is not available right now.
            </p>
          )}

          {places.error && (
            <p className="text-tfl-red text-sm font-medium">
              Could not search for places: {places.error}
            </p>
          )}

          {/* Wording that is true of both cases it covers: nothing matched, and
              something matched too far from the Underground to be a journey.
              Brighton is a real place and not a destination this service has an
              opinion about. */}
          {!places.loading &&
            places.available &&
            !places.error &&
            places.results.length === 0 && (
              <p className="text-tfl-grey text-sm">
                Nothing near the Underground matched “{places.query}”.
              </p>
            )}

          {places.results.length > 0 && (
            <ul className="space-y-2">
              {places.results.map((match, index) => (
                // Index as the key: matches have no id and the list is replaced
                // wholesale by the next search.
                <li key={index} className="border-tfl-line border-2 p-2">
                  {/* Google's own formatted address, because it is the only thing
                      distinguishing one "High St" from the next six and it is not
                      ours to reword. */}
                  <p className="text-xs font-medium">{match.address}</p>
                  <ul className="mt-1.5 space-y-1">
                    {match.stations.map((station) => (
                      <li key={station.naptan_id}>
                        <button
                          type="button"
                          onClick={() => chooseNearby(station)}
                          className="hover:bg-tfl-blue focus:bg-tfl-blue flex w-full items-baseline justify-between gap-2 px-2 py-1.5 text-left text-sm hover:text-white focus:text-white focus:outline-none"
                        >
                          <span>{shortName(station.name)}</span>
                          <span className="shrink-0 text-xs opacity-70">
                            {station.metres < 1000
                              ? `${station.metres} m`
                              : `${(station.metres / 1000).toFixed(1)} km`}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
