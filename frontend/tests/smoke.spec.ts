import { test, expect } from '@playwright/test';

const apiPath = (path: string) => path.startsWith('/') ? path : `/${path}`;

test('health endpoint exposes build info', async ({ request }) => {
  const resp = await request.get(apiPath('/api/healthz'));
  expect(resp.ok()).toBeTruthy();
  const json = await resp.json();
  expect(json).toHaveProperty('ok', true);
  expect(json.data).toHaveProperty('status', 'ok');
  expect(json.data).toHaveProperty('build');
  expect(json.data.build).toHaveProperty('gitSha');
});

test('materials list responds successfully', async ({ request }) => {
  const resp = await request.get(apiPath('/api/materials?page=1&size=12'));
  expect(resp.status()).toBeLessThan(500);
  const json = await resp.json();
  expect(json).toHaveProperty('ok', true);
  expect(Array.isArray(json.data?.items)).toBeTruthy();
});

test('login endpoint reachable', async ({ request }) => {
  const resp = await request.post(apiPath('/api/session'), {
    data: { identifier: 'smoke@test', password: 'invalid', captchaId: 'x', captchaCode: '0000' },
  });
  expect(resp.status()).toBeGreaterThanOrEqual(400);
  expect(resp.status()).toBeLessThan(500);
  const json = await resp.json().catch(() => ({}));
  expect(json).toHaveProperty('ok', false);
});
