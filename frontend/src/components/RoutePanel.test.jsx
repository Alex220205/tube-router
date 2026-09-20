/**
 * Tests for the route panel's leg listing.
 *
 * WHY THIS EXISTS
 *     Two risks, one test each, and both are silent when they break. A leg
 *     that lists the wrong stations still renders a plausible list, and an
 *     accordion that opens two legs at once still opens the one you clicked.
 *     Nothing raises in either case.
 *
 *     The rest of this component is deliberately untested. Durations, the
 *     singular of "1 change", the disruption bars and the not-found messages
 *     are all rendering a value the backend already pins, and a test for each
 *     would be a test that React works.
 *
 * NO 2021 EQUIVALENT
 *     The old project rendered a flat list of station names into a Tkinter
 *     label, with no record of which line each hop was on. There were no
 *     legs, so there was nothing to open.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import RoutePanel from './RoutePanel'

// Shaped like a real answer from POST /route, trimmed to two legs. The
// interchange appears at the end of one and the start of the next, which is
// what the API actually returns and what the panel is expected to show.
const ROUTE = {
  found: true,
  total_seconds: 5040,
  changes: 1,
  step_free: false,
  avoided_for_disruption: [],
  partly_closed: [],
  legs: [
    {
      line: 'central',
      seconds: 2760,
      stations: [
        { id: '940GZZLUEPG', name: 'Epping Underground Station' },
        { id: '940GZZLUTHB', name: 'Theydon Bois Underground Station' },
        { id: '940GZZLUDBN', name: 'Debden Underground Station' },
        { id: '940GZZLULVT', name: 'Liverpool Street Underground Station' },
      ],
    },
    {
      line: 'metropolitan',
      seconds: 2280,
      stations: [
        { id: '940GZZLULVT', name: 'Liverpool Street Underground Station' },
        { id: '940GZZLUMGT', name: 'Moorgate Underground Station' },
        { id: '940GZZLUBST', name: 'Baker Street Underground Station' },
      ],
    },
  ],
}

const LINES = [
  { code: 'central', name: 'Central', colour: '#E32017' },
  { code: 'metropolitan', name: 'Metropolitan', colour: '#9B0056' },
]

function renderPanel() {
  return render(
    <RoutePanel
      route={ROUTE}
      loading={false}
      error={null}
      objective="fastest"
      lines={LINES}
      stations={[]}
    />,
  )
}

describe('RoutePanel', () => {
  it('opening one leg closes the other', async () => {
    renderPanel()

    // Closed to start with. Forty-eight rows on arrival is a worse panel than
    // the summary it replaces.
    expect(screen.queryByText('Theydon Bois')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^Central/ }))
    expect(screen.getByText('Theydon Bois')).toBeInTheDocument()

    // The requirement, and the reason one index is held rather than a set of
    // them: opening another leg has to close the one before it. With a set,
    // both stay open and every other assertion here still passes.
    await userEvent.click(screen.getByRole('button', { name: /^Metropolitan/ }))
    expect(screen.queryByText('Theydon Bois')).not.toBeInTheDocument()
    expect(screen.getByText('Moorgate')).toBeInTheDocument()
  })

  it('an opened leg lists every station it passes through, in order', async () => {
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /^Central/ }))

    // Scoped to the list, because the two ends are also in the summary above
    // it. Reading the ends twice would pass a check that only looked for
    // names somewhere on the page.
    const stops = within(
      screen.getByRole('list', { name: 'Stops on the Central leg' }),
    ).getAllByRole('listitem')

    // Order matters as much as membership: a journey listed out of sequence
    // is worse than no journey, and nothing about the markup would show it.
    expect(stops.map((stop) => stop.textContent)).toEqual([
      'Epping',
      'Theydon Bois',
      'Debden',
      'Liverpool Street',
    ])
  })
})
