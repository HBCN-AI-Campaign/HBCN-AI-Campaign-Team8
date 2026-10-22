import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => { cleanup(); localStorage.clear() })
Object.defineProperty(window, 'matchMedia', { writable: true, value: (query: string) => ({
  matches: false, media: query, onchange: null, addListener: vi.fn(), removeListener: vi.fn(),
  addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
}) })
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// jsdom has no pseudo-element layout; Ant Design measures scrollbars via this API.
const computedStyle = window.getComputedStyle
window.getComputedStyle = (element) => {
  const style = computedStyle(element)
  if (!style.borderTopWidth) style.borderTopWidth = '0px'
  if (!style.borderBottomWidth) style.borderBottomWidth = '0px'
  return style
}
