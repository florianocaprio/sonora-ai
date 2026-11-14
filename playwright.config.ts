import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  workers: 1,
  timeout: 180_000,
  expect: { timeout: 12_000 },
  use: { baseURL: process.env.SONORA_E2E_URL ?? 'http://127.0.0.1:8765', viewport: { width: 1440, height: 1050 } },
})
