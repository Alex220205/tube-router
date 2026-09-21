/**
 * Tests for the route-to-GeoJSON transform.
 *
 * WHY THIS EXISTS
 *     Two tests, and both guard a map that draws something wrong without
 *     complaining. Same reason network-geojson.test.js exists: MapLibre needs
 *     WebGL and jsdom has none, so the logic worth checking was put somewhere
 *     a test can reach it.
 *
 * NO 2021 EQUIVALENT
 *     No map, no coordinates, and a result that did not record which line any
 *     hop was on.
 */

import { describe, expect, it } from 'vitest'
import { toRouteGeoJson } from './route-geojson'

// Three stations on two lines. The payload shapes are the live ones: the
// network keys stations by integer id and carries naptan_id beside it, while
// a route's legs know only the NaPTAN id - which is the whole reason a join
// is needed.
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
      step_free: true,
    },
    {
      id: 3,
      naptan_id: '940GZZLUWSM',
      name: 'Westminster',
      lat: 51.501402,
      lon: -0.124971,
    },
  ],
  segments: [],
  lines: [
    { id: 10, code: 'victoria', name: 'Victoria', colour: '#0098D4', mode: 'tube' },
    { id: 11, code: 'jubilee', name: 'Jubilee', colour: '#A0A5A9', mode: 'tube' },
  ],
}

// Oxford Circus to Westminster, changing at Green Park.
const route = {
  found: true,
  legs: [
    {
      line: 'victoria',
      seconds: 120,
      stations: [
        { id: '940GZZLUOXC', name: 'Oxford Circus' },
        { id: '940GZZLUGPK', name: 'Green Park' },
      ],
    },
    {
      line: 'jubilee',
      seconds: 90,
      stations: [
        { id: '940GZZLUGPK', name: 'Green Park' },
        { id: '940GZZLUWSM', name: 'Westminster' },
      ],
    },
  ],
}

describe('toRouteGeoJson', () => {
  it('takes coordinates from the network, joined by NaPTAN id', () => {
    // The legs carry no coordinates at all - only ids and names. A join that
    // looks up the wrong key finds nothing and draws nothing; one that reads
    // the wrong fields draws a route in the Indian Ocean. Neither raises.
    const { line } = toRouteGeoJson(route, network)

    expect(line.features[0].geometry.coordinates).toEqual([
      [-0.141903, 51.515224],
      [-0.142787, 51.506947],
    ])
  })

  it('keeps the step-free marking on the stations it draws', () => {
    // The route's own stations are drawn on top of the network's, so a
    // transform that forgets step_free does not make the ring wrong - it
    // makes it vanish, and only once a route is planned. That is the one
    // moment somebody is checking whether they can get out at the other end.
    //
    // It shipped that way and was reported from a screenshot. Nothing raised,
    // every other assertion here passed, and the map looked entirely normal.
    const { stations } = toRouteGeoJson(route, network)

    const byName = new Map(
      stations.features.map((f) => [f.properties.name, f.properties.stepFree]),
    )

    expect(byName.get('Green Park')).toBe(true)
    expect(byName.get('Oxford Circus')).toBe(false)

    // Never undefined: MapLibre's `case` on a missing property takes the
    // fallback silently, so an absent flag and a false one would look the
    // same on the map and different in a test.
    for (const value of byName.values()) expect(typeof value).toBe('boolean')
  })

  it('marks only where you get on and off as the ends of the journey', () => {
    // The map places these labels first when two cannot both fit, so the
    // name that survives a collision is your destination rather than a
    // station you change at. Zoomed out on Heathrow Terminal 5 to Oxford
    // Circus, Oxford Circus used to lose its label to Green Park a kilometre
    // away, and the journey's destination had no name on it.
    //
    // A change is the end of one leg and the start of the next, so the
    // per-leg `major` flag is true for it too. Marking changes as termini
    // would put them in the same priority as the ends and bring the bug
    // straight back, with every assertion about `major` still passing.
    const { stations } = toRouteGeoJson(route, network)
    const terminus = new Map(
      stations.features.map((f) => [f.properties.name, f.properties.terminus]),
    )

    expect(terminus.get('Oxford Circus')).toBe(true)
    expect(terminus.get('Westminster')).toBe(true)
    expect(terminus.get('Green Park')).toBe(false)
  })

  it('draws a change as two legs, each in its own line colour', () => {
    // Merging the legs into one LineString is the tempting simplification.
    // It draws the whole journey in a single colour, which hides the change -
    // wrong in the one place a traveller most needs to see it.
    const { line } = toRouteGeoJson(route, network)

    expect(line.features).toHaveLength(2)
    expect(line.features.map((feature) => feature.properties.colour)).toEqual([
      '#0098D4',
      '#A0A5A9',
    ])
  })
})
