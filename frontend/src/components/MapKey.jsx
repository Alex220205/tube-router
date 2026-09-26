/** What the marks on the map mean, and what the status wording's colours mean. */

import { useState } from 'react'
import { BAND_ORDER, BANDS } from '../lib/severity'

// Mirrors the paint in TubeMap.jsx. Duplicated rather than imported because those are
// MapLibre paint values in a WebGL canvas and these are CSS on DOM nodes, so they
// cannot be the same object - but they must be the same colours, and saying so here is
// what keeps them honest.
export const INK = '#1c1c1b'
export const STEP_FREE = '#0019a8'

/** The collapsible legend explaining every mark the map draws. */
export default function MapKey({ lines }) {
  const [open, setOpen] = useState(false)

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-tfl-grey font-bold tracking-wider uppercase">Key</h2>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="text-tfl-blue hover:text-tfl-blue-dark shrink-0 font-medium underline underline-offset-2"
        >
          {open ? 'Hide' : 'Show'}
        </button>
      </div>

      {open && (
        <ul className="mt-1.5 space-y-1.5">
          <Row swatch={<Dot ring={INK} />}>Station</Row>

          <Row swatch={<Dot ring={STEP_FREE} thick />}>
            Step-free: from street to platform at a station, and a wheelchair accessible
            entrance on a place near your destination
          </Row>

          <Row swatch={<Dot ring={INK} big />}>
            Start, end or change on a planned route
          </Row>

          <Row swatch={<Track colour="#E32017" />}>
            A line, in its own colour{lines?.length ? ` (${lines.length} of them)` : ''}
          </Row>

          <Row swatch={<Track colour="#E32017" faded />}>
            Dimmed while a route is shown
          </Row>

          <li className="text-tfl-grey border-tfl-line mt-2 border-t pt-2">
            Lines that share track are drawn side by side. Positions are the real ones,
            so a line between two stations is straight rather than following the track.
          </li>

          {/* The status panel's wording, in the colours it prints them in. Listed
              worst last so it reads as a scale. */}
          <li className="border-tfl-line mt-2 border-t pt-2">
            <h3 className="text-tfl-grey mb-1 font-bold tracking-wider uppercase">
              Line status
            </h3>
            <ul className="space-y-1">
              {BAND_ORDER.map((key) => (
                <li key={key} className="flex gap-2">
                  <span
                    className="w-24 shrink-0 font-medium"
                    style={{ color: BANDS[key].colour }}
                  >
                    {BANDS[key].label}
                  </span>
                  <span className="text-tfl-grey min-w-0 flex-1">{MEANINGS[key]}</span>
                </li>
              ))}
            </ul>
            <p className="text-tfl-grey mt-1.5">
              Grey is no status at all, which is not the same as good service.
            </p>
          </li>
        </ul>
      )}
    </div>
  )
}

// What each band means for the journey, not for the railway. "Severe delays" describes
// the trains; "the router still used it" describes the answer you were given, and that
// is the thing the colour is here to explain.
const MEANINGS = {
  good: 'Running normally.',
  info: 'Running. Something worth reading.',
  minor: 'Running, slower. The route still uses it.',
  bad: 'Running, much slower. The route still uses it.',
  part: 'Part of it is shut. The route goes round the closed stretch.',
  closed: 'Not running. The route will not use it at all.',
}

/** One key entry: a fixed-width swatch column so the labels line up. */
function Row({ swatch, children }) {
  return (
    <li className="flex items-center gap-2">
      <span className="flex w-6 shrink-0 justify-center">{swatch}</span>
      <span>{children}</span>
    </li>
  )
}

/** A station marker, drawn with the same ring colours the map uses. */
function Dot({ ring, thick = false, big = false }) {
  return (
    <span
      className="inline-block rounded-full bg-white"
      style={{
        width: big ? 13 : 9,
        height: big ? 13 : 9,
        border: `${thick ? 2.5 : 1.5}px solid ${ring}`,
      }}
      aria-hidden="true"
    />
  )
}

/** A stretch of line. */
function Track({ colour, faded = false }) {
  return (
    <span
      className="inline-block"
      style={{
        width: 22,
        height: 5,
        backgroundColor: colour,
        opacity: faded ? 0.25 : 1,
      }}
      aria-hidden="true"
    />
  )
}
