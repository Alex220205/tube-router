/**
 * A search box over the station list.
 *
 * WHY THIS EXISTS
 *     The first thing in this project a person can actually use. It proves
 *     the whole chain end to end: React asks the API, the API queries
 *     Postgres, and 272 real stations come back.
 *
 * NO 2021 EQUIVALENT
 *     The old project's station entry was a Tkinter field reading a list held
 *     in the same process.
 *
 * WHAT'S NEW
 *     Phase 8 replaces this with the same search feeding a map and an
 *     origin/destination pair. The querying is already in useStations, so
 *     that change is to this file and not to the data path.
 */

import { useState } from 'react'
import { useStations } from '../hooks/useStations'

export default function StationSearch() {
  const [query, setQuery] = useState('')
  const { stations, loading, error } = useStations(query)

  return (
    <section className="mt-6">
      <label htmlFor="station-search" className="block text-sm font-medium">
        Find a station
      </label>

      <input
        id="station-search"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="oxford, bank, king's cross…"
        className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
        autoComplete="off"
      />

      {error && (
        <p className="mt-2 text-sm text-red-600">Could not reach the API: {error}</p>
      )}

      {loading && !error && <p className="mt-2 text-sm text-gray-500">Searching…</p>}

      {/* An empty result is a real answer, not an error. Saying so beats
          rendering an empty box the user has to interpret. */}
      {!loading && !error && stations.length === 0 && (
        <p className="mt-2 text-sm text-gray-500">
          No stations match “{query}”.
        </p>
      )}

      {stations.length > 0 && (
        <ul className="mt-2 divide-y divide-gray-100 rounded-md border border-gray-200">
          {stations.map((station) => (
            <li key={station.id} className="px-3 py-2">
              <span>{station.name}</span>{' '}
              <span className="text-xs text-gray-400">{station.naptan_id}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
