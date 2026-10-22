import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], include: ['./tests/**/*.test.ts', './tests/**/*.test.tsx'],
    testTimeout: 30000, restoreMocks: true,
    deps: { optimizer: { client: { enabled: true, include: ['antd', '@ant-design/x'] } } } },
})
