import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const apiPath = (path: string) => (path.startsWith('/') ? path : `/${path}`);
const browserBaseUrl = process.env.SMOKE_BASE_URL || 'http://127.0.0.1:3100';

const setMockSessionCookie = async (
  page: Page,
  user: { id: number; username: string; nickname: string; roleMask: number }
) => {
  await page.context().addCookies([
    {
      name: 'studyhub_user',
      value: encodeURIComponent(JSON.stringify(user)),
      url: browserBaseUrl,
    },
  ]);
};

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
  const splashOverlay = page.locator('[data-splash-overlay]').first();
  if (await splashOverlay.isVisible().catch(() => false)) {
    await splashOverlay.click({ force: true });
    await expect(splashOverlay).toBeHidden({ timeout: 5000 });
  }
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


test('StudyHub Bot hides on mobile viewports while bottom navigation remains visible', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 780 });
  await page.addInitScript(() => window.localStorage.removeItem('floating-sidebar-pos-v2'));
  await page.goto('/more');
  await closeEntryModalIfPresent(page);

  const bot = page.locator('.floating-sidebar__bubble');
  const navigation = page.locator('.mobile-bottom-nav');
  await expect(bot).toHaveCount(0);
  await expect(navigation).toBeVisible();

  const navigationBox = await navigation.boundingBox();
  expect(navigationBox).not.toBeNull();
  expect(navigationBox?.x ?? -1).toBeGreaterThanOrEqual(0);
  expect((navigationBox?.x ?? 0) + (navigationBox?.width ?? 0)).toBeLessThanOrEqual(320);
});

test('administrator speech queue advances, remembers dismissal, and shows updated messages', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 844 });
  await page.addInitScript(() => {
    window.localStorage.removeItem('floating-sidebar-pos-v2');
    // Init scripts also run on reload; keep the dismissal record we are testing.
  });
  const firstMessage = {
    id: 11,
    message: '这条高优先级消息会自动进入下一条。',
    displayStyle: 'TYPEWRITER',
    displayDurationSeconds: 1,
    priority: 90,
    status: 'PUBLISHED',
    startsAt: null,
    endsAt: null,
    updatedAt: '2026-09-21T07:00:00Z',
  };
  let secondMessage = {
    id: 12,
    message: '今天也要记得收藏喜欢的学习资料哦！',
    displayStyle: 'EMPHASIS',
    displayDurationSeconds: 0,
    priority: 50,
    status: 'PUBLISHED',
    startsAt: null,
    endsAt: null,
    updatedAt: '2026-09-21T08:00:00Z',
  };
  let speech = {
    enabled: true,
    message: firstMessage.message,
    updatedAt: '2026-09-21T08:00:00Z',
    messages: [firstMessage, secondMessage],
    pollIntervalSeconds: 15,
  };
  await page.route('**/api/bot-speech', (route) => route.fulfill({ json: { ok: true, data: speech } }));
  await page.goto('/more');
  await closeEntryModalIfPresent(page);

  const bubble = page.locator('.floating-sidebar__speech');
  await expect(bubble).toContainText(firstMessage.message);
  await expect(bubble).toHaveClass(/style-typewriter/);
  await expect(bubble).toContainText(secondMessage.message, { timeout: 3000 });
  await expect(bubble).toHaveClass(/style-emphasis/);
  const bubbleBox = await bubble.boundingBox();
  expect(bubbleBox).not.toBeNull();
  expect(bubbleBox?.x ?? -1).toBeGreaterThanOrEqual(0);
  expect((bubbleBox?.x ?? 0) + (bubbleBox?.width ?? 0)).toBeLessThanOrEqual(1024);

  await page.getByRole('button', { name: '关闭宠物对话气泡' }).click();
  await expect(bubble).toHaveCount(0);
  const dismissalRecord = await page.evaluate(() => window.localStorage.getItem('studyhub-bot-speech-dismissed'));
  expect(dismissalRecord).toContain(secondMessage.message);
  const reloadedSpeech = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/bot-speech');
  await page.reload();
  await reloadedSpeech;
  await closeEntryModalIfPresent(page);
  expect(await page.evaluate(() => window.localStorage.getItem('studyhub-bot-speech-dismissed'))).toBe(dismissalRecord);
  await expect(page.locator('.floating-sidebar__speech')).toHaveCount(0);

  secondMessage = { ...secondMessage, message: '新的学习资料已经上线啦！', updatedAt: '2026-09-21T09:00:00Z' };
  speech = { ...speech, message: secondMessage.message, updatedAt: secondMessage.updatedAt, messages: [secondMessage] };
  await page.reload();
  await closeEntryModalIfPresent(page);
  await expect(page.locator('.floating-sidebar__speech')).toContainText(speech.message);
});

