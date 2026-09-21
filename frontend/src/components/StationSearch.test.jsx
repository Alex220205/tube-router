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
 *
 * WHAT'S NEW
 *     The component takes an id and a label now, so these render it the way
 *     App does. Phase 8b made it reusable, which is not a new failure mode -
 *     whether the label prop reaches the label is the kind of thing that
 *     fails loudly, at once, in every other test here.
 *
 *     Two more since, both about the keyboard, because a keyboard path that
 *     breaks does not throw: the key is pressed, nothing happens, and the
 *     only person who finds out is someone who was not going to use the
 *     mouse anyway.
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

function station(id, naptan, name) {
  return { id, naptan_id: naptan, name }
}

// Rendered the way App renders it. Nothing is selected, which is the state
// every one of these tests is about.
function renderSearch(onSelect = () => {}) {
  return render(
    <StationSearch id="from" label="From" selected={null} onSelect={onSelect} />,
  )
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

    renderSearch()
    await userEvent.type(screen.getByLabelText('From'), 'oxf')

    // "Oxford Circus", not "Oxford Circus Underground Station". The database
    // stores TfL's commonName verbatim - a Phase 1 decision - and the suffix
    // is trimmed on the way to the screen by lib/station-name.js, because it
    // is the same eighteen characters on every row in the list.
    expect(await screen.findByText('Oxford Circus')).toBeInTheDocument()

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

    renderSearch()
    await userEvent.type(screen.getByLabelText('From'), 'zzzz')

    // An empty result is a successful answer. Rendering nothing would leave
    // the user unable to tell it apart from a broken request.
    expect(await screen.findByText(/No stations match/)).toBeInTheDocument()
  })

  it('picks the only result on Enter', async () => {
    mockStations(() =>
      Promise.resolve(
        ok([station(1, '940GZZLUOXC', 'Oxford Circus Underground Station')]),
      ),
    )

    const chosen = vi.fn()
    renderSearch(chosen)

    const box = screen.getByLabelText('From')
    await userEvent.type(box, 'oxf')
    await screen.findByText('Oxford Circus')

    // Nothing left to choose between, so typing enough to be unambiguous is
    // the choice. Without this the user types a full station name, sees one
    // row, presses Enter and watches nothing happen.
    await userEvent.keyboard('{Enter}')

    await waitFor(() => expect(chosen).toHaveBeenCalledTimes(1))
    expect(chosen.mock.calls[0][0].naptan_id).toBe('940GZZLUOXC')
  })

  it('walks the list with the arrow keys and picks with Enter', async () => {
    mockStations(() =>
      Promise.resolve(
        ok([
          station(1, '940GZZLUHR4', 'Heathrow Terminal 4 Underground Station'),
          station(2, '940GZZLUHR5', 'Heathrow Terminal 5 Underground Station'),
        ]),
      ),
    )

    const chosen = vi.fn()
    renderSearch(chosen)

    await userEvent.type(screen.getByLabelText('From'), 'heathrow')
    await screen.findByText('Heathrow Terminal 4')

    // Down into the list, down again, then Enter. With more than one result
    // Enter in the box deliberately does nothing, so this IS the keyboard
    // path to a choice - if focus does not move, there is no other one.
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByText('Heathrow Terminal 4')).toHaveFocus()

    await userEvent.keyboard('{ArrowDown}{Enter}')

    await waitFor(() => expect(chosen).toHaveBeenCalledTimes(1))
    expect(chosen.mock.calls[0][0].naptan_id).toBe('940GZZLUHR5')
  })

  it('does not pick a result left over from the previous search', async () => {
    // Found by the end to end sweep, not by reading the code. Pick Oxford
    // Circus, type "heathrow", press Enter straight away - and the box read
    // "Oxford Circus". For the 250ms before the debounced request went out,
    // the hook still held the last query's single result with loading false,
    // so Enter saw exactly one result and took it.
    //
    // A fast typist got the wrong station, silently. See ISSUES.md #31.
    mockStations((url) => {
      const q = (new URL(url).searchParams.get('q') ?? '').toLowerCase()
      if (q.startsWith('oxford')) {
        return Promise.resolve(
          ok([station(1, '940GZZLUOXC', 'Oxford Circus Underground Station')]),
        )
      }
      if (q.startsWith('heathrow')) {
        return Promise.resolve(
          ok([
            station(2, '940GZZLUHR4', 'Heathrow Terminal 4 Underground Station'),
            station(3, '940GZZLUHR5', 'Heathrow Terminal 5 Underground Station'),
          ]),
        )
      }
      return Promise.resolve(ok([]))
    })

    const chosen = vi.fn()
    renderSearch(chosen)
    const box = screen.getByLabelText('From')

    await userEvent.type(box, 'oxford circus')
    await screen.findByText('Oxford Circus')
    await userEvent.keyboard('{Enter}')
    await waitFor(() =>
      expect(chosen).toHaveBeenCalledWith(
        expect.objectContaining({ naptan_id: '940GZZLUOXC' }),
      ),
    )
    chosen.mockClear()

    // Type and press Enter inside the debounce window, as a person does.
    await userEvent.clear(box)
    await userEvent.type(box, 'heathrow{Enter}')

    expect(chosen).not.toHaveBeenCalledWith(
      expect.objectContaining({ naptan_id: '940GZZLUOXC' }),
    )
  })

  it('reports an unreachable API instead of appearing to find nothing', async () => {
    mockStations(() => Promise.reject(new Error('Failed to fetch')))

    renderSearch()
    await userEvent.type(screen.getByLabelText('From'), 'oxf')

    await waitFor(() =>
      expect(screen.getByText(/Could not reach the API/)).toBeInTheDocument(),
    )
    // Must not also claim nothing matched - that would be two different
    // failures wearing the same message.
    expect(screen.queryByText(/No stations match/)).not.toBeInTheDocument()
  })
})
