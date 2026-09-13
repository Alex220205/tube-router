/**
 * Vitest setup, run once before the suite.
 *
 * WHY THIS EXISTS
 *     Registers jest-dom's matchers so assertions can be written against the
 *     DOM as a reader understands it — toBeInTheDocument, toHaveTextContent —
 *     rather than against node properties.
 */

import '@testing-library/jest-dom/vitest'