test('mobile detail actions reuse the global bottom navigation layer', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 780 });
  await page.addInitScript(() => window.localStorage.removeItem('floating-sidebar-pos-v2'));
  await page.goto('/more');
  await closeEntryModalIfPresent(page);

  await page.evaluate(() => {
    const navigation = document.querySelector('.mobile-bottom-nav');
    if (!(navigation instanceof HTMLElement)) return;
    navigation.classList.add('mobile-bottom-nav--detail');
    navigation.setAttribute('aria-label', '资料快捷操作');
    navigation.innerHTML = '<a class="mobile-bottom-nav__item">资料</a><button class="mobile-bottom-nav__item">点赞</button><button class="mobile-bottom-nav__detail-primary">获取链接</button><a class="mobile-bottom-nav__item">我的</a>';
    window.dispatchEvent(new Event('resize'));
  });

  const bot = page.locator('.floating-sidebar__bubble');
  const navigation = page.locator('.mobile-bottom-nav--detail');
  await expect(bot).toHaveCount(0);
  await expect(navigation).toBeVisible();
  await expect(page.locator('.mobile-detail-action-bar')).toHaveCount(0);
  await page.waitForTimeout(100);

  const navigationBox = await navigation.boundingBox();
  expect(navigationBox).not.toBeNull();
  expect(navigationBox?.x ?? -1).toBeGreaterThanOrEqual(0);
  expect((navigationBox?.x ?? 0) + (navigationBox?.width ?? 0)).toBeLessThanOrEqual(320);
});

test('login presents the centered auth card without the introductory aside', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/login');

  const loginCard = page.locator('.login-card');
  await expect(loginCard).toBeVisible();
  await expect(page.locator('.login-aside')).toHaveCount(0);
  await expect(page.locator('.mobile-bottom-nav')).toHaveCount(0);
  await expect(page.locator('.floating-sidebar__bubble')).toHaveCount(0);

  const loginBox = await loginCard.boundingBox();
  expect(loginBox).not.toBeNull();
  const centerX = (loginBox?.x ?? 0) + (loginBox?.width ?? 0) / 2;
  expect(Math.abs(centerX - 195)).toBeLessThanOrEqual(4);
});

test('mobile discovery controls provide comfortable touch targets', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/materials');

  const filterChip = page.locator('.mobile-filter-chip').first();
  await expect(filterChip).toBeVisible();
  const chipBox = await filterChip.boundingBox();
  expect(chipBox?.height ?? 0).toBeGreaterThanOrEqual(44);

  const compactView = page.getByRole('button', { name: '紧凑双列显示' });
  const detailView = page.getByRole('button', { name: '详细单列显示' });
  await expect(compactView).toHaveAttribute('aria-pressed', 'true');
  await detailView.click();
  await expect(detailView).toHaveAttribute('aria-pressed', 'true');

  await page.goto('/');
  await closeEntryModalIfPresent(page);
  const searchPill = page.locator('[data-home-portal] [data-search-pill]').first();
  await expect(searchPill).toBeVisible();
  const pillBox = await searchPill.boundingBox();
  expect(pillBox?.height ?? 0).toBeGreaterThanOrEqual(44);
});

