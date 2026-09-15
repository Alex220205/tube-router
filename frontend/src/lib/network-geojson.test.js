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
