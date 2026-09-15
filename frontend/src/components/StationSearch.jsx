/**
 * A search box over the station list, used once per end of a journey.
 *
 * WHY THIS EXISTS
 *     Picking a station is the first thing anyone does here, and it happens
 *     twice. One component, rendered as From and as To, so the two cannot
 *     drift apart in behaviour.
 *
 * NO 2021 EQUIVALENT
 *     The old project's station entry was a Tkinter field reading a list held
 *     in the same process.
 *
 * WHAT'S NEW
 *     It is reusable, and results are clickable.
 *
 *     The id is a prop rather than a constant. Two copies of a hardcoded id
 *     is invalid HTML, and the practical cost is that a label stops pointing
 *     at its own input: screen readers announce the wrong one, clicking the
 *     label focuses the wrong box, and getByLabelText finds two elements.
 *
 *     The list appears only once something has been typed. Opening with all
 *     272 stations pushed the To box and everything under it off the bottom
 *     of the screen, so the second half of the form was unreachable without
 *     scrolling past a list nobody had asked for.
 */

import { useState } from 'react'
import { shortName } from '../lib/station-name'
import { useStations } from '../hooks/useStations'

/**
 * @param {object} props
 * @param {string} props.id Unique DOM id, tying the label to the input.
 * @param {string} props.label What this box is for, e.g. "From".
 * @param {object | null} props.selected The chosen station, or null.
 * @param {(station: object | null) => void} props.onSelect Called with a
 *   station when one is picked, and with null when the user starts editing.
 */
export default function StationSearch({ id, label, selected, onSelect }) {
  const [query, setQuery] = useState('')
  const { stations, loading, error } = useStations(query)

  // Derived, not stored. A second piece of state saying "the list is closed"
  // could disagree with the selection it was meant to reflect, and the two
  // going out of step is the whole class of bug this avoids.
  const chosen = Boolean(selected)

  // Nothing typed means nothing to choose between. The hook still runs, so
  // the results are already there the moment a character appears.
  const searching = query.trim().length > 0

  function handleChange(event) {
    setQuery(event.target.value)

    // Editing drops the selection. The alternative - keep it until something
    // new is picked - leaves the box reading "Oxfo" while the route below is
    // still from Oxford Circus, which is a lie the user has no way to spot.
    if (selected) onSelect(null)
  }

  function choose(station) {
    setQuery(shortName(station.name))
    onSelect(station)
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
        {/* A short bar in TfL blue down the side of the active field. It is
            the same device the signage uses to say "this line, here", and it
            is the one thing distinguishing a filled box from an empty one at
            a glance. */}
        <span
          className={`absolute inset-y-0 left-0 w-1 ${
            chosen ? 'bg-tfl-blue' : 'bg-tfl-line'
          }`}
          aria-hidden="true"
        />
        <input
          id={id}
          type="search"
          value={query}
          onChange={handleChange}
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

      {/* An empty result is a real answer, not an error. Saying so beats
          rendering an empty box the user has to interpret. */}
      {searching && !loading && !error && !chosen && stations.length === 0 && (
        <p className="text-tfl-grey mt-2 text-sm">No stations match “{query}”.</p>
      )}

      {/* Hidden once something is chosen: a list still offering alternatives
          under a filled-in box reads as though the choice did not take. */}
      {searching && !chosen && stations.length > 0 && (
        <ul className="border-tfl-line divide-tfl-line mt-1.5 max-h-52 divide-y overflow-y-auto border-2 bg-white">
          {stations.map((station) => (
            <li key={station.id}>
              {/* A button, not a clickable li. Tab reaches it, Enter and
                  Space activate it, and screen readers announce it as
                  something that does something - none of which is true of a
                  list item with an onClick. */}
              <button
                type="button"
                onClick={() => choose(station)}
                className="hover:bg-tfl-blue focus:bg-tfl-blue w-full px-4 py-2.5 text-left text-sm hover:text-white focus:text-white focus:outline-none"
              >
                {shortName(station.name)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
