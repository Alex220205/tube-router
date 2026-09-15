/**
 * Turns the /network payload into GeoJSON the map can draw.
 *
 * WHY THIS EXISTS
 *     /network hands back three flat lists joined by integer ids - segments
 *     carry an origin_station_id and a line_id, not coordinates and not a
 *     colour. Doing that join inside the map component would bury the one
 *     piece of real logic in this phase inside the one thing that cannot be
 *     tested, because MapLibre needs WebGL and jsdom has none.
 *
 *     Pure function, no React, no fetch, no map. Payload in, two
 *     FeatureCollections out.
 *
 * NO 2021 EQUIVALENT
 *     The old project drew nothing. It had no coordinates at all - the table
 *     meant to hold them was created with malformed SQL and stayed empty for
 *     five years, so there was never a map to put anything on.
 *
 * WHAT'S NEW
 *     Coordinates, and therefore the chance to put them in backwards. GeoJSON
 *     wants [lon, lat], which is the reverse of how anyone says it out loud,
 *     and this project has already been caught by that inversion twice on the
 *     database side. Wrong here and every station renders perfectly, in the
 *     Indian Ocean.
 */

// What an unknown line is drawn in. The seed guarantees a colour on every
// line, so this is for a payload that has outrun the frontend rather than a
// missing value - visibly wrong beats invisibly absent.
const UNKNOWN_LINE_COLOUR = '#7f7f7f'

/**
 * Build the map's two sources from a /network response.
 *
 * @param {{stations: Array, segments: Array, lines: Array}} network
 * @returns {{segments: object, stations: object}} Two GeoJSON
 *   FeatureCollections: LineStrings for the track, Points for the stations.
 */
export function toGeoJson(network) {
  const stations = network?.stations ?? []
  const segments = network?.segments ?? []
  const lines = network?.lines ?? []

  const stationById = new Map(stations.map((station) => [station.id, station]))
  const lineById = new Map(lines.map((line) => [line.id, line]))

  // Segments are directional: every link appears once each way. Drawn as-is
  // that is 754 features for 377 lines, each stroked twice - which shows the
  // moment anything has opacity, and is twice the data for no benefit.
  const drawn = new Set()
  const features = []

  for (const segment of segments) {
    const from = stationById.get(segment.origin_station_id)
    const to = stationById.get(segment.destination_station_id)

    // A segment naming a station the payload does not contain would otherwise
    // draw a line to undefined, which MapLibre renders at null island off the
    // coast of Africa rather than refusing. Skipped, because one bad row must
    // not cost the other 753.
    if (!from || !to) continue

    // Unordered, so A-B and B-A collapse to one entry. Keyed with the line
    // too: Shepherd's Bush Market to Wood Lane is genuinely two links, on the
    // Circle and on the Hammersmith & City, and they are different lines on
    // the map.
    const key = [segment.line_id, ...[from.id, to.id].sort((a, b) => a - b)].join(':')
    if (drawn.has(key)) continue
    drawn.add(key)

    features.push({
      type: 'Feature',
      properties: {
        colour: lineById.get(segment.line_id)?.colour ?? UNKNOWN_LINE_COLOUR,
      },
      geometry: {
        type: 'LineString',
        // [lon, lat]. See the header - the order is the reverse of speech.
        coordinates: [
          [from.lon, from.lat],
          [to.lon, to.lat],
        ],
      },
    })
  }

  return {
    segments: { type: 'FeatureCollection', features },
    stations: {
      type: 'FeatureCollection',
      features: stations.map((station) => ({
        type: 'Feature',
        properties: { name: station.name, naptanId: station.naptan_id },
        geometry: { type: 'Point', coordinates: [station.lon, station.lat] },
      })),
    },
  }
}
