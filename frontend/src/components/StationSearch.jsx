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
 *
 *     And it is usable without the mouse: down from the box into the list,
 *     up and down through it, up again to come back out. Typing a station
 *     name and then reaching for the trackpad to click the one result it
 *     found is the sort of thing that makes a form feel unfinished.
 */

import { useRef, useState } from 'react'
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

  // Held to move focus between the box and the list, which is the one thing
  // in here that cannot be expressed as rendered output.
  const inputRef = useRef(null)
  const listRef = useRef(null)

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

  // Moving through the list is moving focus, not tracking a highlighted index
  // in state. The results are real buttons, so the browser's focus IS that
  // state and nothing can disagree with it: Enter and Space already activate
  // the focused one, it is already styled as focused, and it is scrolled into
  // view inside the list's own overflow without anything here asking.
  //
  // The alternative - aria-activedescendant over a listbox - would mean the
  // options stop being buttons, and then every behaviour above has to be
  // rebuilt by hand.
  function focusOption(index) {
    const options = listRef.current?.querySelectorAll('button') ?? []
    if (options.length === 0) return

    // Clamped rather than wrapped. Holding down arrow should stop at the end
    // of the list, not cycle past it with no way to tell you have.
    options[Math.max(0, Math.min(index, options.length - 1))].focus()
  }

  function handleInputKeys(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusOption(0)
      return
    }

    // Enter with exactly one result: there is nothing left to choose between,
    // so typing enough to be unambiguous is the choice. With more than one it
    // deliberately does nothing. Picking the first of fifty on a keypress the
    // user meant as "done typing" is a decision made on their behalf, and the
    // arrow key that makes it theirs is one key away.
    if (event.key === 'Enter' && searching && !chosen && stations.length === 1) {
      event.preventDefault()
      choose(stations[0])
    }
  }

  function handleOptionKeys(event, index) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusOption(index + 1)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()

      // Up from the top returns to the box rather than wrapping to the
      // bottom, so the way out of the list is the way you came into it.
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

      {/* An empty result is a real answer, not an error. Saying so beats
          rendering an empty box the user has to interpret. */}
      {searching && !loading && !error && !chosen && stations.length === 0 && (
        <p className="text-tfl-grey mt-2 text-sm">No stations match “{query}”.</p>
      )}

      {/* Hidden once something is chosen: a list still offering alternatives
          under a filled-in box reads as though the choice did not take. */}
      {searching && !chosen && stations.length > 0 && (
        <ul
          ref={listRef}
          className="border-tfl-line divide-tfl-line mt-1.5 max-h-52 divide-y overflow-y-auto border-2 bg-white"
        >
          {stations.map((station, index) => (
            <li key={station.id}>
              {/* A button, not a clickable li. Tab and the arrow keys reach
                  it, Enter and Space activate it, and screen readers announce
                  it as something that does something - none of which is true
                  of a list item with an onClick. */}
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
      )}
    </section>
  )
}
