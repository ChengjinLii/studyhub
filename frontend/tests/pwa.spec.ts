import { expect, test } from '@playwright/test';

test.describe('mobile PWA', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36' });

  test('native install, cancellation and manual fallback', async ({ page }) => {
    await page.goto('/more');
    const button = page.getByRole('button', { name: '安装 StudyHub', exact: true });
    await expect(button).toBeVisible();
    await page.evaluate(() => {
      const event = new Event('beforeinstallprompt', { cancelable: true });
      Object.assign(event, { prompt: () => { document.body.dataset.installCalls = '1'; return Promise.resolve(); }, userChoice: Promise.resolve({ outcome: 'dismissed', platform: 'web' }) });
      window.dispatchEvent(event);
    });
    await button.click();
    await expect(page.locator('body')).toHaveAttribute('data-install-calls', '1');
    await expect(button).toBeEnabled();
    await button.click();
    await expect(page.getByRole('dialog')).toContainText('安装应用');
    await page.getByRole('button', { name: '关闭安装指引' }).click();
    await page.evaluate(() => window.dispatchEvent(new Event('appinstalled')));
    await expect(button).toHaveCount(0);
  });

  test('install entry clears the navigation and Bot, and hides during text entry', async ({ page }, testInfo) => {
    await page.goto('/more');
    const button = page.getByRole('button', { name: '安装 StudyHub', exact: true });
    await expect(button).toBeVisible();
    await expect(page.locator('.floating-sidebar__bubble')).toBeVisible();
    await expect.poll(async () => page.evaluate(() => {
      const install = document.querySelector('[data-pwa-install]')!.getBoundingClientRect();
      const bot = document.querySelector('.floating-sidebar__bubble')!.getBoundingClientRect();
      const nav = document.querySelector('.mobile-bottom-nav')!.getBoundingClientRect();
      return install.bottom <= nav.top && bot.bottom < install.top;
    })).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('mobile-install-entry.png') });
    await page.evaluate(() => { const input = document.createElement('input'); input.id = 'keyboard-test'; document.body.append(input); input.focus(); });
    await expect(button).toHaveCount(0);
    await page.locator('#keyboard-test').blur();
    await expect(button).toBeVisible();
  });

  test('accepted native prompt is single-use and stays hidden after resize', async ({ page }) => {
    await page.goto('/more');
    await expect(page.locator('[data-pwa-install]')).toBeVisible();
    await page.evaluate(() => {
      const event = new Event('beforeinstallprompt', { cancelable: true });
      Object.assign(event, {
        prompt: () => { document.body.dataset.installCalls = String(Number(document.body.dataset.installCalls || 0) + 1); return Promise.resolve(); },
        userChoice: new Promise(resolve => window.addEventListener('test:accept', () => resolve({ outcome: 'accepted', platform: 'web' }), { once: true })),
      });
      window.dispatchEvent(event);
    });
    await page.locator('[data-pwa-install]').click();
    await expect(page.locator('[data-pwa-install]')).toBeDisabled();
    await page.evaluate(() => { (document.querySelector('[data-pwa-install]') as HTMLButtonElement).click(); window.dispatchEvent(new Event('test:accept')); });
    await expect(page.locator('[data-pwa-install]')).toHaveCount(0);
    await page.setViewportSize({ width: 412, height: 844 });
    await expect(page.locator('[data-pwa-install]')).toHaveCount(0);
    await expect(page.locator('body')).toHaveAttribute('data-install-calls', '1');
  });

  test('embedded browsers are guided to the system browser', async ({ page }) => {
    await page.addInitScript(() => Object.defineProperty(navigator, 'userAgent', { value: 'Android MicroMessenger/8.0' }));
    await page.goto('/more');
    await page.locator('[data-pwa-install]').click();
    await expect(page.getByRole('dialog')).toContainText('系统浏览器');
  });

  test('failed native installation offers an accessible guide', async ({ page }) => {
    await page.goto('/more');
    await expect(page.locator('[data-pwa-install]')).toBeVisible();
    await page.evaluate(() => {
      const event = new Event('beforeinstallprompt', { cancelable: true });
      Object.assign(event, { prompt: () => Promise.reject(new Error('not allowed')), userChoice: Promise.resolve({ outcome: 'dismissed' }) });
      window.dispatchEvent(event);
    });
    await page.locator('[data-pwa-install]').click();
    await expect(page.getByRole('dialog')).toContainText('安装窗口未能打开');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.locator('[data-pwa-install]')).toBeFocused();
  });

  test('standalone launch has no install control', async ({ page }) => {
    await page.addInitScript(() => Object.defineProperty(navigator, 'standalone', { value: true }));
    await page.goto('/more');
    await expect(page.getByRole('heading', { name: '其他功能', exact: true })).toBeVisible();
    await expect(page.locator('[data-pwa-install]')).toHaveCount(0);
  });

  test('worker installs an offline page without caching business responses', async ({ page, context }) => {
    await page.goto('/more');
    await page.evaluate(async () => { await navigator.serviceWorker.register('/sw.js'); await navigator.serviceWorker.ready; });
    await page.reload();
    await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
    await page.evaluate(async () => { await fetch('/api/healthz').catch(() => {}); });
    const paths = await page.evaluate(async () => {
      const cache = await caches.open('studyhub-static-v4');
      return (await cache.keys()).map(request => new URL(request.url).pathname);
    });
    expect(paths).toContain('/offline.html');
    expect(paths.some(path => path.startsWith('/api/') || path === '/more')).toBe(false);
    await context.setOffline(true);
    await page.goto('/materials');
    await expect(page.getByRole('heading', { name: '暂时无法连接 StudyHub' })).toBeVisible();
    await context.setOffline(false);
    await page.goto('/more');
    await expect(page.getByRole('heading', { name: '其他功能', exact: true })).toBeVisible();
  });
});

test.describe('iPhone PWA guidance', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1' });
  test('shows Safari instructions instead of a fake download', async ({ page }, testInfo) => {
    await page.goto('/more');
    await page.locator('[data-pwa-install]').click();
    await expect(page.getByRole('dialog')).toContainText('分享');
    await expect(page.getByRole('dialog')).toContainText('添加到主屏幕');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('iphone-install-guide.png') });
  });
});

test('desktop keeps browser-native installation', async ({ page }) => {
  await page.goto('/more');
  await expect(page.getByRole('heading', { name: '其他功能', exact: true })).toBeVisible();
  await expect(page.locator('[data-pwa-install]')).toHaveCount(0);
});
