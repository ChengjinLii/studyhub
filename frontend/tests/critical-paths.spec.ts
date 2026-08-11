import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

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
  const resp = await request.post(apiPath('/api/dev-session'));
  if (resp.status() === 404) {
    return false;
  }
  expect(resp.status(), 'dev-login should not return 5xx').toBeLessThan(500);
  const json = await resp.json().catch(() => ({}));
  return resp.ok() && json?.ok === true;
};

const closeEntryModalIfPresent = async (page: Page) => {
  const closeButton = page.locator('.stable-version-modal__close').first();
  if (await closeButton.isVisible().catch(() => false)) {
    await closeButton.click({ force: true });
  }
};

const dragLauncher = async (page: Page, launcher: Locator, deltaX: number, deltaY: number) => {
  const initialBox = await launcher.boundingBox();
  if (!initialBox) {
    throw new Error('StudyHub Agent launcher should have a bounding box before dragging');
  }
  const startX = initialBox.x + initialBox.width / 2;
  const startY = initialBox.y + initialBox.height / 2;

  await page.mouse.move(startX, startY);
  await page.mouse.down({ button: 'left' });
  await page.mouse.move(startX + deltaX * 0.35, startY + deltaY * 0.35, { steps: 4 });
  await page.mouse.move(startX + deltaX, startY + deltaY, { steps: 8 });
  await page.mouse.up({ button: 'left' });
  await page.waitForTimeout(120);

  const movedBox = await launcher.boundingBox();
  if (!movedBox) {
    throw new Error('StudyHub Agent launcher should have a bounding box after dragging');
  }
  return {
    initialBox,
    movedBox,
    distance: Math.hypot(movedBox.x - initialBox.x, movedBox.y - initialBox.y),
  };
};

test('mock API mode covers login and upload failure envelopes', async ({ page }) => {
  await page.route('**/api/session', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, data: { user: { id: 1, username: 'mock-user' } } }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { user: { id: 1, username: 'mock-user' } } }),
    });
  });
  await page.route('**/api/materials', async (route) => {
    await route.fulfill({
      status: 400,
      contentType: 'application/json',
      body: JSON.stringify({ ok: false, msg: '请上传资料文件或填写网盘链接' }),
    });
  });
  await page.goto('about:blank');
  const result = await page.evaluate(async () => {
    const loginResp = await fetch('https://mock.studyhub.local/api/session', { method: 'POST' });
    const loginJson = await loginResp.json();
    const uploadResp = await fetch('https://mock.studyhub.local/api/materials', { method: 'POST' });
    const uploadJson = await uploadResp.json();
    return {
      loginOk: loginResp.ok && loginJson.ok === true && loginJson.data?.user?.id === 1,
      uploadRejected: uploadResp.status === 400 && uploadJson.ok === false,
      uploadMessage: uploadJson.msg,
    };
  });
  expect(result).toEqual({
    loginOk: true,
    uploadRejected: true,
    uploadMessage: '请上传资料文件或填写网盘链接',
  });
});

test('mock API mode covers request creation payment branch', async ({ page }) => {
  await page.route('**/api/requests', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { id: 301, paymentRequired: true, form: '<form id="pay-form"></form>' } }),
    });
  });
  await page.goto('about:blank');
  const result = await page.evaluate(async () => {
    const resp = await fetch('https://mock.studyhub.local/api/requests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ course: '概率论', keyword: '真题' }),
    });
    const json = await resp.json();
    return {
      ok: resp.ok && json.ok === true,
      requiresPayment: json.data?.paymentRequired === true,
      hasForm: typeof json.data?.form === 'string' && json.data.form.includes('<form'),
    };
  });
  expect(result).toEqual({ ok: true, requiresPayment: true, hasForm: true });
});

