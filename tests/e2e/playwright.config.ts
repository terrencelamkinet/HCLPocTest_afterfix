import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';

export default defineConfig({
  testDir: '.',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 1,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: '../../playwright-report' }],
  ],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      // 唔好寫死開發機絕對路徑（POC snapshot 唔應該 leak 本機 path）
      command: 'npm run dev -- --port 5173',
      cwd: path.resolve(__dirname, '../..'),
      port: 5173,
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
});
