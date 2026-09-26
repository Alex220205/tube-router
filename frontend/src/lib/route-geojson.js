/** Turns a planned route into GeoJSON the map can draw over the network. */

import { UNKNOWN_LINE_COLOUR } from './network-geojson'
import { shortName } from './station-name'

/** A collection with nothing in it, so a source can be cleared in place. */
const empty = () => ({ type: 'FeatureCollection', features: [] })

/**
 * Build the route sources from a /route response and the network.
 *
 * @param {object | null} route A RouteResponse. A route that was not found is
 *   handled here rather than by the caller, so a no-route answer clears the
 *   map by the same path that draws one.
 * @param {object | null} network The /network payload the map is drawing.
 * @returns {{line: object, stations: object}} LineStrings, one per leg, each
 *   carrying the colour of the line it runs on; and Points for every station
 *   the journey passes through, so the map can pick them out of the 272 it is
 *   already drawing. Interchanges are marked, since those are the stations a
 *   traveller has to do something at.
 */
export function toRouteGeoJson(route, network) {
  if (!route?.found || !route.legs?.length) {
    return { line: empty(), stations: empty() }
  }

  // Keyed by NaPTAN id, because that is what the legs speak. The map's own station
  // source carries the same id, so this is a lookup rather than a second request.
  const stationByNaptan = new Map(
    (network?.stations ?? []).map((station) => [station.naptan_id, station]),
  )
  const lineByCode = new Map((network?.lines ?? []).map((line) => [line.code, line]))

  const features = []

  // Keyed by NaPTAN id so a station appearing on two legs - which is exactly what an
  // interchange is - becomes one point rather than two stacked on top of each other.
  const stops = new Map()

  for (const leg of route.legs) {
    const coordinates = []

    for (const stop of leg.stations) {
      const station = stationByNaptan.get(stop.id)

      if (!station) continue

      // [lon, lat]. Reverse of speech, same as network-geojson.js - and the failure is
      // identical: a route rendered perfectly, in the Indian Ocean.
      coordinates.push([station.lon, station.lat])

      // Where the traveller has to do something: the two ends of the journey, and
      // anywhere a leg begins or ends in the middle of it, which is a change.
      // Everything else is a station the train goes through.
      const isEnd = stop === leg.stations[0] || stop === leg.stations.at(-1)

      // The two ends of the whole journey, as opposed to the ends of a leg. Every
      // change is the end of one leg and the start of the next, so `isEnd` is true for
      // both; this is true only for where you got on and where you get off.
      const isTerminus =
        stop === route.legs[0].stations[0] || stop === route.legs.at(-1).stations.at(-1)

      stops.set(stop.id, {
        type: 'Feature',
        properties: {
          name: shortName(stop.name),
          // Drawn larger and labelled. An interchange or an end of the journey is a
          // decision point; the twenty stations between them are not. Sticky across
          // legs - a change is the end of one leg and the start of the next, and it
          // must stay major when the second one sets it.
          major: stops.get(stop.id)?.properties.major || isEnd,
          // Carried through from the network, because the route's own stations are
          // drawn on top of it. Without this the blue ring disappears from every
          // station on a journey the moment one is planned - which is the one time
          // somebody is looking to see whether they can get out at the other end.
          stepFree: Boolean(station.step_free),
          // Where you get on and where you get off, as distinct from a change. Used
          // only to decide which label is placed first when two of them cannot both
          // fit: losing the name of a station you pass through is a nuisance, losing
          // the name of your destination is the map failing at its job.
          terminus: stops.get(stop.id)?.properties.terminus || isTerminus,
        },
        geometry: { type: 'Point', coordinates: [station.lon, station.lat] },
      })
    }

    // A LineString needs two points. One is not a line and MapLibre will not say so.
    if (coordinates.length < 2) continue

    features.push({
      type: 'Feature',
      properties: {
        colour: lineByCode.get(leg.line)?.colour ?? UNKNOWN_LINE_COLOUR,
      },
      geometry: { type: 'LineString', coordinates },
    })
  }

  return {
    line: { type: 'FeatureCollection', features },
    stations: { type: 'FeatureCollection', features: [...stops.values()] },
  }
}
