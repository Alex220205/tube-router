/**
 * Tests for the network-to-GeoJSON transform.
 *
 * WHY THIS EXISTS
 *     Three tests, and each guards a failure that renders perfectly while
 *     being wrong. That is the whole reason this logic was pulled out of
 *     TubeMap.jsx: the map cannot be unit-tested - MapLibre needs WebGL and
 *     jsdom has none - so anything worth checking has to live somewhere a
 *     test can reach it.
 *
 * NO 2021 EQUIVALENT
 *     There were no coordinates and no map. The table meant to hold them was
 *     created with malformed SQL and never held a row.
 */

import { describe, expect, it } from 'vitest'
import { toGeoJson } from './network-geojson'

// Two stations on one line, and the payload shape /network actually returns -
// checked against the live endpoint rather than guessed.
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

// Two lines over one stretch of track, described in OPPOSITE directions -
// which is what the seed actually produces, and the case that makes the
// canonical-direction rule matter.
const sharedTrack = {
  ...network,
  segments: [
    { line_id: 10, origin_station_id: 1, destination_station_id: 2, seconds: 120 },
    { line_id: 11, origin_station_id: 2, destination_station_id: 1, seconds: 140 },
  ],
  lines: [
    ...network.lines,
    { id: 11, code: 'piccadilly', name: 'Piccadilly', colour: '#003688', mode: 'tube' },
  ],
}

describe('toGeoJson', () => {
  it('puts coordinates in [lon, lat] order, not [lat, lon]', () => {
    const { stations, segments } = toGeoJson(network)

    // London is at roughly 51.5 north, 0.14 west. Reversed, these become
    // 51 degrees EAST of Greenwich and a fraction of a degree north - the
    // Indian Ocean, drawn without complaint. docs/TESTS.md records the
    // database side of this project being caught by the same inversion twice.
    expect(stations.features[0].geometry.coordinates).toEqual([-0.141903, 51.515224])
    expect(segments.features[0].geometry.coordinates).toEqual([
      [-0.141903, 51.515224],
      [-0.142787, 51.506947],
    ])
  })

  it('draws each link once, though the payload lists both directions', () => {
    // Segments are directional and every link appears twice. Left alone that
    // is 754 features for 379 links, each stroked over itself.
    const { segments } = toGeoJson(network)

    expect(segments.features).toHaveLength(1)
  })

  it('fans out two lines sharing one stretch of track, the same way round', () => {
    // 57 of the network's 314 links carry more than one line. Drawn without an
    // offset they are identical LineStrings stacked on each other and only the
    // last one painted is visible - which is how the Metropolitan disappeared
    // between Rayners Lane and Uxbridge, and the Circle and Hammersmith & City
    // vanished under the Metropolitan through Farringdon.
    const { segments } = toGeoJson(sharedTrack)

    expect(segments.features).toHaveLength(2)

    // Opposite signs, so they are pushed to opposite sides of the track.
    const offsets = segments.features.map((f) => f.properties.offset)
    expect(offsets).toEqual([-0.5, 0.5])

    // And both drawn the same way round. line-offset is applied relative to
    // the direction of travel, so two lines described in opposite directions
    // would be pushed to the SAME side and stay on top of each other - the
    // bug surviving the fix, on exactly the links the seed happens to emit
    // backwards.
    const [first, second] = segments.features.map((f) => f.geometry.coordinates)
    expect(first).toEqual(second)
  })

  it('skips a segment naming a station the payload does not contain', () => {
    // A dangling id would otherwise draw a line to undefined, which MapLibre
    // renders at null island rather than refusing. The frontend's version of
    // the check AUDIT.md calls the most valuable in the seed - and the good
    // segment still has to survive, or one bad row costs the whole map.
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
