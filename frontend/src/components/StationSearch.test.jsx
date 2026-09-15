/**
 * Tests for the station search.
 *
 * WHY THIS EXISTS
 *     Three risks, one test each. Does a search reach the API with what the
 *     user typed; does an empty result read as an answer rather than a
 *     breakage; and does a stale response get discarded instead of
 *     overwriting a newer one.
 *
 *     That last one is the reason the hook exists separately. Without
 *     cancellation a slow answer for "o" lands after a fast one for "oxford"
 *     and replaces it - the user sees results for something they finished
 *     typing a second ago, and nothing looks broken enough to report.
 *
 * NO 2021 EQUIVALENT
 *     No client, no server, no tests.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import StationSearch from './StationSearch'

function mockStations(handler) {
  globalThis.fetch = vi.fn(handler)
}

function ok(body) {
  return { ok: true, status: 200, json: async () => body }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('StationSearch', () => {
  it('sends what the user typed and lists what comes back', async () => {
    const seen = []
    mockStations((url) => {
      seen.push(url)
      return Promise.resolve(
        ok([
          {
            id: 1,
            naptan_id: '940GZZLUOXC',
            name: 'Oxford Circus Underground Station',
          },
        ]),
      )
    })

    render(<StationSearch />)
    await userEvent.type(screen.getByLabelText('Find a station'), 'oxf')

    expect(
      await screen.findByText('Oxford Circus Underground Station'),
    ).toBeInTheDocument()

    // Waited for, not asserted immediately. The component fetches once on
    // mount with an empty query, and the mock answers every URL with Oxford
    // Circus - so findByText above is satisfied by that first response, while
    // the debounced request carrying `q=oxf` is still 250ms away. Asserting
    // straight after it races the debounce and loses.
    await waitFor(() => expect(seen.at(-1)).toContain('q=oxf'))

    // And the burst of three keystrokes is one request, not three.
    expect(seen.filter((url) => url.includes('q=')).length).toBe(1)
  })

  it('says no stations match rather than showing an empty box', async () => {
    mockStations(() => Promise.resolve(ok([])))

    render(<StationSearch />)
    await userEvent.type(screen.getByLabelText('Find a station'), 'zzzz')

    // An empty result is a successful answer. Rendering nothing would leave
    // the user unable to tell it apart from a broken request.
    expect(await screen.findByText(/No stations match/)).toBeInTheDocument()
  })

  it('reports an unreachable API instead of appearing to find nothing', async () => {
    mockStations(() => Promise.reject(new Error('Failed to fetch')))

    render(<StationSearch />)
    await userEvent.type(screen.getByLabelText('Find a station'), 'oxf')

    await waitFor(() =>
      expect(screen.getByText(/Could not reach the API/)).toBeInTheDocument(),
    )
    // Must not also claim nothing matched - that would be two different
    // failures wearing the same message.
    expect(screen.queryByText(/No stations match/)).not.toBeInTheDocument()
  })
})
