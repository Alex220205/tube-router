/** Vitest setup, run once before the suite. */

import { vi } from 'vitest'

import '@testing-library/jest-dom/vitest'

// WebSocket is stubbed for the whole suite, and this one is not convenience. Node's
// implementation is real: with the API container running, every App test opened an
// actual connection to ws://localhost:8000/ws/status and the run reported an unhandled
// error from inside undici.
globalThis.WebSocket = class {
  addEventListener() {}
  removeEventListener() {}
  close() {}
  send() {}
}

// MapLibre is stubbed for the whole suite. It needs WebGL and a canvas, and jsdom has
// neither - so a component that builds a Map cannot be rendered in a test at all, and
// every App test would fail on a library it is not about.
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
    setLayoutProperty() {}
    isStyleLoaded() {
      return false
    }
  },
  NavigationControl: class {},

  // TubeMap calls this at module scope to tell MapLibre where Vite put the bundled
  // worker. A no-op here: there is no worker in jsdom and nothing to point at.
  setWorkerUrl: () => {},
}))
