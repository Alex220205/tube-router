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

// Which line sits on which side when several share a stretch of track.
// Earlier in this list means further to the LEFT of travel, and links are
// always drawn west to east, so earlier means the northern or upper side.
//
// The order is editorial and has to be: line ids come from the order the seed
// inserted rows and mean nothing visually. Sorting by id put the District
// above the Piccadilly from Ealing Common down to Acton Town, which is the
// wrong way round - the District arrives at Ealing Common from the west (via
// Ealing Broadway) and the Piccadilly from the east (via North Ealing), so
// drawing the District on the upper side makes the two cross at the station.
//
// A line missing from this list sorts last, which is stable rather than
// correct - add it here if it ever shares track.
const LINE_ORDER = [
  'circle',
  'hammersmith-city',
  'metropolitan',
  'piccadilly',
  'district',
  'bakerloo',
  'central',
  'jubilee',
  'northern',
  'victoria',
  'waterloo-city',
]

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
 * The two ends of a link, always west to east.
 *
 * WHY GEOGRAPHY AND NOT ID
 *     `line-offset` shifts a line relative to its direction of travel, so
 *     which side a line sits on depends on which way round it is drawn. Every
 *     link in a corridor therefore has to be drawn the same way, or lines
 *     swap sides at some stations and not others.
 *
 *     Ordering by station id looks like it does that, and does not: ids come
 *     from the order the seed inserted rows, which has nothing to do with
 *     where the stations are. Along Uxbridge to Rayners Lane it reverses the
 *     direction **four times in six links**, and the Metropolitan and
 *     Piccadilly visibly trade places down the branch.
 *
 *     Longitude is stable along a corridor in a way an id never is. Latitude
 *     breaks the tie for track running exactly north-south.
 *
 * @param {object} a A station with lon and lat.
 * @param {object} b The other station.
 * @returns {Array<object>} The pair, westmost first.
 */
function westFirst(a, b) {
  if (a.lon !== b.lon) return a.lon < b.lon ? [a, b] : [b, a]
  return a.lat < b.lat ? [a, b] : [b, a]
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
    // Sorted by LINE_ORDER so the order is both stable and chosen. Without a
    // fixed order the same link could fan out differently between two renders
    // of identical data, which would look like the map twitching for no
    // reason; without a chosen one, the side a line lands on is decided by
    // the order rows happened to be inserted.
    const rank = (id) => {
      const i = LINE_ORDER.indexOf(lineById.get(id)?.code)
      return i === -1 ? LINE_ORDER.length : i
    }
    const bundle = [...linesOnLink.get(link)].sort((a, b) => rank(a) - rank(b))
    const offset = bundle.indexOf(segment.line_id) - (bundle.length - 1) / 2

    // Always west to east, whichever way round this segment happens to be
    // stored. See westFirst: the direction decides which side of the track
    // each line lands on, so it has to be consistent along a whole corridor
    // and not just within one link.
    const [start, end] = westFirst(from, to)

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
        properties: {
          name: shortName(station.name),
          naptanId: station.naptan_id,
          // At least one platform reachable without stairs. Drawn as a ring
          // colour rather than a wheelchair glyph: a 12px icon is unreadable
          // at the zoom where a whole line fits, and a ring is legible at
          // every zoom the map has.
          stepFree: Boolean(station.step_free),
        },
        geometry: { type: 'Point', coordinates: [station.lon, station.lat] },
      })),
    },
  }
}
