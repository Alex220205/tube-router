/** Tests for the network-to-GeoJSON transform. */

import { describe, expect, it } from 'vitest'
import { toGeoJson } from './network-geojson'

// Two stations on one line, and the payload shape /network actually returns - checked
// against the live endpoint rather than guessed.
const network = {
  stations: [
    {
      id: 1,
      naptan_id: '940GZZLUOXC',
      name: 'Oxford Circus',
      lat: 51.515224,
      lon: -0.141903,
    },
    {
      id: 2,
      naptan_id: '940GZZLUGPK',
      name: 'Green Park',
      lat: 51.506947,
      lon: -0.142787,
    },
  ],
  segments: [
    { line_id: 10, origin_station_id: 1, destination_station_id: 2, seconds: 120 },
    { line_id: 10, origin_station_id: 2, destination_station_id: 1, seconds: 120 },
  ],
  lines: [
    { id: 10, code: 'victoria', name: 'Victoria', colour: '#0098D4', mode: 'tube' },
  ],
}

// Two lines sharing a corridor of two consecutive links.
//
// The station ids deliberately disagree with the geography: id 1 is the WESTMOST and id
// 2 the EASTMOST, with id 3 in the middle. That is not contrived - ids come from the
// order the seed inserted rows, and on the real Uxbridge branch the id order reverses
// the direction four times in six links.
const corridor = {
  stations: [
    { id: 1, naptan_id: 'A', name: 'West', lat: 51.55, lon: -0.45 },
    { id: 2, naptan_id: 'C', name: 'East', lat: 51.55, lon: -0.25 },
    { id: 3, naptan_id: 'B', name: 'Middle', lat: 51.55, lon: -0.35 },
  ],
  segments: [
    // West to Middle, and Middle to East, each carrying both lines and each stored in
    // whatever direction - exactly as the seed emits them.
    { line_id: 10, origin_station_id: 1, destination_station_id: 3, seconds: 120 },
    { line_id: 11, origin_station_id: 3, destination_station_id: 1, seconds: 140 },
    { line_id: 10, origin_station_id: 2, destination_station_id: 3, seconds: 120 },
    { line_id: 11, origin_station_id: 3, destination_station_id: 2, seconds: 140 },
  ],
  lines: [
    { id: 10, code: 'victoria', name: 'Victoria', colour: '#0098D4', mode: 'tube' },
    { id: 11, code: 'piccadilly', name: 'Piccadilly', colour: '#003688', mode: 'tube' },
  ],
}

describe('toGeoJson', () => {
  it('puts coordinates in [lon, lat] order, not [lat, lon]', () => {
    const { stations, segments } = toGeoJson(network)

    expect(stations.features[0].geometry.coordinates).toEqual([-0.141903, 51.515224])

    // Green Park first, because links are drawn west to east and it is the westmost of
    // the two by 0.0009 degrees - see westFirst. Still asserting the exact pair rather
    // than loosening the check: the failure this guards is a lat/lon swap, and that is
    // invisible to anything vaguer.
    expect(segments.features[0].geometry.coordinates).toEqual([
      [-0.142787, 51.506947],
      [-0.141903, 51.515224],
    ])
  })

  it('draws each link once, though the payload lists both directions', () => {
    // Segments are directional and every link appears twice. Left alone that is 754
    // features for 379 links, each stroked over itself.
    const { segments } = toGeoJson(network)

    expect(segments.features).toHaveLength(1)
  })

  it('fans out lines sharing track, on the same side for the whole corridor', () => {
    // 57 of the network's 314 links carry more than one line. Drawn without an offset
    // they are identical LineStrings stacked on each other and only the last painted is
    // visible - which is how the Metropolitan disappeared between Rayners Lane and
    // Uxbridge.
    const { segments } = toGeoJson(corridor)

    expect(segments.features).toHaveLength(4)

    // Every link drawn west to east. line-offset shifts a line relative to its
    // direction of travel, so a link drawn backwards puts its lines on the wrong side -
    // and the pair visibly swap places partway along the branch.
    for (const feature of segments.features) {
      const [start, end] = feature.geometry.coordinates
      expect(start[0]).toBeLessThan(end[0])
    }

    // And within each link the two lines are pushed to opposite sides, the same line to
    // the same side both times.
    const offsetsFor = (lon) =>
      Object.fromEntries(
        segments.features
          .filter((f) => f.geometry.coordinates[0][0] === lon)
          .map((f) => [f.properties.colour, f.properties.offset]),
      )

    expect(offsetsFor(-0.45)).toEqual({ '#003688': -0.5, '#0098D4': 0.5 })
    expect(offsetsFor(-0.35)).toEqual({ '#003688': -0.5, '#0098D4': 0.5 })
  })

  it('skips a segment naming a station the payload does not contain', () => {
    const { segments } = toGeoJson({
      ...network,
      segments: [
        { line_id: 10, origin_station_id: 1, destination_station_id: 999, seconds: 60 },
        { line_id: 10, origin_station_id: 1, destination_station_id: 2, seconds: 120 },
      ],
    })

    expect(segments.features).toHaveLength(1)
    expect(segments.features[0].properties.colour).toBe('#0098D4')
  })
})