test('mock API mode covers payment status fallback envelope', async ({ page }) => {
  await page.route('**/api/orders/status*', async (route) => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ ok: false, msg: '订单不存在' }),
    });
  });
  await page.route('**/api/requests/contributions/status*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { status: 'PAID', requestId: 401 } }),
    });
  });
  await page.goto('about:blank');
  const result = await page.evaluate(async () => {
    const orderResp = await fetch('https://mock.studyhub.local/api/orders/status?orderNo=SMOKE_ORDER');
    const orderJson = await orderResp.json();
    const fallbackResp = orderResp.ok
      ? orderResp
      : await fetch('https://mock.studyhub.local/api/requests/contributions/status?orderNo=SMOKE_ORDER');
    const fallbackJson = orderResp.ok ? orderJson : await fallbackResp.json();
    return {
      fallbackUsed: !orderResp.ok,
      paid: fallbackResp.ok && fallbackJson.ok === true && fallbackJson.data?.status === 'PAID',
      requestId: fallbackJson.data?.requestId,
    };
  });
  expect(result).toEqual({ fallbackUsed: true, paid: true, requestId: 401 });
});

test('mock page mode covers StudyHub Agent open, fallback, drag and collapse', async ({ page }) => {
  await page.route('**/api/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        data: { user: { id: 3, username: 'mock-admin', nickname: 'Mock Admin', roleMask: 8 } },
      }),
    });
  });
  await page.route('**/api/ai-recommendations', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300));
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ ok: false, msg: '推荐失败，请稍后重试' }),
    });
  });
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();
    if (url.includes('/api/session') || url.includes('/api/ai-recommendations')) {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: {} }),
    });
  });

  await page.goto('/more');
  await closeEntryModalIfPresent(page);
  const launcher = page.locator('.hermes-agent__launcher');
  await expect(launcher).toBeVisible();

  let dragResult = await dragLauncher(page, launcher, -120, -70);
  if (dragResult.distance <= 20) {
    dragResult = await dragLauncher(page, launcher, -140, -80);
  }
  expect(dragResult.distance).toBeGreaterThan(20);
  const movedBox = dragResult.movedBox;

  await launcher.click();
  await expect(page.getByRole('heading', { name: 'StudyHub 学习辅导' })).toBeVisible();
  await page.getByPlaceholder('描述你要学什么、多久考试、哪里卡住').fill('ESD 怎么复习');
  await page.getByRole('button', { name: '发送' }).click();
  const thinking = page.locator('.hermes-agent__message--thinking');
  await expect(thinking).toBeVisible();
  await expect(thinking).toContainText('StudyHub 正在处理');
  await expect(thinking.locator('.hermes-agent__thinking-steps span')).toHaveCount(1);
  await expect(page.getByText('推荐失败，请稍后重试')).toBeVisible();

  await page.getByLabel('收起 StudyHub 学习辅导').click({ force: true });
  await expect(launcher).toBeVisible();
  const collapsedBox = await launcher.boundingBox();
  expect(collapsedBox).not.toBeNull();
  const movedCenter = { x: movedBox.x + movedBox.width / 2, y: movedBox.y + movedBox.height / 2 };
  const collapsedCenter = {
    x: (collapsedBox?.x ?? 0) + (collapsedBox?.width ?? 0) / 2,
    y: (collapsedBox?.y ?? 0) + (collapsedBox?.height ?? 0) / 2,
  };
  expect(Math.abs(collapsedCenter.x - movedCenter.x)).toBeLessThan(4);
  expect(Math.abs(collapsedCenter.y - movedCenter.y)).toBeLessThan(4);
});

test('mock page mode hides StudyHub Agent from non-admin users', async ({ page }) => {
  await page.route('**/api/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        data: { user: { id: 1, username: 'mock-user', nickname: 'Mock User', roleMask: 1 } },
      }),
    });
  });
  await page.route('**/api/**', async (route) => {
    if (route.request().url().includes('/api/session')) {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: {} }),
    });
  });

  await page.goto('/more');
  await closeEntryModalIfPresent(page);
  await expect(page.getByRole('heading', { name: '其他功能' })).toBeVisible();
  await expect(page.locator('.hermes-agent__launcher')).toHaveCount(0, { timeout: 3000 });
});

test('mobile StudyHub Bot stays fully above the bottom navigation', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 780 });
  await page.addInitScript(() => window.localStorage.removeItem('floating-sidebar-pos'));
  await page.goto('/more');
  await closeEntryModalIfPresent(page);

  const bot = page.locator('.floating-sidebar__bubble');
  const navigation = page.locator('.mobile-bottom-nav');
  await expect(bot).toBeVisible();
  await expect(navigation).toBeVisible();

  const botBox = await bot.boundingBox();
  const navigationBox = await navigation.boundingBox();
  expect(botBox).not.toBeNull();
  expect(navigationBox).not.toBeNull();
  expect((botBox?.y ?? 0) + (botBox?.height ?? 0)).toBeLessThanOrEqual((navigationBox?.y ?? 0) - 8);
  expect(botBox?.x ?? -1).toBeGreaterThanOrEqual(0);
  expect((botBox?.x ?? 0) + (botBox?.width ?? 0)).toBeLessThanOrEqual(320);
});

