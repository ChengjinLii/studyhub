import { expect, test, type Page } from '@playwright/test';

async function session(page: Page, admin = false) {
  const user = { id: admin ? 3 : 1, username: 'batch-test', nickname: '测试投稿者', roleMask: admin ? 8 : 1 };
  await page.context().addCookies([
    { name: 'studyhub_user', value: encodeURIComponent(JSON.stringify(user)), url: 'http://127.0.0.1:3100' },
    { name: 'studyhub_token', value: 'batch-browser-test', url: 'http://127.0.0.1:3100' },
  ]);
  await page.route('**/api/**', route => route.fulfill({ json: { ok: true, data: { user, items: [], total: 0 } } }));
}

test('batch files retry only failed uploads and show receipt', async ({ page }) => {
  await session(page);
  const items = [{ id: 101, name: 'a.txt', sizeBytes: 5 }, { id: 102, name: 'b.txt', sizeBytes: 5 }];
  const counts = { 101: 0, 102: 0 };
  await page.route('**/api/batch-submissions', async route => {
    const payload = route.request().postDataJSON();
    expect(payload.publicationIntent).toBe('FREE');
    expect(payload.files).toHaveLength(2);
    await route.fulfill({ json: { ok: true, data: { id: 7, items } } });
  });
  await page.route('**/api/batch-submissions/7/items/*/authorize', route => route.fulfill({ json: { ok: true, data: { uploadToken: 'test-only' } } }));
  await page.route('**/api/batch-submissions/7/items/*/file', async route => {
    const id = route.request().url().includes('/101/') ? 101 : 102;
    counts[id] += 1;
    const failed = id === 102 && counts[id] === 1;
    await route.fulfill({ status: failed ? 503 : 200, json: failed ? { ok: false, msg: '暂时不可用' } : { ok: true, data: { id } } });
  });
  await page.route('**/api/batch-submissions/7/submit', route => route.fulfill({ json: { ok: true, data: { id: 7, status: 'WAITING' } } }));
  await page.goto('/upload/batch');
  await page.getByLabel('资料文件', { exact: true }).setInputFiles(items.map(i => ({ name: i.name, mimeType: 'text/plain', buffer: Buffer.from('hello') })));
  await page.getByRole('radio', { name: '免费', exact: true }).check();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: '创建批次并提交' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '部分文件上传失败' })).toBeVisible();
  await page.getByRole('button', { name: '重试未完成步骤' }).click();
  await expect(page.getByRole('heading', { name: '批次 #7 已提交' })).toBeVisible();
  expect(counts).toEqual({ 101: 1, 102: 2 });
});

test('mobile batch form has drag target and no metadata requirements or overflow', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await session(page);
  await page.goto('/upload/batch');
  await expect(page.getByText('选择 / 拖拽 文件', { exact: true })).toBeVisible();
  await page.getByRole('radio', { name: '网盘', exact: true }).check();
  await expect(page.getByLabel('网盘链接', { exact: true })).toBeVisible();
  await expect(page.getByLabel('资料文件', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('batch-mobile.png'), fullPage: true });
});

test('administrator sees private intake and explicit publication form', async ({ page }, testInfo) => {
  await session(page, true);
  const batch = { id: 7, status: 'WAITING', uploaderId: 1, deliveryMethod: 'NETDISK', publicationIntent: 'PAID',
    itemCount: 1, totalBytes: 0, pricingNote: '每份两元', netdiskUrl: 'https://example.com/files', netdiskPassword: '1234',
    items: [{ id: 101, name: '网盘投稿', sizeBytes: 0, status: 'UPLOADED', scanStatus: 'NOT_APPLICABLE' }] };
  await page.route('**/api/admin/batch-submissions?*', route => route.fulfill({ json: { ok: true, data: { items: [batch], total: 1 } } }));
  await page.route('**/api/admin/batch-submissions/7', route => route.fulfill({ json: { ok: true, data: batch } }));
  await page.goto('/admin/batch');
  await page.getByRole('button', { name: '查看批次' }).click();
  await expect(page.getByText('定价说明：每份两元')).toBeVisible();
  await expect(page.getByText('提取码：1234')).toBeVisible();
  await expect(page.getByRole('button', { name: '发布所选条目', exact: true })).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath('batch-admin.png'), fullPage: true });
});
