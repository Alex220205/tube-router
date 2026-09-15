/**
 * Vitest setup, run once before the suite.
 *
 * WHY THIS EXISTS
 *     Registers jest-dom's matchers so assertions can be written against the
 *     DOM as a reader understands it - toBeInTheDocument, toHaveTextContent -
 *     rather than against node properties.
 *
 *     It also stubs the two things in this frontend that reach outside the
 *     process. Neither stub is asserted against by any test, which is the
 *     point: they exist so the suite tests this code rather than a graphics
 *     driver or a running server.
 */

import { vi } from 'vitest'

import '@testing-library/jest-dom/vitest'

// WebSocket is stubbed for the whole suite, and this one is not convenience.
// Node's implementation is real: with the API container running, every App
// test opened an actual connection to ws://localhost:8000/ws/status and the
// run reported an unhandled error from inside undici. A suite that reaches
// the network passes or fails on whether a server happens to be up, which is
// the property tests exist to not have.
//
// useLiveStatus is a subscription and a setState. The socket's real contract
// - the current picture on connect, then every change - is tested backend
// side in test_ws.py, one of those cases against a real Redis.
globalThis.WebSocket = class {
  addEventListener() {}
  removeEventListener() {}
  close() {}
  send() {}
}

// MapLibre is stubbed for the whole suite. It needs WebGL and a canvas, and
// jsdom has neither - so a component that builds a Map cannot be rendered in a
// test at all, and every App test would fail on a library it is not about.
//
// This is not a gap being papered over. There is nothing in TubeMap.jsx a
// jsdom test could check: asserting that addLayer was called with the right
// arguments proves the mock records arguments. The logic worth testing was
// moved into src/lib/ precisely so it could be reached without any of this,
// and that is where it is tested.
//
// Named exports, matching the real module: maplibre-gl v6 has no default
// export at all. The first version of this mock invented one, which made the
// tests pass against a shape that does not exist - `npm run build` is what
// caught it, and is why the build is part of this phase's verification rather
// than an afterthought.
vi.mock('maplibre-gl', () => ({
  Map: class {
    addControl() {}
    on() {}
    once() {}
    remove() {}
    getSource() {}
    addSource() {}
    addLayer() {}
    setPaintProperty() {}
    isStyleLoaded() {
      return false
    }
  },
  NavigationControl: class {},
}))