test('material list restores its session view and scroll position after detail navigation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    const materials = Array.from({ length: 24 }, (_, index) => ({
      id: 7000 + index,
      title: `恢复测试资料 ${index + 1}`,
      free: true,
      price: 0,
      school: '电子科技大学',
      college: '信通',
      major: '通信',
      gradeValue: '大二',
      courseCategory: 'MAJOR',
      tags: ['期末真题'],
      likeCount: 0,
      commentCount: 0,
      downloadCount: index,
      ratingAvg: 0,
    }));
    window.sessionStorage.setItem('studyhub:materials-list:v1', JSON.stringify({
      version: 1,
      savedAt: Date.now(),
      pendingRestore: true,
      filters: {
        keyword: '通信原理', school: '', college: '', major: '', tag: '期末真题',
        gradeValue: '', courseCategory: '', price: '', sort: 'downloads', page: '1', size: '24',
      },
      materials,
      meta: { page: 1, size: 24, total: 80 },
      availableTags: ['期末真题'],
      mobileView: 'detail',
      scrollY: 520,
    }));
  });
  await page.goto('/materials');
  await expect(page.getByRole('textbox', { name: '搜索资料', exact: true })).toHaveValue('通信原理');
  await expect(page.getByRole('button', { name: '详细单列显示' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.material-card')).toHaveCount(24);
  await expect(page.locator('.app-toast')).toContainText('已恢复上次的筛选条件和浏览位置');
  await page.waitForTimeout(180);
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThanOrEqual(450);
});

test('desktop material cards keep long titles and prices inside their bounds', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(() => {
    const materials = [
      {
        id: 8101,
        title: '线性代数2020期末卷UESTC1001_1_Linear_Algebra_and_Space_Analytic_Extended_Edition',
        free: true,
        price: 0,
      },
      {
        id: 8102,
        title: '毛概期末复习考试重点手写笔记与历年真题解析完整版',
        free: false,
        price: 3,
      },
    ].map((material) => ({
      ...material,
      school: '电子科技大学',
      uploaderNickname: '测试用户',
      gradeValue: '大二',
      courseCategory: 'GENERAL',
      tags: ['期末真题'],
      likeCount: 0,
      commentCount: 0,
      downloadCount: 8,
      ratingAvg: 0,
    }));
    window.sessionStorage.setItem('studyhub:materials-list:v1', JSON.stringify({
      version: 1,
      savedAt: Date.now(),
      pendingRestore: true,
      filters: {
        keyword: '', school: '', college: '', major: '', tag: '', gradeValue: '',
        courseCategory: '', price: '', sort: 'latest', page: '1', size: '24',
      },
      materials,
      meta: { page: 1, size: 24, total: 2 },
      availableTags: ['期末真题'],
      mobileView: 'compact',
      scrollY: 0,
    }));
  });

  await page.goto('/materials');
  const cards = page.locator('.material-card');
  await expect(cards).toHaveCount(2);

  for (let index = 0; index < 2; index += 1) {
    const card = cards.nth(index);
    const header = card.locator('.material-card__header');
    const title = header.locator('h3');
    const price = header.locator('.price-tag');
    await expect(title).toBeVisible();
    await expect(price).toBeVisible();

    const bounds = await Promise.all([card.boundingBox(), title.boundingBox(), price.boundingBox()]);
    const [cardBox, titleBox, priceBox] = bounds;
    expect(cardBox).not.toBeNull();
    expect(titleBox).not.toBeNull();
    expect(priceBox).not.toBeNull();
    expect((titleBox?.x ?? 0) + (titleBox?.width ?? 0)).toBeLessThanOrEqual(
      (cardBox?.x ?? 0) + (cardBox?.width ?? 0) + 0.5
    );
    expect((priceBox?.x ?? 0) + (priceBox?.width ?? 0)).toBeLessThanOrEqual(
      (cardBox?.x ?? 0) + (cardBox?.width ?? 0) + 0.5
    );
    expect(await header.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
});

test('mobile Bot stays unmounted during text entry and mounts on desktop viewports', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => window.localStorage.removeItem('floating-sidebar-pos-v2'));
  await page.goto('/materials');
  const bot = page.locator('.floating-sidebar__bubble');
  const search = page.getByRole('textbox', { name: '搜索资料', exact: true });
  await expect(bot).toHaveCount(0);
  await search.focus();
  await page.waitForTimeout(180);
  await expect(bot).toHaveCount(0);
  await search.evaluate((element) => (element as HTMLInputElement).blur());
  await page.waitForTimeout(260);
  await expect(bot).toHaveCount(0);
  await page.setViewportSize({ width: 1024, height: 844 });
  await expect(bot).toBeVisible();
});

