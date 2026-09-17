/**
 * The tube network, drawn on a map, with a planned route over it.
 *
 * WHY THIS EXISTS
 *     The first thing in this project that looks like a journey planner. It
 *     draws 272 stations at their real coordinates and 379 links in TfL's
 *     line colours, and since Phase 8b the route you asked for on top.
 *
 * NO 2021 EQUIVALENT
 *     The old project drew nothing at all. docs/AUDIT.md found the table
 *     meant to hold coordinates had been created with malformed SQL - the
 *     commas were missing, so SQLite parsed three columns as one - and it
 *     held zero rows for five years. There was no map because there was
 *     nothing to put on one.
 *
 * WHAT'S NEW
 *     No basemap. MapLibre usually sits on top of tiles from somewhere; this
 *     draws on a flat canvas instead, so there is no tile host, no API key,
 *     no usage policy and nothing external that can be slow or gone. The
 *     positions are real and the connections are straight lines, which is
 *     exactly what the data supports: TfL's track geometry was never sourced,
 *     and drawing curves we do not have would be a prettier lie.
 *
 *     Phase 8b adds the route. The rest of the network dims rather than
 *     disappearing, and the camera stays where the user left it.
 */

import { Map, NavigationControl, setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import { toGeoJson } from '../lib/network-geojson'
import { toRouteGeoJson } from '../lib/route-geojson'

// Roughly central London, framed so zone 1 fills the view and the far ends of
// the Central and Piccadilly lines are a scroll away rather than off-planet.
const CENTRE = [-0.128, 51.509]
const ZOOM = 10.4

// Faint enough that the route reads as the subject, strong enough that the
// rest of the network is still recognisably a map.
const DIMMED = 0.25

// Thicker as you zoom in, so the network reads as a diagram from far out and
// as individual track up close. The two ends are named separately because
// line-offset has to shift by exactly one of these per line, and a zoom
// expression cannot be nested inside the multiply that does it.
const LINE_WIDTH_MIN = 1.5
const LINE_WIDTH_MAX = 5
const LINE_WIDTH = [
  'interpolate',
  ['linear'],
  ['zoom'],
  9,
  LINE_WIDTH_MIN,
  13,
  LINE_WIDTH_MAX,
]

// MapLibre parses every GeoJSON source in a web worker, and finds that worker
// by building its URL at runtime:
//
//     new URL(`./${isDev ? 'maplibre-gl-worker-dev.mjs' : 'maplibre-gl-worker.mjs'}`, base)
//
// A template literal, not a string literal. Vite can only emit an asset for
// `new URL('./literal', import.meta.url)`, which it can see at build time, so
// the worker is never bundled. In production the URL resolves to
// /assets/maplibre-gl-worker.mjs, that 404s, no worker starts, **no source
// ever parses** - and MapLibre reports nothing, because a failed worker fetch
// is not an error it surfaces. The background layer paints, the layers exist,
// every source sits permanently at zero features, and the page is an empty
// grey rectangle.
//
// `?worker&url` makes Vite bundle the worker with its dependencies - it pulls
// in a 500KB shared chunk, so copying the file alone would fail the same way
// one level down - and hand back the hashed URL of the result. setWorkerUrl is
// MapLibre's own supported way to say where it went.
//
// Called at module scope, because it has to be set before any Map is
// constructed.
setWorkerUrl(workerUrl)

// A style with no sources of its own. MapLibre requires a style object, and
// this is the smallest one that is valid: a single background layer.
const BLANK_STYLE = {
  version: 8,
  sources: {},
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#f7f7f5' } },
  ],
}

/**
 * @param {object} props
 * @param {object | null} props.network The /network payload, or null while it
 *   is still loading.
 * @param {object | null} props.route A RouteResponse, or null when no journey
 *   has been planned. A route that was not found is handled by the transform
 *   rather than here, so clearing the map and drawing on it are one path.
 * @param {(message: string) => void} [props.onError] Called with whatever
 *   MapLibre complains about. See the note below on why this exists.
 */
