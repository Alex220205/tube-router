/**
 * Browser entry point. Mounts React onto the root element.
 *
 * WHY THIS EXISTS
 *     index.html loads exactly this file and nothing else. It is the one
 *     place where the application meets the DOM.
 *
 * NO 2021 EQUIVALENT
 *     Tkinter had no mount step: constructing the window was the application.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
