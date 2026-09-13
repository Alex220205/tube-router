/**
 * Vite configuration: dev server, build, and the Vitest environment.
 *
 * WHY THIS EXISTS
 *     One file configuring both the build and the test run, because Vitest
 *     reads Vite's config. Anything the app can import, a test can import,
 *     with no second resolver to keep in sync.
 *
 * NO 2021 EQUIVALENT
 *     The old project was a Tkinter desktop window. There was no build step,
 *     no bundler and no browser.
 */

import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],

  server: {
    // Bind all interfaces. Inside a container, binding localhost means the
    // port publish works and the page still never loads.
    host: true,
    port: 5173,
  },

  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.js',
  },
})
