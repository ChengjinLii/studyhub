import { defineConfig } from '@playwright/test';

const baseURL = process.env.SMOKE_BASE_URL || 'http://127.0.0.1:3100';
const hostHeader = process.env.SMOKE_HOST;
const shouldStartLocalServer = !process.env.SMOKE_BASE_URL || /^http:\/\/(127\.0\.0\.1|localhost):3100\/?$/i.test(baseURL);

export default defineConfig({
  use: {
    baseURL,
    extraHTTPHeaders: hostHeader ? { Host: hostHeader } : undefined,
  },
  timeout: 30000,
  testDir: 'tests',
  webServer: shouldStartLocalServer
    ? {
        command: 'npm run dev -- --hostname 127.0.0.1 --port 3100',
        url: `${baseURL.replace(/\/$/, '')}/more`,
        reuseExistingServer: true,
        timeout: 120000,
      }
    : undefined,
});
