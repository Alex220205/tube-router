/**
 * Tests for the API status panel.
 *
 * WHY THIS EXISTS
 *     The component is parked - see ApiStatus.jsx - and these are kept with
 *     it, because a component nobody has mounted for a while is exactly the
 *     one that quietly stops working.
 *
 *     The interesting behaviour is not that a heading renders - it is that
 *     the three outcomes are told apart. "Degraded" (the API answered and
 *     reports Postgres is down) and "unreachable" (the API did not answer)
 *     look similar on screen and have completely different causes, so a page
 *     that conflates them sends you debugging the wrong thing.
 *
 * NO 2021 EQUIVALENT
 *     The old project had no tests at all.
 */

import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ApiStatus from './ApiStatus'

// fetch is stubbed rather than the api module, so api.js - the URL building
// and the status check - is exercised by these tests too.
function mockHealth(payload) {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload,
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ApiStatus', () => {
  // Status and database frequently hold the same word, so querying by text
  // alone is ambiguous. <dd> carries the implicit ARIA role "definition",
  // which lets the three values be read positionally - and asserts they are
  // in the documented order as a side effect.
  const definitionValues = () =>
    screen.getAllByRole('definition').map((node) => node.textContent)

  it('renders the healthy status returned by the API', async () => {
    mockHealth({ status: 'ok', database: 'ok', version: '0.1.0' })

    render(<ApiStatus />)
    await screen.findByText('0.1.0')

    expect(definitionValues()).toEqual(['ok', 'ok', '0.1.0'])
  })

  it('shows degraded when the API reports the database is unreachable', async () => {
    mockHealth({ status: 'degraded', database: 'unreachable', version: '0.1.0' })

    render(<ApiStatus />)
    await screen.findByText('degraded')

    expect(definitionValues()).toEqual(['degraded', 'unreachable', '0.1.0'])
  })

  it('distinguishes an unreachable API from a degraded one', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('Failed to fetch'))

    render(<ApiStatus />)

    expect(await screen.findByText('API unreachable')).toBeInTheDocument()
    // Not the same message as a degraded database, which is the whole point.
    expect(screen.queryByText('degraded')).not.toBeInTheDocument()
  })

  it('reports a timeout as its own message, not a generic failure', async () => {
    // What AbortSignal.timeout actually throws. Its own message says only
    // that the operation was aborted, which is why api.js rewrites it.
    globalThis.fetch = vi
      .fn()
      .mockRejectedValue(
        new DOMException('The operation was aborted due to timeout', 'TimeoutError'),
      )

    render(<ApiStatus />)

    expect(await screen.findByText('API unreachable')).toBeInTheDocument()
    // Names the request. Since Phase 8a the page makes two - /health and
    // /network - and an unreachable API times out both, so a match on
    // "timed out after 5000ms" alone now finds two elements. Being specific
    // is the fix; loosening the query to getAllByText would assert that
    // something somewhere timed out, which is not what this is checking.
    expect(screen.getByText('GET /health timed out after 5000ms')).toBeInTheDocument()
  })

  it('requests health from the configured API base URL, with a timeout', async () => {
    mockHealth({ status: 'ok', database: 'ok', version: '0.1.0' })

    render(<ApiStatus />)
    await screen.findByText('0.1.0')

    // The URL comes from VITE_API_URL, not from a literal in a component.
    // The signal is asserted because a fetch without one waits forever.
    expect(globalThis.fetch).toHaveBeenCalledWith(
      `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/health`,
      expect.objectContaining({ signal: expect.anything() }),
    )
  })
})
