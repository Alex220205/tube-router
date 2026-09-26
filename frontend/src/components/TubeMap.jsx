/** The tube network, drawn on a map, with a planned route over it. */

import { Map, NavigationControl, setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import { toGeoJson } from '../lib/network-geojson'
import { toRouteGeoJson } from '../lib/route-geojson'

// Roughly central London, framed so zone 1 fills the view and the far ends of the
// Central and Piccadilly lines are a scroll away rather than off-planet.
const CENTRE = [-0.128, 51.509]
const ZOOM = 10.4

// Faint enough that the route reads as the subject, strong enough that the rest of the
// network is still recognisably a map.
const DIMMED = 0.25

// The map's own colours, as opposed to the lines'.
//
// These have to be hex literals: MapLibre paints into a WebGL canvas and
// cannot read the CSS custom properties in index.css, so `var(--color-tfl-
// ink)` would simply not resolve. They are named here, with the token they
// mirror, so changing the palette is two edits in two files rather than a
// hunt through eleven paint blocks.
const PAPER = '#f7f7f5' // --color-tfl-paper, the canvas and label halos
const INK = '#1c1c1b' // --color-tfl-ink, station rings and label text
const STATION_FILL = '#ffffff'

// The ring round a station marker. Step-free stations get TfL blue instead of ink,
// which is the cheap version of the wheelchair symbol on TfL's own map: a 12px glyph is
// illegible at the zoom where a whole line fits, and a ring reads at every zoom this
// map has.
const STATION_RING = '#1c1c1b'
const STATION_RING_STEP_FREE = '#0019a8' // --color-tfl-blue

// Thicker as you zoom in, so the network reads as a diagram from far out and as
// individual track up close. The two ends are named separately because line-offset has
// to shift by exactly one of these per line, and a zoom expression cannot be nested
// inside the multiply that does it.
const LINE_WIDTH_MIN = 1.5
const LINE_WIDTH_MAX = 5

// How far apart lines sharing a stretch of track are pushed, centre to centre. Exactly
// one line width, so they sit edge to edge with no background between them - a band of
// colour, the way TfL's own map draws the Circle, Hammersmith & City and Metropolitan
// running together from Baker Street round to Liverpool Street.
const LINE_GAP_MIN = LINE_WIDTH_MIN
const LINE_GAP_MAX = LINE_WIDTH_MAX
const LINE_WIDTH = [
  'interpolate',
  ['linear'],
  ['zoom'],
  9,
  LINE_WIDTH_MIN,
  13,
  LINE_WIDTH_MAX,
]

// MapLibre parses every GeoJSON source in a web worker and builds that worker's URL at
// runtime, which Vite cannot see at build time, so the worker would never be bundled
// and every source would silently stay empty. Importing it with `?worker&url` bundles
// it, and this hands MapLibre the URL.
setWorkerUrl(workerUrl)

// A style with no sources of its own. MapLibre requires a style object, and this is the
// smallest one that is valid: a single background layer.
const BLANK_STYLE = {
  version: 8,
  sources: {},
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': PAPER } },
  ],
}

