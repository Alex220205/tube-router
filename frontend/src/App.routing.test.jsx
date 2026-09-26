/** Tests for planning a journey. */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

const STATIONS = [
  {
    id: 1,
    naptan_id: '940GZZLUOXC',
    name: 'Oxford Circus',
    lat: 51.5152,
    lon: -0.1419,
  },
  { id: 2, naptan_id: '940GZZLUGPK', name: 'Green Park', lat: 51.5069, lon: -0.1427 },
]

const LINES = [
  { id: 10, code: 'victoria', name: 'Victoria', colour: '#0098D4', mode: 'tube' },
]

const A_ROUTE = {
  found: true,
  reason: null,
  total_seconds: 120,
  changes: 0,
  step_free: false,
  avoided_for_disruption: [],
  legs: [
    {
      line: 'victoria',
      seconds: 120,
      stations: [
        { id: '940GZZLUOXC', name: 'Oxford Circus' },
        { id: '940GZZLUGPK', name: 'Green Park' },
      ],
    },
  ],
}

function ok(body) {
  return { ok: true, status: 200, json: async () => body }
}

/** Stub every endpoint the page calls, and record what was posted to /route. */
function mockApi(route) {
  const asked = []

  globalThis.fetch = vi.fn((url, options) => {
    if (url.includes('/health')) {
      return Promise.resolve(ok({ status: 'ok', database: 'ok', version: '0.1.0' }))
    }
    if (url.includes('/network')) {
      return Promise.resolve(ok({ stations: STATIONS, segments: [], lines: LINES }))
    }
    if (url.includes('/stations')) {
      return Promise.resolve(ok(STATIONS))
    }
    if (url.includes('/route')) {
      asked.push(JSON.parse(options.body))
      return Promise.resolve(ok(route))
    }
    return Promise.reject(new Error(`unexpected request to ${url}`))
  })

  return asked
}

/** Pick Oxford Circus as the origin and Green Park as the destination. */
async function chooseBothEnds() {
  await userEvent.type(screen.getByLabelText('From'), 'ox')
  await userEvent.click(await screen.findByRole('button', { name: 'Oxford Circus' }))

  await userEvent.type(screen.getByLabelText('To'), 'gr')
  await userEvent.click(await screen.findByRole('button', { name: 'Green Park' }))
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('planning a journey', () => {
  it('asks for the objective the user selected, not always the default', async () => {
    const asked = mockApi(A_ROUTE)

    render(<App />)
    await chooseBothEnds()

    await waitFor(() => expect(asked).toHaveLength(1))
    expect(asked.at(-1)).toEqual({
      origin: '940GZZLUOXC',
      destination: '940GZZLUGPK',
      objective: 'fastest',
    })

    await userEvent.click(screen.getByLabelText('Step-free'))

    // The point of the test. A toggle that renders its selection correctly and keeps
    // asking for the fastest route is invisible from everywhere else - the page shows a
    // checked radio and a plausible journey.
    await waitFor(() => expect(asked).toHaveLength(2))
    expect(asked.at(-1).objective).toBe('step_free')
  })

  it('says why there is no route rather than showing nothing', async () => {
    mockApi({
      found: false,
      reason: 'disconnected',
      total_seconds: 0,
      changes: 0,
      step_free: false,
      legs: [],
      avoided_for_disruption: [],
    })

    render(<App />)
    await chooseBothEnds()

    // found: false is a successful answer, and arrives as a 200. Rendering nothing
    // would leave it indistinguishable from a request that failed.
    expect(
      await screen.findByText('No route between these two stations.'),
    ).toBeInTheDocument()
  })
})