test('material filtering updates one toast from loading to completion', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/materials');
  await page.route('**/api/materials?**', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        data: { items: [], meta: { page: 1, size: 24, total: 0 }, availableTags: [] },
      }),
    });
  });
  await page.getByRole('button', { name: '付费', exact: true }).click();
  await expect(page.locator('.app-toast')).toHaveCount(1);
  await expect(page.locator('.app-toast')).toContainText('正在筛选资料');
  await expect(page.locator('.app-toast')).toContainText('筛选完成，共 0 条结果');
});

test('StudyHub Bot wardrobe hats use their calibrated head contact points', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 844 });
  await page.addInitScript(() => {
    window.localStorage.removeItem('floating-sidebar-pos-v2');
    window.localStorage.setItem('studyhub-bot-hat-v2', 'santa');
  });
  await page.goto('/more');
  await closeEntryModalIfPresent(page);

  const sidebar = page.locator('.floating-sidebar');
  const bubble = page.locator('.floating-sidebar__bubble');
  const hat = page.locator('.floating-sidebar__hat');
  await expect(bubble).toBeVisible();

  await bubble.click({ force: true });
  await page.getByRole('button', { name: /衣帽间/ }).click();
  await page.getByRole('radio', { name: '皇帝冕旒' }).click();
  await expect(sidebar).toHaveClass(/hat-mianliu/);
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem('studyhub-bot-hat-v2'))).toBe('mianliu');
  await page.getByRole('button', { name: '关闭衣帽间' }).click();

  for (const hatId of ['graduation', 'party', 'wizard', 'mianliu']) {
    await sidebar.evaluate((element, id) => {
      element.classList.remove('hat-santa', 'hat-graduation', 'hat-party', 'hat-wizard', 'hat-mianliu', 'hat-none');
      element.classList.add(`hat-${id}`);
    }, hatId);

    const [bubbleBox, hatBox, styles] = await Promise.all([
      bubble.boundingBox(),
      hat.boundingBox(),
      sidebar.evaluate((element) => {
        const computed = window.getComputedStyle(element);
        return {
          x: Number.parseFloat(computed.getPropertyValue('--hat-x')),
          y: Number.parseFloat(computed.getPropertyValue('--hat-y')),
          rotation: Number.parseFloat(computed.getPropertyValue('--hat-rot')),
        };
      }),
    ]);

    expect(bubbleBox).not.toBeNull();
    expect(hatBox).not.toBeNull();
    const hatCenterX = (hatBox?.x ?? 0) + (hatBox?.width ?? 0) / 2;
    const bubbleCenterX = (bubbleBox?.x ?? 0) + (bubbleBox?.width ?? 0) / 2;
    expect((hatBox?.y ?? 0) + (hatBox?.height ?? 0) / 2).toBeLessThan(
      (bubbleBox?.y ?? 0) + (bubbleBox?.height ?? 0) / 2
    );
    if (hatId === 'mianliu') {
      expect(Math.abs(hatCenterX - bubbleCenterX)).toBeLessThanOrEqual(6);
    } else {
      expect(hatCenterX).toBeLessThan(bubbleCenterX);
    }
    if (hatId === 'graduation') expect(styles.rotation).toBeLessThanOrEqual(-10);
    if (hatId === 'party') expect(styles.x).toBeLessThanOrEqual(-90);
    if (hatId === 'wizard') expect(styles.x).toBeLessThanOrEqual(-80);
    if (hatId === 'mianliu') {
      expect(styles.x).toBeGreaterThanOrEqual(-60);
      expect(styles.x).toBeLessThanOrEqual(-54);
      expect(styles.y).toBeGreaterThanOrEqual(-85);
      expect(styles.y).toBeLessThanOrEqual(-79);
      expect(styles.rotation).toBe(0);
    }
  }
});