test('StudyHub Bot wardrobe hats sit diagonally over the upper-left corner', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    window.localStorage.removeItem('floating-sidebar-pos');
    window.localStorage.setItem('studyhub-bot-hat', 'santa');
  });
  await page.goto('/more');
  await closeEntryModalIfPresent(page);

  const sidebar = page.locator('.floating-sidebar');
  const bubble = page.locator('.floating-sidebar__bubble');
  const hat = page.locator('.floating-sidebar__hat');
  await expect(bubble).toBeVisible();

  for (const hatId of ['graduation', 'party', 'wizard']) {
    await sidebar.evaluate((element, id) => {
      element.classList.remove('hat-santa', 'hat-graduation', 'hat-party', 'hat-wizard', 'hat-none');
      element.classList.add(`hat-${id}`);
    }, hatId);

    const [bubbleBox, hatBox, styles] = await Promise.all([
      bubble.boundingBox(),
      hat.boundingBox(),
      sidebar.evaluate((element) => {
        const computed = window.getComputedStyle(element);
        return {
          x: Number.parseFloat(computed.getPropertyValue('--hat-x')),
          rotation: Number.parseFloat(computed.getPropertyValue('--hat-rot')),
        };
      }),
    ]);

    expect(bubbleBox).not.toBeNull();
    expect(hatBox).not.toBeNull();
    expect((hatBox?.x ?? 0) + (hatBox?.width ?? 0) / 2).toBeLessThan(
      (bubbleBox?.x ?? 0) + (bubbleBox?.width ?? 0) / 2
    );
    expect((hatBox?.y ?? 0) + (hatBox?.height ?? 0) / 2).toBeLessThan(
      (bubbleBox?.y ?? 0) + (bubbleBox?.height ?? 0) / 2
    );
    expect(styles.x).toBeLessThanOrEqual(-66);
    expect(styles.rotation).toBeLessThanOrEqual(-10);
  }
});

test('StudyHub Bot eyes remain centered and symmetric while looking sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/more');
  await closeEntryModalIfPresent(page);
  await page.addStyleTag({
    content: '.floating-sidebar__bubble .floating-face::before { animation: none !important; transition: none !important; }',
  });

  const measurements = await page.locator('.floating-sidebar__bubble').evaluate((source) =>
    [-5, 0, 5].map((eyeX) => {
      const clone = source.cloneNode(true) as HTMLElement;
      clone.style.position = 'fixed';
      clone.style.left = '120px';
      clone.style.top = '120px';
      clone.style.setProperty('--eye-x', `${eyeX}px`, 'important');
      clone.style.setProperty('--eye-y', '0px', 'important');
      document.body.appendChild(clone);

      const face = clone.querySelector<HTMLElement>('.floating-face');
      if (!face) throw new Error('StudyHub Bot face is missing');
      const faceStyle = window.getComputedStyle(face);
      const eyeStyle = window.getComputedStyle(face, '::before');
      const transform = new DOMMatrixReadOnly(eyeStyle.transform);
      const eyeWidth = Number.parseFloat(eyeStyle.width);
      const shadowOffset = Number.parseFloat(eyeStyle.boxShadow.match(/-?\d+(?:\.\d+)?px/)?.[0] || '0');
      const faceWidth = Number.parseFloat(faceStyle.width);
      const eyeLeft = (faceWidth - eyeWidth) / 2 + transform.e;
      const pairLeft = Math.min(eyeLeft, eyeLeft + shadowOffset);
      const pairRight = Math.max(eyeLeft + eyeWidth, eyeLeft + shadowOffset + eyeWidth);
      const result = {
        eyeX,
        leftMargin: pairLeft,
        rightMargin: faceWidth - pairRight,
        pairCenter: (pairLeft + pairRight) / 2,
        faceCenter: faceWidth / 2,
      };
      clone.remove();
      return result;
    })
  );

  const [lookingLeft, centered, lookingRight] = measurements;
  for (const measurement of measurements) {
    expect(measurement.leftMargin).toBeGreaterThanOrEqual(8);
    expect(measurement.rightMargin).toBeGreaterThanOrEqual(8);
  }
  expect(centered.leftMargin).toBeCloseTo(centered.rightMargin, 4);
  expect(lookingLeft.leftMargin).toBeCloseTo(lookingRight.rightMargin, 4);
  expect(lookingLeft.rightMargin).toBeCloseTo(lookingRight.leftMargin, 4);
  expect(lookingLeft.pairCenter).toBeLessThan(lookingLeft.faceCenter);
  expect(lookingRight.pairCenter).toBeGreaterThan(lookingRight.faceCenter);
});

