/**
 * What the marks on the map mean.
 *
 * WHY THIS EXISTS
 *     The map carries five distinct signals - a plain station, a step-free
 *     one, the lines, a drawn route and the dimmed rest of the network - and
 *     until this existed the page explained none of them. TfL's own map
 *     devotes a corner to exactly this, and a blue ring nobody has been told
 *     about is decoration rather than information.
 *
 *     Collapsed by default. It is reference material: needed once, then in
 *     the way.
 *
 * NO 2021 EQUIVALENT
 *     The old project drew no map. Its output was a list of station names in
 *     a Tkinter label, and a list of names needs no key. A key becomes
 *     necessary the moment information moves from words into marks, which is
 *     what drawing the network did.
 *
 * WHAT'S NEW
 *     The step-free entry, which is the only one carrying information the
 *     shapes cannot. TfL draw a wheelchair symbol; this draws a blue ring,
 *     because a 12px glyph is illegible at the zoom where a whole line fits
 *     and a ring reads at every zoom this map has.
 *
 *     It is also deliberately narrower than TfL's key. Theirs lists National
 *     Rail, river services, airports, cable car, fare zones and Oyster
 *     validity - none of which this map draws. A key describing marks that
 *     are not there is worse than no key.
 */

import { useState } from 'react'

// Mirrors the paint in TubeMap.jsx. Duplicated rather than imported because
// those are MapLibre paint values in a WebGL canvas and these are CSS on DOM
// nodes, so they cannot be the same object - but they must be the same
// colours, and saying so here is what keeps them honest.
const INK = '#1c1c1b'
const STEP_FREE = '#0019a8'

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
            Step-free access from street to platform
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
        </ul>
      )}
    </div>
  )
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
