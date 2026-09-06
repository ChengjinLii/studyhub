import { expect, test, type Page } from '@playwright/test';
import type { MaterialDetail } from '../types/material';
import { RoleMask, type SessionUser } from '../types/user';

const user = { id: 9002, username: 'reader', nickname: '测试读者', roleMask: 1 } as SessionUser;
const material: MaterialDetail = {
  id: 9001,
  uploaderId: 9003,
  uploaderNickname: 'JoeyLam',
  title: '信号与系统五年期末考自制解析（2020-2024）',
  description: '适用于电工和通信两个专业。\n\n包含五年期末试卷与自制解析。',
  school: '电子科技大学',
  major: '电工',
  gradeValue: '大三',
  courseCategory: 'MAJOR',
  free: true,
  price: 0,
  hasFile: false,
  hasNetdisk: true,
  downloadCount: 58,
  likeCount: 1,
  commentCount: 0,
  tags: ['期末真题', '期末答案（自制解析）'],
  versions: [],
  reviews: [],
};

// Inject page data and intercept every browser API request. No writes reach production.
async function openDetail(page: Page, changes: Partial<MaterialDetail> = {}, viewer: SessionUser | null = user) {
  const current = { ...material, ...changes };
  const calls: string[] = [];
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.push(`${route.request().method()} ${path}`);
    let data: unknown = {};
    if (path.endsWith('/session')) data = { user: viewer };
    else if (path.endsWith('/downloads')) data = { url: 'https://example.com/test-material' };
    else if (path.endsWith('/like')) data = 2;
    else if (path.endsWith('/rating')) data = { ratingAvg: 4, ratingCount: 1 };
    else if (path.endsWith('/comments')) data = { items: [], meta: { page: 0, size: 10, total: 0 } };
    else if (path.endsWith('/preview')) data = { status: 'done', images: [], previewPages: 3 };
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.route('**/_next/data/**/materials/**', (route) =>
    route.fulfill({
      json: { pageProps: { material: current, user: viewer }, __N_SSP: true },
    })
  );
  await page.goto('/more');
  await page.evaluate(async () => {
    const next = (window as unknown as { next: { router: { push: (url: string) => Promise<boolean> } } }).next;
    await next.router.push('/materials/9001');
  });
  await expect(page.locator('#download-card h1')).toHaveText(current.title);
  return calls;
}

test('detail preserves free netdisk, rating, like and comment interactions', async ({ page }) => {
  const calls = await openDetail(page);
  await expect(page.getByRole('button', { name: '展示预览', exact: true })).toHaveCount(0);
  const access = page.getByRole('complementary', { name: '资料获取' });
  await expect(access).not.toContainText('购买后');
  await page.locator('.detail-action-download').click();
  await expect(page.locator('.netdisk-access-modal')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.locator('.detail-action-like').click();
  await expect(page.locator('.detail-action-like')).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('radio', { name: '评分 4', exact: true }).click();
  await expect(page.getByText('4.0 / 5 · 1 人评分', { exact: false })).toBeVisible();
  await page.getByRole('tab', { name: '评论 0' }).click();
  await expect(page.locator('#material-comments-panel')).toBeVisible();
  await expect(page.locator('#material-preview-panel')).toBeHidden();
  expect(calls).toContain('POST /api/materials/9001/downloads');
  expect(calls).toContain('PUT /api/materials/9001/rating');
  expect(calls).toContain('PUT /api/materials/9001/like');
});

test('administrator retains paid material access and editing', async ({ page }) => {
  await openDetail(page, { free: false, price: 3 }, { ...user, roleMask: RoleMask.ADMIN });
  await expect(page.locator('.detail-action-order')).toHaveCount(0);
  await expect(page.locator('.detail-action-download')).toBeEnabled();
  await expect(page.locator('.detail-action-edit')).toHaveAttribute('href', '/upload?materialId=9001');
});

test('PDF preview keeps the existing preview request', async ({ page }) => {
  const calls = await openDetail(page, { hasFile: true, hasNetdisk: false, fileType: 'pdf' });
  await page.getByRole('button', { name: '展示预览', exact: true }).click();
  await expect.poll(() => calls.includes('GET /api/materials/9001/preview')).toBe(true);
  await expect(page.getByRole('button', { name: '收起预览', exact: true })).toBeVisible();
});

test('approved material layout screenshots', async ({ page }, testInfo) => {
  await openDetail(page, {
    description:
      '该资料电工和通信两个专业的同学都适用。本人为 2023 级格院通信工程专业学生，信号与系统期末 97 分。\n\n压缩包里是本人在考前做的 10 套往年卷子，涵盖 2020–2024 年电工和通信两个专业的期末考题。不保证全对，但正确率应该可观。',
  });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.screenshot({ path: testInfo.outputPath(`detail-${width}.png`), fullPage: true });
  }
});

