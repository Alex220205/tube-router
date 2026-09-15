/**
 * Turns a planned route into GeoJSON the map can draw over the network.
 *
 * WHY THIS EXISTS
 *     POST /route answers with legs carrying NaPTAN ids and station names and
 *     **no coordinates** - verified against the live endpoint, not assumed.
 *     Drawing a route therefore means joining those ids against the network
 *     already in memory for the map, which is the one piece of real logic in
 *     this phase.
 *
 *     It lives here rather than in TubeMap.jsx for the reason §11 of
 *     docs/CODE_STYLE.md now records: MapLibre needs WebGL, jsdom has none,
 *     and logic buried in an untestable component is untested logic.
 *
 * NO 2021 EQUIVALENT
 *     The old project drew nothing, and its result was a flat list of station
 *     names with no record of which line each hop was on - so even with
 *     coordinates there would have been nothing to colour a leg by.
 *
 * WHAT'S NEW
 *     One feature per leg, not one per journey. A route that changes at
 *     Holborn is Piccadilly then Central, and a single merged LineString
 *     would draw the whole thing in one colour - wrong in the one place a
 *     traveller most needs to see the change.
 */

import { UNKNOWN_LINE_COLOUR } from './network-geojson'

const EMPTY = { type: 'FeatureCollection', features: [] }

/**
 * Build the route source from a /route response and the network.
 *
 * @param {object | null} route A RouteResponse. A route that was not found is
 *   handled here rather than by the caller, so a no-route answer clears the
 *   map by the same path that draws one.
 * @param {object | null} network The /network payload the map is drawing.
 * @returns {object} A FeatureCollection of LineStrings, one per leg, each
 *   carrying the colour of the line it runs on.
 */
export function toRouteGeoJson(route, network) {
  if (!route?.found || !route.legs?.length) return EMPTY

  // Keyed by NaPTAN id, because that is what the legs speak. The map's own
  // station source carries the same id, so this is a lookup rather than a
  // second request.
  const stationByNaptan = new Map(
    (network?.stations ?? []).map((station) => [station.naptan_id, station]),
  )
  const lineByCode = new Map((network?.lines ?? []).map((line) => [line.code, line]))

  const features = []

  for (const leg of route.legs) {
    const coordinates = []

    for (const stop of leg.stations) {
      const station = stationByNaptan.get(stop.id)

      // A stop the network does not contain means the graph was rebuilt
      // between this page loading /network and asking for a route - Phase 7's
      // generation key makes that a real sequence rather than a hypothetical.
      // Skipping draws the leg straight past it, which is slightly wrong;
      // dropping the whole leg would lose part of a journey the panel beside
      // the map still lists, which is worse.
      if (!station) continue

      // [lon, lat]. Reverse of speech, same as network-geojson.js - and the
      // failure is identical: a route rendered perfectly, in the Indian Ocean.
      coordinates.push([station.lon, station.lat])
    }

    // A LineString needs two points. One is not a line and MapLibre will not
    // say so.
    if (coordinates.length < 2) continue

    features.push({
      type: 'Feature',
      // Colour only. A `line` property carrying the code would be the obvious
      // companion and nothing would read it - the layer paints from `colour`
      // and the panel beside the map already has the code. CODE_STYLE.md §10:
      // a field with no reader is a plan, not a field.
      properties: {
        colour: lineByCode.get(leg.line)?.colour ?? UNKNOWN_LINE_COLOUR,
      },
      geometry: { type: 'LineString', coordinates },
    })
  }

  return { type: 'FeatureCollection', features }
}
