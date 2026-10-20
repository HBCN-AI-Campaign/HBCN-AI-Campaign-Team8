import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    deps: { optimizer: { web: { enabled: true, include: ['antd', '@ant-design/x'] } } },
    environment: 'jsdom',
    // Real Ant Design X components do CSS/layout work in jsdom; allow for slow CI.
    testTimeout: 30000,
    setupFiles: ['./tests/setup.ts'],
    include: ['./tests/**/*.test.ts', './tests/**/*.test.tsx'],
    restoreMocks: true,
  },
})
