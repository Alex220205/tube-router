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

import { shortName } from './station-name'

// What an unknown line is drawn in. The seed guarantees a colour on every
// line, so this is for a payload that has outrun the frontend rather than a
// missing value - visibly wrong beats invisibly absent.
export const UNKNOWN_LINE_COLOUR = '#7f7f7f'

/**
 * One physical stretch of track, whichever way round it is described.
 *
 * @param {number} a Station id.
 * @param {number} b The other station id.
 * @returns {string} The same key for a-b and b-a.
 */
function linkKey(a, b) {
  return a < b ? `${a}:${b}` : `${b}:${a}`
}

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

  // Which lines run over each physical link. **57 of 314 links carry more
  // than one** - 18% of the network - and until this existed they were drawn
  // as identical LineStrings stacked on each other, so only whichever painted
  // last was visible.
  //
  // The Piccadilly and the Metropolitan share the track from Rayners Lane to
  // Uxbridge; the Circle, Hammersmith & City and Metropolitan share six links
  // through Baker Street and Farringdon. On the real map those run side by
  // side. Here one of them simply vanished, and nothing was wrong with the
  // data - both segments were in the payload, both became features, and one
  // was painted exactly over the other.
  const linesOnLink = new Map()

  for (const segment of segments) {
    const from = stationById.get(segment.origin_station_id)
    const to = stationById.get(segment.destination_station_id)
    if (!from || !to) continue

    const link = linkKey(from.id, to.id)
    if (!linesOnLink.has(link)) linesOnLink.set(link, new Set())
    linesOnLink.get(link).add(segment.line_id)
  }

  // Segments are directional, and nearly every link appears once each way:
  // 754 rows for 379 links. Drawn as-is that is 375 of them stroked twice,
  // which shows the moment anything has opacity, for no benefit.
  //
  // Four links are genuinely one-way and must survive the dedupe rather than
  // being treated as a missing direction: the Piccadilly's Heathrow Terminal
  // 4 loop runs Hatton Cross to T4 to Terminals 2 & 3 and never back, and two
  // Metropolitan links north of Finchley Road are served in one direction
  // only. 754 / 2 would be 377, and the two it loses are real track.
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
    const link = linkKey(from.id, to.id)
    const key = `${segment.line_id}:${link}`
    if (drawn.has(key)) continue
    drawn.add(key)

    // Where this line sits in the bundle running over this link, as a
    // multiple of one line-width either side of the centre: a lone line gets
    // 0, a pair gets -0.5 and +0.5, a trio -1, 0 and +1.
    //
    // Sorted by line id so the order is stable. Without that the same link
    // could fan out differently between two renders of identical data, which
    // would look like the map twitching for no reason.
    const bundle = [...linesOnLink.get(link)].sort((a, b) => a - b)
    const offset = bundle.indexOf(segment.line_id) - (bundle.length - 1) / 2

    // Drawn in a canonical direction - low station id to high - rather than
    // whichever way round this segment happens to be. line-offset is applied
    // relative to the direction of travel, so two lines on one link described
    // in opposite directions would be pushed the same way and stay on top of
    // each other. That would have fixed some of the network and silently left
    // the rest broken.
    const [start, end] = from.id < to.id ? [from, to] : [to, from]

    features.push({
      type: 'Feature',
      properties: {
        colour: lineById.get(segment.line_id)?.colour ?? UNKNOWN_LINE_COLOUR,
        offset,
      },
      geometry: {
        type: 'LineString',
        // [lon, lat]. See the header - the order is the reverse of speech.
        coordinates: [
          [start.lon, start.lat],
          [end.lon, end.lat],
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
        properties: { name: shortName(station.name), naptanId: station.naptan_id },
        geometry: { type: 'Point', coordinates: [station.lon, station.lat] },
      })),
    },
  }
}
