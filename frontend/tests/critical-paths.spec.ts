import { expect, test, type APIRequestContext } from '@playwright/test';

const apiPath = (path: string) => (path.startsWith('/') ? path : `/${path}`);

const isSmokeTargetAvailable = async (request: APIRequestContext) => {
  try {
    const resp = await request.get(apiPath('/api/healthz'));
    return resp.status() < 500;
  } catch {
    return false;
  }
};

const tryDevLogin = async (request: APIRequestContext) => {
  const resp = await request.post(apiPath('/api/auth/dev-login'));
  if (resp.status() === 404) {
    return false;
  }
  expect(resp.status(), 'dev-login should not return 5xx').toBeLessThan(500);
  const json = await resp.json().catch(() => ({}));
  return resp.ok() && json?.ok === true;
};

test('login success should make session readable', async ({ request }) => {
  const available = await isSmokeTargetAvailable(request);
  test.skip(!available, 'smoke target is unavailable (SMOKE_BASE_URL is not reachable)');

  const loggedIn = await tryDevLogin(request);
  test.skip(!loggedIn, 'local-dev quick login is disabled on this target');

  const sessionResp = await request.get(apiPath('/api/session'));
  expect(sessionResp.ok()).toBeTruthy();
  const sessionJson = await sessionResp.json();
  expect(sessionJson).toHaveProperty('ok', true);
  expect(sessionJson.data?.user?.id).toBeTruthy();
});

test('upload flow failure branch should return 4xx for invalid file delivery payload', async ({ request }) => {
  const available = await isSmokeTargetAvailable(request);
  test.skip(!available, 'smoke target is unavailable (SMOKE_BASE_URL is not reachable)');

  const loggedIn = await tryDevLogin(request);
  test.skip(!loggedIn, 'local-dev quick login is disabled on this target');

  const payload = {
    title: 'smoke upload invalid',
    description: 'smoke test invalid payload',
    price: 0,
    school: '广州大学',
    deliveryMethod: 'FILE',
  };
  const resp = await request.post(apiPath('/api/materials'), {
    multipart: {
      payload: JSON.stringify(payload),
    },
  });
  expect(resp.status()).toBeGreaterThanOrEqual(400);
  expect(resp.status()).toBeLessThan(500);
  const json = await resp.json().catch(() => ({}));
  expect(json).toHaveProperty('ok', false);
});

test('material detail core endpoints should stay available', async ({ request }) => {
  const available = await isSmokeTargetAvailable(request);
  test.skip(!available, 'smoke target is unavailable (SMOKE_BASE_URL is not reachable)');

  const loggedIn = await tryDevLogin(request);
  test.skip(!loggedIn, 'local-dev quick login is disabled on this target');

  const listResp = await request.get(apiPath('/api/materials?page=1&size=12'));
  expect(listResp.status()).toBeLessThan(500);
  const listJson = await listResp.json();
  expect(listJson).toHaveProperty('ok', true);
  const items = Array.isArray(listJson.data?.items) ? listJson.data.items : [];
  test.skip(items.length === 0, 'no materials found on current environment');

  const id = items[0].id as number;
  const detailResp = await request.get(apiPath(`/api/materials/${id}`));
  expect(detailResp.status()).toBeLessThan(500);
  const detailJson = await detailResp.json();
  expect(detailJson).toHaveProperty('ok', true);
  expect(detailJson.data).toHaveProperty('id', id);

  const viewResp = await request.post(apiPath(`/api/materials/${id}/view`), {
    data: { viewerToken: `smoke-${Date.now()}` },
  });
  expect(viewResp.status()).toBeLessThan(500);
  const viewJson = await viewResp.json();
  expect(viewJson).toHaveProperty('ok', true);

  const commentResp = await request.get(apiPath(`/api/comments?materialId=${id}&page=0&size=10`));
  expect(commentResp.status()).toBeLessThan(500);
  const commentJson = await commentResp.json();
  expect(commentJson).toHaveProperty('ok', true);

  const likeResp = await request.post(apiPath(`/api/materials/${id}/like`));
  expect(likeResp.status()).toBeLessThan(500);
  const likeJson = await likeResp.json().catch(() => ({}));
  if (likeResp.ok()) {
    expect(likeJson).toHaveProperty('ok', true);
  }
  await request.delete(apiPath(`/api/materials/${id}/like`)).catch(() => undefined);

  const downloadResp = await request.get(apiPath(`/api/materials/${id}/download`));
  expect(downloadResp.status()).toBeLessThan(500);
  const downloadJson = await downloadResp.json().catch(() => ({}));
  if (downloadResp.ok()) {
    expect(downloadJson).toHaveProperty('ok', true);
  }
});

test('pay result page should render after auth with orderNo query', async ({ request }) => {
  const available = await isSmokeTargetAvailable(request);
  test.skip(!available, 'smoke target is unavailable (SMOKE_BASE_URL is not reachable)');

  const beforeLoginResp = await request.get(apiPath('/pay/result?orderNo=SMOKE_ORDER_001'));
  if (beforeLoginResp.status() === 404) {
    test.skip(true, 'frontend SSR route is unavailable on this smoke target');
  }
  expect(beforeLoginResp.status()).toBeLessThan(500);

  const loggedIn = await tryDevLogin(request);
  test.skip(!loggedIn, 'local-dev quick login is disabled on this target');

  const resp = await request.get(apiPath('/pay/result?orderNo=SMOKE_ORDER_001'));
  expect(resp.ok()).toBeTruthy();
  const html = await resp.text();
  expect(html).toContain('支付完成，系统确认中');
});
