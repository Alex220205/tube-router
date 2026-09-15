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

import { Map, NavigationControl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef } from 'react'
import { toGeoJson } from '../lib/network-geojson'
import { toRouteGeoJson } from '../lib/route-geojson'

// Roughly central London, framed so zone 1 fills the view and the far ends of
// the Central and Piccadilly lines are a scroll away rather than off-planet.
const CENTRE = [-0.128, 51.509]
const ZOOM = 10.4

// Faint enough that the route reads as the subject, strong enough that the
// rest of the network is still recognisably a map.
const DIMMED = 0.25

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

    map.current.on('error', (event) => {
      report.current?.(event?.error?.message ?? 'the map failed for an unstated reason')
    })

    return () => {
      map.current?.remove()
      map.current = null
    }
  }, [])

  // Separate effect: the data arrives after the map is built, and may arrive
  // again. Sources are updated in place rather than re-added, because
  // addSource on an existing id throws.
  useEffect(() => {
    if (!map.current || !network) return

    const { segments, stations } = toGeoJson(network)
    const routeLine = toRouteGeoJson(route, network)
    const hasRoute = routeLine.features.length > 0

    const draw = () => {
      const m = map.current
      if (!m) return

      if (m.getSource('segments')) {
        m.getSource('segments').setData(segments)
        m.getSource('stations').setData(stations)
        m.getSource('route').setData(routeLine)
      } else {
        addLayers(m, { segments, stations, routeLine })
      }

      // Dim the rest of the network rather than hiding it. What a route did
      // NOT take is most of what makes it legible - one line on an empty
      // canvas could be anywhere.
      m.setPaintProperty('segments', 'line-opacity', hasRoute ? DIMMED : 1)
      m.setPaintProperty('stations', 'circle-opacity', hasRoute ? DIMMED : 1)

      // The camera deliberately does not move. Fitting the view to the route
      // is the obvious touch, and it fights someone who has just panned
      // somewhere on purpose.
    }

    // Sources cannot be added before the style has loaded, and whether it has
    // depends on how fast /network answered.
    if (map.current.isStyleLoaded()) draw()
    else map.current.once('load', draw)
  }, [network, route])

  return <div ref={container} className="absolute inset-0" />
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
 * @param {{segments: object, stations: object, routeLine: object}} data
 */
function addLayers(m, { segments, stations, routeLine }) {
  m.addSource('segments', { type: 'geojson', data: segments })
  m.addSource('route', { type: 'geojson', data: routeLine })
  m.addSource('stations', { type: 'geojson', data: stations })

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
      'line-width': ['interpolate', ['linear'], ['zoom'], 9, 1.5, 13, 5],
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