export default function TubeMap({ network, route, onError }) {
  const container = useRef(null)

  // Whether the style has finished loading. See the long note on the data
  // effect below - this replaces asking the map, which was a race.
  const [ready, setReady] = useState(false)
  const map = useRef(null)

  // MapLibre reports almost everything through an 'error' event rather than
  // by throwing: a WebGL context it could not get, a source that would not
  // parse, a glyph it could not fetch. With no listener those go to the
  // console and nowhere else, so the page renders a blank canvas and says
  // nothing - which is precisely the failure this project keeps arguing
  // against everywhere else. Anything it reports is now put on screen.
  //
  // Held in a ref, and updated in an effect rather than during render: the
  // listener is registered once when the map is built, and reading the prop
  // through a ref means a new callback does not require tearing the map down
  // and putting it back up to hear about it.
  const report = useRef(onError)
  useEffect(() => {
    report.current = onError
  }, [onError])

  // Created once, and never in the same effect that updates the data.
  // Re-creating a Map leaks its WebGL context, and browsers cap those at
  // around sixteen before new ones silently fail to render - no error, no
  // obvious cause, and it only shows up after enough re-renders.
  useEffect(() => {
    if (map.current) return

    try {
      map.current = new Map({
        container: container.current,
        style: BLANK_STYLE,
        center: CENTRE,
        zoom: ZOOM,
        // Nothing here is legible upside down, and a rotated tube map helps
        // nobody find a station.
        dragRotate: false,
        attributionControl: false,
      })
    } catch (cause) {
      // The one thing MapLibre does throw rather than report: it could not
      // get a WebGL context. Software rendering disabled, a blocked GPU, a
      // browser with hardware acceleration off. Uncaught here it would take
      // the whole React tree down and leave a white page with no explanation,
      // which is a worse outcome than a map-shaped hole and a sentence.
      report.current?.(cause.message)
      return
    }

    map.current.addControl(new NavigationControl({ showCompass: false }))

    // Attached before the event can fire, because the constructor above is
    // synchronous and `load` is not. This is the only thing that knows the
    // style is ready, and the effect below waits on it.
    map.current.on('load', () => setReady(true))

    map.current.on('error', (event) => {
      report.current?.(event?.error?.message ?? 'the map failed for an unstated reason')
    })

    return () => {
      map.current?.remove()
      map.current = null
      // The next map starts with an unloaded style. Leaving this true would
      // let the data effect run against it and add sources to a style that is
      // not there yet - which is only reachable through StrictMode's double
      // mount in development, and would be maddening to diagnose.
      setReady(false)
    }
  }, [])

  // Separate effect: the data arrives after the map is built, and may arrive
  // again. Sources are updated in place rather than re-added, because
  // addSource on an existing id throws.
  //
  // It waits on `ready` rather than asking the map whether its style is
  // loaded. The previous version did the latter, and it is a race:
  //
  //     if (map.isStyleLoaded()) draw()
  //     else map.once('load', draw)
  //
  // If `load` has already fired and `isStyleLoaded()` still answers false -
  // which it does, because it also requires every source to be loaded, and
  // between the two calls nothing guarantees otherwise - then `once('load')`
  // subscribes to an event that has been and gone. Nothing draws, nothing
  // errors, and the map is a blank canvas with the data sitting in memory
  // beside it.
  //
  // A flag set by the one `load` handler cannot miss it: the handler is
  // attached synchronously when the map is constructed, so the event cannot
  // have fired first, and a flag - unlike an event - is still true later.
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

    // Dim the rest of the network rather than hiding it. What a route did NOT
    // take is most of what makes it legible - one line on an empty canvas
    // could be anywhere.
    m.setPaintProperty('segments', 'line-opacity', hasRoute ? DIMMED : 1)
    m.setPaintProperty('stations', 'circle-opacity', hasRoute ? DIMMED : 1)
    m.setPaintProperty('stations', 'circle-stroke-opacity', hasRoute ? DIMMED : 1)

    // The network's own labels go away while a route is up, so the only names
    // on screen are the ones on the journey. Two sets of labels fighting for
    // the same space is how a route ends up with its interchange unlabelled.
    m.setLayoutProperty(
      'station-labels',
      'visibility',
      hasRoute ? 'none' : 'visible',
    )

    // The camera deliberately does not move. Fitting the view to the route is
    // the obvious touch, and it fights someone who has just panned somewhere
    // on purpose.
  }, [ready, network, route])

  // Two divs, and the nesting is load-bearing.
  //
  // MapLibre puts `.maplibregl-map { position: relative }` on whatever element
  // you hand it, from a stylesheet with no cascade layer. Tailwind v4 emits
  // its utilities inside `@layer utilities`, and **unlayered CSS beats layered
  // CSS whatever the source order** - so `.absolute` loses to a rule that
  // appears 89KB earlier in the same file.
  //
  // A single `absolute inset-0` div therefore ends up `position: relative`,
  // where inset-0 sets offsets instead of size. The box collapses to height 0,
  // the canvas inside it keeps its default 300px, `overflow: hidden` clips it,
  // and the result is an empty page with no error anywhere: MapLibre is
  // drawing perfectly into a container nobody can see.
  //
  // So the outer div does the positioning and is not MapLibre's to restyle.
  // The inner one is the map, and fills its parent - nothing in MapLibre's
  // CSS sets a height, so `h-full` is uncontested.
  return (
    <div className="absolute inset-0">
      <div ref={container} className="h-full w-full" />
    </div>
  )
}

