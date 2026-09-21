/**
 * Tests for the severity bands.
 *
 * WHY THIS EXISTS
 *     Two risks. A severity TfL publishes that falls through every branch and
 *     renders with no colour, and - much worse - bands that disagree with the
 *     backend about which severities stop a journey.
 *
 *     The second is the one worth the file. The colours are not decoration:
 *     black says the router dropped the line and red says it routed around a
 *     closed stretch. If these sets drift from `NOT_RUNNING` and `PARTIAL` in
 *     backend/app/services/status.py, the panel explains a journey that did
 *     not happen, and every other test in the project still passes.
 *
 * NO 2021 EQUIVALENT
 *     The old project stored status as a sentence. There was no severity
 *     number, so there was nothing to band.
 */

import { describe, expect, it } from 'vitest'
import { band, BANDS, worstFirst } from './severity'

// TfL's /Line/Meta/Severity for the tube, read from the live endpoint rather
// than remembered. 0 to 20 with no gaps.
const PUBLISHED = Array.from({ length: 21 }, (_, level) => level)

describe('severity bands', () => {
  it('gives every severity TfL publishes a band and a colour', () => {
    for (const level of PUBLISHED) {
      const result = band(level)
      expect(result.key, `severity ${level}`).toBeTruthy()
      expect(result.colour, `severity ${level}`).toMatch(/^#[0-9a-f]{6}$/i)
    }

    // No status at all is its own band, and it is not "good". That
    // distinction is the one schemas/status.py exists to protect.
    expect(band(null).key).toBe('unknown')
    expect(band(undefined).key).toBe('unknown')

    // Distinct, or the colour coding does not code anything. The wording
    // itself is what gets coloured, so two bands sharing a value is two
    // bands the panel cannot tell apart.
    const colours = Object.values(BANDS).map((b) => b.colour)
    expect(new Set(colours).size).toBe(colours.length)
  })

  it('bands the closures exactly as the backend does', () => {
    const inBand = (key) => PUBLISHED.filter((level) => band(level).key === key)

    // PARTIAL in services/status.py. These are the severities where TfL's
    // affectedStops says which stretch is shut and the router suppresses
    // only that stretch.
    expect(inBand('part')).toEqual([3, 5, 11])

    // NOT_RUNNING minus PARTIAL: the line is gone entirely and the router
    // drops all of it.
    expect(inBand('closed')).toEqual([1, 2, 4, 16, 20])

    // Which makes the union the backend's NOT_RUNNING, and that is the set
    // this file exists to keep honest.
    expect([...inBand('part'), ...inBand('closed')].sort((a, b) => a - b)).toEqual([
      1, 2, 3, 4, 5, 11, 16, 20,
    ])

    // Good Service and No Issues, and nothing else, may read as running
    // normally.
    expect(inBand('good')).toEqual([10, 18])
  })

  it('orders the worst line first', () => {
    const rows = [
      { line_code: 'bakerloo', severity: 9 }, // minor delays
      { line_code: 'district', severity: 5 }, // part closure
      { line_code: 'victoria', severity: 4 }, // planned closure
    ]

    // A line that has stopped belongs above one running two minutes late.
    // Sorted the other way this still renders three rows and looks fine.
    expect(worstFirst(rows).map((r) => r.line_code)).toEqual([
      'victoria',
      'district',
      'bakerloo',
    ])

    // And the caller's array is not reordered underneath it.
    expect(rows[0].line_code).toBe('bakerloo')
  })
})