export default function TubeMap({ network, route, onError }) {
  const container = useRef(null)

  // Whether the style has finished loading. Tracked here rather than asked of the map:
  // if `load` has already fired and map.isStyleLoaded() still answers false, a draw
  // waiting on `load` would never happen.
  const [ready, setReady] = useState(false)
  const map = useRef(null)

  // MapLibre reports almost everything through an 'error' event rather than by
  // throwing: a WebGL context it could not get, a source that would not parse, a glyph
  // it could not fetch.
  const report = useRef(onError)
  useEffect(() => {
    report.current = onError
  }, [onError])

  // Created once, and never in the same effect that updates the data. Re-creating a Map
  // leaks its WebGL context, and browsers cap those at around sixteen before new ones
  // silently fail to render - no error, no obvious cause, and it only shows up after
  // enough re-renders.
  useEffect(() => {
    if (map.current) return

    try {
      map.current = new Map({
        container: container.current,
        style: BLANK_STYLE,
        center: CENTRE,
        zoom: ZOOM,
        // Nothing here is legible upside down, and a rotated tube map helps nobody find
        // a station.
        dragRotate: false,
        attributionControl: false,
      })
    } catch (cause) {
      // The one thing MapLibre does throw rather than report: it could not get a WebGL
      // context. Software rendering disabled, a blocked GPU, a browser with hardware
      // acceleration off.
      report.current?.(cause.message)
      return
    }

    map.current.addControl(new NavigationControl({ showCompass: false }))

    // Attached before the event can fire, because the constructor above is synchronous
    // and `load` is not. This is the only thing that knows the style is ready, and the
    // effect below waits on it.
    map.current.on('load', () => setReady(true))

    map.current.on('error', (event) => {
      report.current?.(event?.error?.message ?? 'the map failed for an unstated reason')
    })

    return () => {
      map.current?.remove()
      map.current = null
      // The next map starts with an unloaded style. Leaving this true would let the
      // data effect run against it and add sources to a style that is not there yet -
      // which is only reachable through StrictMode's double mount in development, and
      // would be maddening to diagnose.
      setReady(false)
    }
  }, [])

  // Separate effect: the data arrives after the map is built, and may arrive again.
  // Sources are updated in place rather than re-added, because addSource on an existing
  // id throws.
  useEffect(() => {
    const m = map.current
    if (!ready || !m || !network) return

    const { segments, stations } = toGeoJson(network)
    const drawn = toRouteGeoJson(route, network)
    const hasRoute = drawn.line.features.length > 0

    if (m.getSource('segments')) {
      m.getSource('segments').setData(segments)
      m.getSource('stations').setData(stations)
      m.getSource('route').setData(drawn.line)
      m.getSource('route-stations').setData(drawn.stations)
    } else {
      addLayers(m, { segments, stations, drawn })
    }

    // Dim the rest of the network rather than hiding it. What a route did NOT take is
    // most of what makes it legible - one line on an empty canvas could be anywhere.
    m.setPaintProperty('segments', 'line-opacity', hasRoute ? DIMMED : 1)
    m.setPaintProperty('stations', 'circle-opacity', hasRoute ? DIMMED : 1)
    m.setPaintProperty('stations', 'circle-stroke-opacity', hasRoute ? DIMMED : 1)

    // The network's own labels go away while a route is up, so the only names on screen
    // are the ones on the journey. Two sets of labels fighting for the same space is
    // how a route ends up with its interchange unlabelled.
    m.setLayoutProperty('station-labels', 'visibility', hasRoute ? 'none' : 'visible')

    // The camera deliberately does not move. Fitting the view to the route is the
    // obvious touch, and it fights someone who has just panned somewhere on purpose.
  }, [ready, network, route])

  // Two divs, and the nesting is load-bearing.
  //
  // MapLibre puts `.maplibregl-map { position: relative }` on whatever element you hand
  // it, from a stylesheet with no cascade layer. Tailwind v4 emits its utilities inside
  // `@layer utilities`, and **unlayered CSS beats layered CSS whatever the source
  // order** - so `.absolute` loses to a rule that appears 89KB earlier in the same
  // file.
  return (
    <div className="absolute inset-0">
      <div ref={container} className="h-full w-full" />
    </div>
  )
}

/**
 * Add every source and layer, once, in drawing order.
 *
 * Order is why this is one function rather than four calls spread about: MapLibre
 * draws layers in the order they are added, so the route goes on after the network
 * and before the station dots. The other way round it either hides under the track
 * it runs along or paints over every interchange it passes through.
 */
