import { defineConfig } from '@playwright/test';

const baseURL = process.env.SMOKE_BASE_URL || 'http://127.0.0.1:3100';
const hostHeader = process.env.SMOKE_HOST;
const serverMode = (process.env.PLAYWRIGHT_SERVER_MODE || process.env.SMOKE_SERVER_MODE || 'dev').trim().toLowerCase();
const useProductionServer = serverMode === 'production' || serverMode === 'prod';
const shouldStartLocalServer = !process.env.SMOKE_BASE_URL || /^http:\/\/(127\.0\.0\.1|localhost):3100\/?$/i.test(baseURL);
const localServerCommand = useProductionServer
  ? 'npm run build && npm run start -- --hostname 127.0.0.1 --port 3100'
  : 'npm run dev -- --hostname 127.0.0.1 --port 3100';

export default defineConfig({
  use: {
    baseURL,
    extraHTTPHeaders: hostHeader ? { Host: hostHeader } : undefined,
  },
  timeout: 30000,
  testDir: 'tests',
  webServer: shouldStartLocalServer
    ? {
        command: localServerCommand,
        url: `${baseURL.replace(/\/$/, '')}/more`,
        reuseExistingServer: true,
        timeout: useProductionServer ? 180000 : 120000,
      }
    : undefined,
});
