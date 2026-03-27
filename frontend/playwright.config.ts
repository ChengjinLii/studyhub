import { defineConfig } from '@playwright/test';

const baseURL = process.env.SMOKE_BASE_URL || 'http://127.0.0.1:8080';
const hostHeader = process.env.SMOKE_HOST;

export default defineConfig({
  use: {
    baseURL,
    extraHTTPHeaders: hostHeader ? { Host: hostHeader } : undefined,
  },
  timeout: 30000,
  testDir: 'tests',
});