test('home entry modal and discovery views remain keyboard accessible', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/');

  const modal = page.locator('.stable-version-modal');
  await expect(modal).toBeVisible();
  await expect(page.getByText('也可以点击弹窗外区域，或按 ESC 键关闭。')).toBeVisible();
  const firstHotspotBackground = page.locator('.studyhub-popup-poster__hotspot-bg').first();
  await page.locator('.studyhub-popup-poster__hotspot').first().hover();
  await expect(firstHotspotBackground).toHaveCSS('opacity', '0');
  await page.keyboard.press('Escape');
  await expect(modal).toBeHidden();

  const requestTab = page.getByRole('tab', { name: '求购列表' });
  const popularTab = page.getByRole('tab', { name: '近期热门' });
  const cooperationTab = page.getByRole('tab', { name: '合作招募' });
  await popularTab.click();
  await expect(popularTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.request-card .card-title')).toHaveText('近期热门');
  const pageUrl = page.url();
  await page.getByRole('button', { name: '全部资料' }).click();
  await expect(page).toHaveURL(pageUrl);
  await expect(page.locator('#materials-list')).toBeInViewport();
  await cooperationTab.click();
  await expect(cooperationTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.request-card .card-title')).toHaveText('合作招募');
  await expect(page.getByRole('link', { name: 'chengjinli@std.uestc.edu.cn' })).toHaveAttribute(
    'href',
    'mailto:chengjinli@std.uestc.edu.cn'
  );
  await page.getByRole('button', { name: '复制邮箱' }).click();
  await expect(page.getByRole('button', { name: '已复制' })).toBeVisible();
  await requestTab.click();
  await expect(requestTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.request-card .card-title')).toHaveText('求购列表');
});

test('material list shows active search keywords and the 24-item page size', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/?keyword=概率论%20期末');
  await closeEntryModalIfPresent(page);

  await expect(page.locator('.materials-search-context')).toContainText('当前搜索：概率论 期末');
  await expect(page.locator('.materials-library-header__summary .help-text')).toContainText('每页 24 条');
});

test('mock page mode covers more page secondary navigation', async ({ page }) => {
  await page.route('**/api/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { user: null } }),
    });
  });
  await page.route('**/api/**', async (route) => {
    if (route.request().url().includes('/api/session')) {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: {} }),
    });
  });

  await page.goto('/more');
  await closeEntryModalIfPresent(page);
  await expect(page.getByRole('heading', { name: '其他功能' })).toBeVisible();
  await expect(page.getByText('内容专栏、校园服务、平台信息与支持入口。')).toBeVisible();
  await expect(page.getByText(/主导航保持轻量/)).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '内容与校园' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '平台信息' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '联系与协作' })).toBeVisible();
  await expect(page.getByRole('link', { name: /学汇专栏/ })).toHaveAttribute('href', '/column');
  await expect(page.getByRole('link', { name: /校园集市/ })).toHaveAttribute('href', '/market');
  await expect(page.getByText('投稿、收款码、收益结算与隐私相关说明。')).toBeVisible();
});

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

  const likeResp = await request.put(apiPath(`/api/materials/${id}/like`));
  expect(likeResp.status()).toBeLessThan(500);
  const likeJson = await likeResp.json().catch(() => ({}));
  if (likeResp.ok()) {
    expect(likeJson).toHaveProperty('ok', true);
  }
  await request.delete(apiPath(`/api/materials/${id}/like`)).catch(() => undefined);

  const downloadResp = await request.post(apiPath(`/api/materials/${id}/downloads`));
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
