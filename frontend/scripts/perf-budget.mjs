#!/usr/bin/env node
import process from 'node:process';
import { chromium } from '@playwright/test';

const DEFAULT_ROUTES = ['/', '/more', '/column', '/market', '/login', '/join', '/identity-info'];
const METRIC_KEYS = new Set(['ttfbMs', 'responseEndMs', 'domContentLoadedMs', 'loadMs']);

const splitList = (value) =>
  (value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

const parsePositiveInt = (value, fallback) => {
  const parsed = Number.parseInt(String(value || ''), 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
};

const round = (value) => (typeof value === 'number' && Number.isFinite(value) ? Math.round(value * 10) / 10 : null);
const percentile = (values, p) => {
  const sorted = values.filter((value) => typeof value === 'number' && Number.isFinite(value)).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  const index = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[index];
};

const baseURL = (process.env.PERF_BASE_URL || process.env.SMOKE_BASE_URL || 'http://127.0.0.1:3100').replace(/\/+$/, '');
const routes = splitList(process.env.PERF_ROUTES);
const dynamicRoutes = splitList(process.env.PERF_DYNAMIC_ROUTES);
const targetRoutes = [...(routes.length > 0 ? routes : DEFAULT_ROUTES), ...dynamicRoutes];
const budgetMs = parsePositiveInt(process.env.PERF_BUDGET_MS, 200);
const warmupRuns = parsePositiveInt(process.env.PERF_WARMUP_RUNS, 1);
const sampleRuns = Math.max(1, parsePositiveInt(process.env.PERF_SAMPLE_RUNS, 3));
const networkIdleTimeoutMs = parsePositiveInt(process.env.PERF_NETWORK_IDLE_TIMEOUT_MS, 1200);
const budgetMetric = METRIC_KEYS.has(process.env.PERF_BUDGET_METRIC || '')
  ? process.env.PERF_BUDGET_METRIC
  : 'domContentLoadedMs';

const toUrl = (route) => {
  if (/^https?:\/\//i.test(route)) return route;
  const normalizedRoute = route.startsWith('/') ? route : `/${route}`;
  return `${baseURL}${normalizedRoute}`;
};

const readMetrics = async (page) =>
  page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0];
    const resources = performance.getEntriesByType('resource');
    const paints = Object.fromEntries(
      performance.getEntriesByType('paint').map((entry) => [entry.name, Math.round(entry.startTime * 10) / 10])
    );
    const resourceTransferSize = resources.reduce((total, entry) => total + (entry.transferSize || 0), 0);
    if (!nav) {
      return {
        ttfbMs: null,
        responseEndMs: null,
        domContentLoadedMs: null,
        loadMs: null,
        firstPaintMs: paints['first-paint'] ?? null,
        firstContentfulPaintMs: paints['first-contentful-paint'] ?? null,
        resourceCount: resources.length,
        transferKb: Math.round((resourceTransferSize / 1024) * 10) / 10,
      };
    }
    return {
      ttfbMs: Math.round((nav.responseStart - nav.requestStart) * 10) / 10,
      responseEndMs: Math.round((nav.responseEnd - nav.startTime) * 10) / 10,
      domContentLoadedMs: Math.round((nav.domContentLoadedEventEnd - nav.startTime) * 10) / 10,
      loadMs: nav.loadEventEnd ? Math.round((nav.loadEventEnd - nav.startTime) * 10) / 10 : null,
      firstPaintMs: paints['first-paint'] ?? null,
      firstContentfulPaintMs: paints['first-contentful-paint'] ?? null,
      resourceCount: resources.length,
      transferKb: Math.round(((nav.transferSize || 0) + resourceTransferSize) / 1024 * 10) / 10,
    };
  });

const runNavigation = async (context, route) => {
  const page = await context.newPage();
  const url = toUrl(route);
  const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  if (!response || response.status() >= 500) {
    throw new Error(`${route} returned ${response ? response.status() : 'no response'}`);
  }
  await page.waitForLoadState('load', { timeout: 5000 }).catch(() => {});
  await page.waitForLoadState('networkidle', { timeout: networkIdleTimeoutMs }).catch(() => {});
  const metrics = await readMetrics(page);
  await page.close();
  return metrics;
};

const summarize = (route, samples) => {
  const metricValues = samples.map((sample) => sample[budgetMetric]).filter((value) => value !== null);
  return {
    route,
    samples: samples.length,
    budgetMetric,
    budgetMs,
    p50Ms: round(percentile(metricValues, 50)),
    p95Ms: round(percentile(metricValues, 95)),
    maxMs: round(Math.max(...metricValues)),
    ttfbP95Ms: round(percentile(samples.map((sample) => sample.ttfbMs), 95)),
    responseEndP95Ms: round(percentile(samples.map((sample) => sample.responseEndMs), 95)),
    loadP95Ms: round(percentile(samples.map((sample) => sample.loadMs), 95)),
    fcpP95Ms: round(percentile(samples.map((sample) => sample.firstContentfulPaintMs), 95)),
    transferKbMax: round(Math.max(...samples.map((sample) => sample.transferKb || 0))),
    resourceCountMax: Math.max(...samples.map((sample) => sample.resourceCount || 0)),
  };
};

const main = async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    serviceWorkers: 'allow',
    viewport: { width: 1366, height: 900 },
  });
  const summaries = [];
  const failures = [];

  try {
    for (const route of targetRoutes) {
      for (let index = 0; index < warmupRuns; index += 1) {
        await runNavigation(context, route);
      }
      const samples = [];
      for (let index = 0; index < sampleRuns; index += 1) {
        samples.push(await runNavigation(context, route));
      }
      const summary = summarize(route, samples);
      summaries.push(summary);
      if (summary.p95Ms === null || summary.p95Ms > budgetMs) {
        failures.push(summary);
      }
    }
  } finally {
    await context.close();
    await browser.close();
  }

  console.table(summaries);
  if (failures.length > 0) {
    console.error(`Performance budget failed: ${failures.length}/${summaries.length} routes exceeded ${budgetMs}ms ${budgetMetric}.`);
    process.exitCode = 1;
    return;
  }
  console.log(`Performance budget passed: ${summaries.length} routes stayed within ${budgetMs}ms ${budgetMetric}.`);
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
