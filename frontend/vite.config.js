/** Vite configuration: dev server, build, and the Vitest environment. */

import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  // MapLibre's worker is created with { type: 'module' }, so the bundle Vite emits for
  // it has to be an ES module. The default is IIFE, which the browser refuses to load
  // as a module worker.
  worker: { format: 'es' },

  plugins: [react(), tailwindcss()],

  server: {
    // Bind all interfaces. Inside a container, binding localhost means the port publish
    // works and the page still never loads.
    host: true,
    port: 5173,
  },

  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.js',
  },
})