test('poster title retains clearance above the diagonal', async ({ page }, testInfo) => {
  await page.route('**/api/**', (route) => route.fulfill({ status: 503, json: { ok: false, msg: 'Isolated layout test' } }));
  await page.goto('/');
  const title = page.locator('.studyhub-popup-poster__title');
  await expect(title).toBeVisible();
  for (const family of ['Arial', 'Helvetica Neue', 'sans-serif']) {
    const clearance = await title.evaluate(async (element, fontFamily) => {
      const text = element as SVGTextElement;
      text.style.fontFamily = fontFamily;
      await document.fonts.ready;
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      text.getBoundingClientRect();
      const end = text.getEndPositionOfChar(text.getNumberOfChars() - 1);
      return 1056 - ((1056 - 660) * end.x) / 2048 - end.y;
    }, family);
    expect(clearance, family).toBeGreaterThan(18);
  }
  await page.screenshot({ path: testInfo.outputPath('poster.png') });
  await page.keyboard.press('Escape');
  await expect(title).toBeHidden();
});

test('anonymous netdisk acquisition still redirects to login', async ({ page }) => {
  await openDetail(page, {}, null);
  await page.locator('.detail-action-download').click();
  await expect(page).toHaveURL(/\/login\?next=/);
});

test('unpaid material uses the existing payment page', async ({ page }) => {
  await openDetail(page, { free: false, price: 3 });
  await expect(page.locator('.detail-action-download')).toHaveCount(0);
  await page.route('**/_next/data/**/pay/**', (route) =>
    route.fulfill({ json: { pageProps: { material: { ...material, free: false, price: 3 }, user }, __N_SSP: true } })
  );
  await page.locator('.detail-action-order').click();
  await expect(page).toHaveURL(/\/pay\/9001/);
});

test('purchased materials retain acquisition without a purchase button', async ({ page }) => {
  await openDetail(page, { free: false, price: 3, purchased: true });
  await expect(page.locator('.detail-action-order')).toHaveCount(0);
  await expect(page.locator('.detail-action-download')).toBeEnabled();
  await expect(page.locator('.detail-action-edit')).toHaveCount(0);
});

test('owner retains editing and download without a purchase button', async ({ page }) => {
  await openDetail(page, { free: false, price: 3, uploaderId: user.id });
  await expect(page.locator('.detail-action-order')).toHaveCount(0);
  await expect(page.locator('.detail-action-download')).toBeEnabled();
  await expect(page.locator('.detail-action-edit')).toHaveAttribute('href', '/upload?materialId=9001');
});

test('security scan still prevents file acquisition', async ({ page }) => {
  await openDetail(page, { hasFile: true, hasNetdisk: false, securityScanStatus: 'SCANNING' });
  await expect(page.locator('.detail-action-download')).toBeDisabled();
  await expect(page.getByText('文件安全检查中', { exact: true })).toBeVisible();
});

test('long titles and filenames fit desktop and mobile detail layouts', async ({ page }) => {
  await openDetail(page, {
    title: '线性代数2020期末卷_' + 'Linear_Algebra_and_Space_Analytic'.repeat(4),
    hasFile: true,
    hasNetdisk: false,
    originalFilename: 'Probability_Theory'.repeat(12) + '.pdf',
    fileType: 'pdf',
  });
  for (const width of [1440, 1024, 768, 760, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const overflow = await page.evaluate(() =>
      [document.documentElement, ...Array.from(document.querySelectorAll('#download-card, #download-card h1, #download-card aside'))]
        .filter((el) => el.scrollWidth > el.clientWidth + 1)
        .map((el) => el.tagName)
    );
    expect(overflow, `horizontal overflow at ${width}px`).toEqual([]);
  }
  await expect(page.locator('.mobile-bottom-nav--detail')).toBeVisible();
  await page.getByRole('tab', { name: '资料预览' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: '评论 0' })).toBeFocused();
  await expect(page.locator('#material-comments-panel')).toBeVisible();
});