function addLayers(m, { segments, stations, drawn }) {
  m.addSource('segments', { type: 'geojson', data: segments })
  m.addSource('route', { type: 'geojson', data: drawn.line })
  m.addSource('stations', { type: 'geojson', data: stations })
  m.addSource('route-stations', { type: 'geojson', data: drawn.stations })

  // One layer for all eleven lines. The colour is read per feature from the property
  // the transform set, so adding a line to the network is a data change rather than a
  // twelfth layer here.
  m.addLayer({
    id: 'segments',
    type: 'line',
    source: 'segments',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': ['get', 'colour'],
      // Thicker as you zoom in, so the network reads as a diagram from far out and as
      // individual track up close.
      'line-width': LINE_WIDTH,
      // Lines sharing a stretch of track are fanned out either side of it rather than
      // stacked. The shift is exactly one line width, so they sit touching rather than
      // overlapping or leaving a gap, at every zoom. The transform decides who goes
      // where; see network-geojson.js.
      'line-offset': [
        'interpolate',
        ['linear'],
        ['zoom'],
        9,
        ['*', ['get', 'offset'], LINE_GAP_MIN],
        13,
        ['*', ['get', 'offset'], LINE_GAP_MAX],
      ],
    },
  })

  // Above the network, below the stations. Wider than the track it covers, so the route
  // is visible at the zoom where the whole journey fits.
  m.addLayer({
    id: 'route',
    type: 'line',
    source: 'route',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': ['get', 'colour'],
      'line-width': ['interpolate', ['linear'], ['zoom'], 9, 4, 13, 9],
    },
  })

  // Stations above the track, or the interchanges disappear under it.
  m.addLayer({
    id: 'stations',
    type: 'circle',
    source: 'stations',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 1.6, 13, 4],
      'circle-color': STATION_FILL,
      'circle-stroke-color': [
        'case',
        ['get', 'stepFree'],
        STATION_RING_STEP_FREE,
        STATION_RING,
      ],
      // Slightly heavier on a step-free station, so the colour is not the only thing
      // carrying the meaning. Colour alone fails for anyone who cannot distinguish blue
      // from near-black, which is a poor property for the one marker that is about
      // accessibility.
      'circle-stroke-width': [
        'interpolate',
        ['linear'],
        ['zoom'],
        9,
        ['case', ['get', 'stepFree'], 0.9, 0.5],
        13,
        ['case', ['get', 'stepFree'], 2, 1.2],
      ],
    },
  })

  // The stations on the journey, above everything and at full strength while the other
  // 250-odd are dimmed to a quarter. Bigger and black-ringed, because at the zoom where
  // a whole route fits, a 2px white dot on a coloured line is not something anyone can
  // pick out.
  m.addLayer({
    id: 'route-stations',
    type: 'circle',
    source: 'route-stations',
    paint: {
      'circle-radius': [
        'interpolate',
        ['linear'],
        ['zoom'],
        9,
        ['case', ['get', 'major'], 4.5, 2.5],
        13,
        ['case', ['get', 'major'], 8, 5],
      ],
      'circle-color': STATION_FILL,
      // Step-free stays step-free while a route is drawn. This layer sits on top of the
      // network's own stations, so painting every ring ink here silently undid the
      // accessibility marking for exactly the journey somebody had just asked about.
      'circle-stroke-color': ['case', ['get', 'stepFree'], STATION_RING_STEP_FREE, INK],
      // Heavier again on step-free, so the colour is not the only signal - the same
      // pairing the network layer uses, scaled up because these circles are bigger.
      'circle-stroke-width': [
        'case',
        ['get', 'stepFree'],
        ['case', ['get', 'major'], 3.5, 2.5],
        ['case', ['get', 'major'], 2.5, 1.5],
      ],
    },
  })

  // Every other station the journey passes through, once there is room. The decision
  // points are named at any zoom by the layer below; these are the stops between them,
  // and not naming them at all left a zoomed-in route as a line of unlabelled dots -
  // you could see where to change and not where you were going through.
  m.addLayer({
    id: 'route-station-labels-minor',
    type: 'symbol',
    source: 'route-stations',
    filter: ['!', ['get', 'major']],
    minzoom: 12,
    layout: {
      'text-field': ['get', 'name'],
      'text-size': 11,
      'text-offset': [0, 1.1],
      'text-anchor': 'top',
    },
    paint: {
      'text-color': INK,
      'text-halo-color': PAPER,
      'text-halo-width': 2,
    },
  })

  // The ends of the journey and every change, named whatever the zoom. Added after the
  // minor labels so MapLibre resolves collisions in their favour - where two names
  // cannot both fit, the one you have to act on wins.
  m.addLayer({
    id: 'route-station-labels',
    type: 'symbol',
    source: 'route-stations',
    filter: ['get', 'major'],
    layout: {
      'text-field': ['get', 'name'],
      'text-size': 12,
      // Variable anchors, not a fixed one below the dot. MapLibre tries each in order
      // and only gives up when none of them fit.
      'text-variable-anchor': ['top', 'bottom', 'left', 'right'],
      'text-radial-offset': 0.9,
      'text-justify': 'auto',
      // Tighter than the default of 2, so two labels can sit closer before either has
      // to move. Every pixel here is a collision that does not happen.
      'text-padding': 1,
      // The ends of the journey are placed before the changes in the middle, so when
      // something genuinely cannot fit, the thing that goes is a station you pass
      // through rather than the one you are going to. Lower sorts first.
      'symbol-sort-key': ['case', ['get', 'terminus'], 0, 1],
    },
    paint: {
      'text-color': INK,
      'text-halo-color': PAPER,
      'text-halo-width': 2,
    },
  })

  // Only once there is room for them. Every station at zone-1 density is an unreadable
  // smear, and MapLibre drops overlapping labels rather than stacking them.
  m.addLayer({
    id: 'station-labels',
    type: 'symbol',
    source: 'stations',
    minzoom: 12,
    layout: {
      'text-field': ['get', 'name'],
      'text-size': 11,
      'text-offset': [0, 1.1],
      'text-anchor': 'top',
    },
    paint: {
      'text-color': INK,
      'text-halo-color': PAPER,
      'text-halo-width': 1.2,
    },
  })
}