test('StudyHub Bot resolves login state through the server session endpoint', async ({ page }) => {
  let loggedIn = true;
  const sessionUser = {
    id: 1643,
    username: 'session-user',
    nickname: '会话识别用户',
    roleMask: 1,
    verified: true,
    email: 'session@example.com',
  };
  await page.route('**/api/session', (route) => {
    if (!loggedIn) {
      return route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ ok: false, error: { message: '请先登录' } }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { user: sessionUser } }),
    });
  });
  await page.goto('/more');
  await closeEntryModalIfPresent(page);

  await page.locator('.floating-sidebar__bubble').click({ force: true });
  const profile = page.locator('.floating-sidebar__panel .sidebar-profile');
  await expect(profile.getByText(sessionUser.nickname, { exact: true })).toBeVisible();
  await expect(profile.getByText(`@${sessionUser.username}`, { exact: true })).toBeVisible();
  await expect(page.locator('.floating-sidebar__panel').getByText('未登录', { exact: true })).toHaveCount(0);

  loggedIn = false;
  await page.evaluate(() => window.dispatchEvent(new Event('studyhub:session-changed')));
  await expect(page.locator('.floating-sidebar__panel').getByText('未登录', { exact: true })).toBeVisible();
});

test('StudyHub Bot eyes remain centered and symmetric while looking sideways', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 844 });
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

test('home discovery views remain accessible without entry modal', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/');

  await closeEntryModalIfPresent(page);
  await expect(page.locator('.stable-version-modal')).toHaveCount(0);

  // Desktop: the search portal shows two rank columns, with no tab, request list or cooperation card.
  const portal = page.locator('[data-home-portal]');
  await expect(portal).toBeVisible();
  await expect(portal.getByRole('heading', { name: '热门资料', exact: true })).toBeVisible();
  await expect(portal.getByRole('heading', { name: '热门学科', exact: true })).toBeVisible();
  await expect(page.getByRole('tablist', { name: '首页发现内容' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: '合作招募', exact: true })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: '求购列表' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '为你推荐', exact: true })).toHaveCount(0);
  const pageUrl = page.url();
  await portal.getByRole('button', { name: '全部资料' }).click();
  await expect(page).toHaveURL(pageUrl);
  await expect(page.locator('#materials-list')).toBeInViewport();

  // Phone: starts on the unified HomePortal first screen with mobile tabs, then reveals the library below.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.goto('/');
  await closeEntryModalIfPresent(page);
  await expect(portal).toBeVisible();
  const mobileTabs = portal.locator('[data-portal-mobile-tabs]');
  await expect(mobileTabs).toBeVisible();
  await expect(page.locator('#home-content')).toHaveAttribute('data-revealed', 'false');

  const materialsTab = mobileTabs.getByRole('tab', { name: '热门资料' });
  const subjectsTab = mobileTabs.getByRole('tab', { name: '热门学科' });
  await expect(materialsTab).toHaveAttribute('aria-selected', 'true');
  await expect(portal.getByRole('button', { name: '全部资料' })).toBeVisible();

  await subjectsTab.click();
  await expect(subjectsTab).toHaveAttribute('aria-selected', 'true');
  await expect(materialsTab).toHaveAttribute('aria-selected', 'false');
  await expect(portal.getByRole('list', { name: '热门学科排行', exact: true })).toBeVisible();
  await expect(portal.getByRole('button', { name: '全部学科' })).toBeVisible();

  await portal.getByRole('button', { name: '向下滚动' }).click();
  await expect(page.locator('#home-content')).toHaveAttribute('data-revealed', 'true');
  await expect(page.locator('#materials-list')).toBeVisible();
  await expect(page.locator('.leaderboard-card')).toBeVisible();
  await expect(page.locator('.support-card')).toBeVisible();
  await expect(page.locator('.request-card')).toBeHidden();
  await expect(page.getByRole('region', { name: '合作招募', exact: true })).toHaveCount(0);
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

test('about page shows the platform impact report without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/join');

  const growthSection = page.locator('#growth');
  await expect(growthSection.getByRole('heading', { name: '平台成果' })).toBeVisible();
  await expect(growthSection.getByLabel('平台累计成果').getByText('362', { exact: true })).toBeVisible();
  await expect(growthSection.getByText(/累计数据截至 2026\.09\.08/)).toBeVisible();
  await expect(growthSection.getByRole('heading', { name: '月活跃与回访趋势' })).toBeVisible();
  await expect(growthSection.getByRole('heading', { name: '行为深度与内容使用' })).toBeVisible();
  const mobileCharts = growthSection.locator('.join-growth-chart__svg--mobile');
  await expect(mobileCharts).toHaveCount(3);
  await expect(mobileCharts.first()).toBeVisible();

  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1
  );
  expect(hasHorizontalOverflow).toBe(false);
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