/**
 * Add every source and layer, once, in drawing order.
 *
 * Order is why this is one function rather than four calls spread about:
 * MapLibre draws layers in the order they are added, so the route goes on
 * after the network and before the station dots. The other way round it
 * either hides under the track it runs along or paints over every
 * interchange it passes through.
 *
 * @param {object} m The map.
 * @param {{segments: object, stations: object, drawn: object}} data
 */
function addLayers(m, { segments, stations, drawn }) {
  m.addSource('segments', { type: 'geojson', data: segments })
  m.addSource('route', { type: 'geojson', data: drawn.line })
  m.addSource('stations', { type: 'geojson', data: stations })
  m.addSource('route-stations', { type: 'geojson', data: drawn.stations })

  // One layer for all eleven lines. The colour is read per feature from the
  // property the transform set, so adding a line to the network is a data
  // change rather than a twelfth layer here.
  m.addLayer({
    id: 'segments',
    type: 'line',
    source: 'segments',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': ['get', 'colour'],
      // Thicker as you zoom in, so the network reads as a diagram from far
      // out and as individual track up close.
      'line-width': LINE_WIDTH,
      // Lines sharing a stretch of track are fanned out either side of it
      // rather than stacked. The shift is exactly one line width, so they sit
      // touching rather than overlapping or leaving a gap, at every zoom. The
      // transform decides who goes where; see network-geojson.js.
      //
      // The zoom interpolation has to be the OUTERMOST expression, with the
      // multiply inside each stop. Wrapping it the other way round -
      // ['*', ['get','offset'], LINE_WIDTH] - is rejected at addLayer time
      // with "Cannot style non-existing layer", because a zoom expression is
      // only allowed at the top level of a property value.
      'line-offset': [
        'interpolate',
        ['linear'],
        ['zoom'],
        9,
        ['*', ['get', 'offset'], LINE_WIDTH_MIN],
        13,
        ['*', ['get', 'offset'], LINE_WIDTH_MAX],
      ],
    },
  })

  // Above the network, below the stations. Wider than the track it covers,
  // so the route is visible at the zoom where the whole journey fits.
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
      'circle-color': '#ffffff',
      'circle-stroke-color': '#111111',
      'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 9, 0.5, 13, 1.2],
    },
  })

  // The stations on the journey, above everything and at full strength while
  // the other 250-odd are dimmed to a quarter. Bigger and black-ringed,
  // because at the zoom where a whole route fits, a 2px white dot on a
  // coloured line is not something anyone can pick out.
  //
  // Two sizes. The ends of the journey and every change are decision points -
  // places a traveller has to do something - and the stations between them are
  // not, so the ones that matter are drawn nearly twice the size.
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
      'circle-color': '#ffffff',
      'circle-stroke-color': '#1c1c1b',
      'circle-stroke-width': ['case', ['get', 'major'], 2.5, 1.5],
    },
  })

  // Named whenever a route is showing, whatever the zoom. The rule below -
  // labels only past zoom 12 - exists because 272 of them at once is a smear;
  // a dozen on one journey is the thing you actually wanted to read.
  m.addLayer({
    id: 'route-station-labels',
    type: 'symbol',
    source: 'route-stations',
    filter: ['get', 'major'],
    layout: {
      'text-field': ['get', 'name'],
      'text-size': 12,
      'text-offset': [0, 1.2],
      'text-anchor': 'top',
      'text-allow-overlap': false,
    },
    paint: {
      'text-color': '#1c1c1b',
      'text-halo-color': '#f7f7f5',
      'text-halo-width': 2,
    },
  })

  // Only once there is room for them. Every station at zone-1 density is an
  // unreadable smear, and MapLibre drops overlapping labels rather than
  // stacking them.
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
      'text-color': '#111111',
      'text-halo-color': '#f7f7f5',
      'text-halo-width': 1.2,
    },
  })
}
