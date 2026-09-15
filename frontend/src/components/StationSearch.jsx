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
 *     It is now reusable, and results are clickable. Until this phase it was
 *     a demonstration that the API answered - it listed stations and nothing
 *     could be done with them.
 *
 *     The id is a prop rather than a constant. Two copies of a hardcoded id
 *     is invalid HTML, and the practical cost is that a label stops pointing
 *     at its own input: screen readers announce the wrong one, clicking the
 *     label focuses the wrong box, and getByLabelText finds two elements.
 */

import { useState } from 'react'
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

  function handleChange(event) {
    setQuery(event.target.value)

    // Editing drops the selection. The alternative - keep it until something
    // new is picked - leaves the box reading "Oxfo" while the route below is
    // still from Oxford Circus, which is a lie the user has no way to spot.
    if (selected) onSelect(null)
  }

  function choose(station) {
    setQuery(station.name)
    onSelect(station)
  }

  return (
    <section className="mt-4">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>

      <input
        id={id}
        type="search"
        value={query}
        onChange={handleChange}
        placeholder="oxford, bank, king's cross…"
        className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
        autoComplete="off"
      />

      {error && (
        <p className="mt-2 text-sm text-red-600">Could not reach the API: {error}</p>
      )}

      {loading && !error && !chosen && (
        <p className="mt-2 text-sm text-gray-500">Searching…</p>
      )}

      {/* An empty result is a real answer, not an error. Saying so beats
          rendering an empty box the user has to interpret. */}
      {!loading && !error && !chosen && stations.length === 0 && (
        <p className="mt-2 text-sm text-gray-500">No stations match “{query}”.</p>
      )}

      {/* Hidden once something is chosen: a list still offering alternatives
          under a filled-in box reads as though the choice did not take. */}
      {!chosen && stations.length > 0 && (
        <ul className="mt-2 max-h-48 divide-y divide-gray-100 overflow-y-auto rounded-md border border-gray-200">
          {stations.map((station) => (
            <li key={station.id}>
              {/* A button, not a clickable li. Tab reaches it, Enter and
                  Space activate it, and screen readers announce it as
                  something that does something - none of which is true of a
                  list item with an onClick. */}
              <button
                type="button"
                onClick={() => choose(station)}
                className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50"
              >
                {station.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
