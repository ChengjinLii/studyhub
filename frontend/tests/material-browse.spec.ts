import { expect, test, type Page } from '@playwright/test';
import catalogue from '../data/material-subject-catalogue.json';
import type { MaterialListItem } from '../types/material';

const filters = {
  keyword: '', school: '', college: '', major: '', tag: '', gradeValue: '', courseCategory: '',
  price: '', sort: 'downloads', page: '2', size: '24',
};
const publicItems = catalogue.folders.flatMap((folder) => folder.materials);
const materials: MaterialListItem[] = Array.from({ length: 48 }, (_, i) => ({
  id: 9100 + i, title: `通信原理复习资料 ${i + 1}`,
  free: true, price: 0, school: '电子科技大学', uploaderNickname: '测试投稿者', courseCategory: 'GENERAL',
  tags: ['期末真题'], downloadCount: 48 - i,
}));

async function openHomepage(page: Page) {
  const calls: string[] = [];
  const documents: string[] = [];
  page.on('request', (request) => { if (request.isNavigationRequest()) documents.push(request.url()); });
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    let data: unknown = {};
    if (url.pathname === '/api/materials') {
      calls.push(url.search);
      const pageNumber = Number(url.searchParams.get('page') || 1);
      const size = Number(url.searchParams.get('size') || 24);
      const keyword = url.searchParams.get('keyword');
      const items = keyword ? publicItems.filter((item) => item.title.toLowerCase().includes(keyword.toLowerCase())) : materials;
      data = { items: items.slice((pageNumber - 1) * size, pageNumber * size), meta: { page: pageNumber, size, total: items.length } };
    } else if (url.pathname === '/api/leaderboard/contributors') data = [];
    else if (url.pathname.endsWith('/session')) data = { user: null };
    else if (url.pathname.endsWith('/comments')) data = { items: [], meta: { page: 1, size: 10, total: 0 } };
    else if (url.pathname.endsWith('/speech')) data = { enabled: false };
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.route('**/_next/data/**/*.json*', async (route) => {
    const url = new URL(route.request().url());
    const detail = url.pathname.match(/\/materials\/(\d+)/);
    let pageProps: unknown;
    if (detail) {
      const item = [...materials, ...publicItems].find((entry) => entry.id === Number(detail[1]))!;
      pageProps = { user: null, material: { ...item, hasFile: false, hasNetdisk: true, versions: [], reviews: [] } };
    } else {
      pageProps = {
        subjectSearchAliases: { calculus: ['微积分', '高数', 'Calculus'] },
        user: null, materials: materials.slice(24, 48), meta: { page: 2, size: 24, total: 48 }, filters,
        stats: null, tagOptions: ['期末真题'], profileSummary: null, profileMissingFields: [],
        recommendations: [materials[32]], popularMaterials: [], requests: [], requestLeaderboard: [], contributors: [],
      };
    }
    await route.fulfill({ json: { pageProps, __N_SSP: true } });
  });
  await page.goto('/more');
  await page.evaluate(async () => {
    await (window as unknown as { next: { router: { push: (url: string) => Promise<boolean> } } }).next.router.push('/?page=2&sort=downloads');
  });
  await expect(page.getByRole('button', { name: '按资料', exact: true })).toHaveAttribute('aria-pressed', 'true');
  return { calls, documents };
}

test('homepage uses the complete prepared subject catalogue without any catalogue requests', async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const { calls } = await openHomepage(page);
  const library = page.locator('#materials-list');
  await expect(library.locator('.material-card')).toHaveCount(24);
  await expect(library.getByRole('button', { name: '列表', exact: true })).toHaveCount(0);
  await page.route('**/api/materials?*', (route) => { calls.push(route.request().url()); return route.abort(); });
  await library.getByRole('button', { name: '按学科', exact: true }).click();
  const folders = page.getByRole('list', { name: '学科文件夹' });
  await expect(folders.getByRole('button')).toHaveCount(catalogue.folders.length);
  await expect(library).toContainText(`${catalogue.total} 份资料`);
  expect(calls).toHaveLength(0);
  await library.screenshot({ path: info.outputPath('subject-folders-desktop.png') });
  const physics = catalogue.folders.find((folder) => folder.id === 'physics')!;
  await folders.getByRole('button', { name: /^大学物理 \d/ }).click();
  await expect(library.locator('.material-card')).toHaveCount(24);
  await library.getByRole('button', { name: '第 2 页', exact: true }).click();
  await expect(library.locator('.material-card')).toHaveCount(physics.materials.length - 24);
  await page.getByRole('button', { name: '全部学科', exact: true }).click();
  await expect(folders).toBeVisible();
  await library.getByRole('button', { name: '按资料', exact: true }).click();
  await expect(library.locator('.material-card')).toHaveCount(24);
  expect(calls).toHaveLength(0);
});

test('subject folders keep their horizontal layout and animate Fluent artwork', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openHomepage(page);
  await page.getByRole('button', { name: '按学科', exact: true }).click();
  const button = page.getByRole('list', { name: '学科文件夹' }).getByRole('button').first();
  const icon = button.locator('svg[viewBox="0 0 32 32"]').first();
  await expect(icon).toBeVisible();
  const iconBounds = (await icon.boundingBox())!;
  expect((await button.locator('strong').boundingBox())!.x).toBeGreaterThan(iconBounds.x + iconBounds.width);
  const front = icon.locator('path').last();
  const pose = () => front.evaluate((node) => {
    const style = getComputedStyle(node);
    return { outline: style.getPropertyValue('d'), transform: style.transform };
  });
  const closed = await pose();
  const bottom = await front.evaluate((node: SVGPathElement) => {
    const box = node.getBBox();
    return box.y + box.height;
  });
  await button.hover();
  await expect.poll(pose).not.toEqual(closed);
  expect(await icon.evaluate((node) => getComputedStyle(node).transform)).toBe('none');
  expect(await icon.locator('rect').evaluate((node) => getComputedStyle(node).transform)).toBe('none');
  expect(await front.evaluate((node: SVGPathElement) => {
    const box = node.getBBox();
    return box.y + box.height;
  })).toBeCloseTo(bottom, 4);
  await page.mouse.move(0, 0);
  await expect.poll(pose).toEqual(closed);
  await page.keyboard.press('Tab');
  await button.focus();
  await expect(button).toBeFocused();
  await expect.poll(pose).not.toEqual(closed);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect.poll(() => front.evaluate((node) => getComputedStyle(node).transform)).toBe('none');
  expect(await front.evaluate((node) => parseFloat(getComputedStyle(node).transitionDuration))).toBeLessThanOrEqual(0.001);
});

test('homepage filters the prepared catalogue locally after the existing search', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const { calls } = await openHomepage(page);
  const input = page.locator('#keyword');
  await input.fill('ESD');
  await input.press('Enter');
  await expect(page.locator('#materials-list .material-card')).toHaveCount(9);
  expect(calls).toHaveLength(1);
  const related = page.getByRole('list', { name: '相关学科文件夹' });
  await expect(related.getByRole('button')).toHaveCount(1);
  await related.getByRole('button', { name: /电子系统设计/ }).click();
  await expect(page.locator('#materials-list .material-card')).toHaveCount(9);
  await page.getByRole('button', { name: '返回搜索结果', exact: true }).click();
  await expect(related).toBeVisible();
  await page.getByRole('button', { name: '按学科', exact: true }).click();
  const folders = page.getByRole('list', { name: '学科文件夹' });
  await expect(folders.getByRole('button')).toHaveCount(1);
  await folders.getByRole('button', { name: /电子系统设计/ }).click();
  await expect(page.locator('#materials-list .material-card')).toHaveCount(9);
  expect(calls).toHaveLength(1);
});

test('course aliases still show a full folder when no literal material title matches', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const { calls, documents } = await openHomepage(page);
  await page.locator('#keyword').fill('高数');
  await page.locator('#keyword').press('Enter');
  const folder = page.getByRole('list', { name: '相关学科文件夹' }).getByRole('button', { name: /微积分/ });
  await expect(folder).toBeVisible();
  await folder.click();
  const library = page.locator('#materials-list');
  const count = catalogue.folders.find((item) => item.id === 'calculus')!.materials.length;
  await expect(library.locator('.material-card')).toHaveCount(Math.min(24, count));
  expect(calls).toHaveLength(1);
  const card = library.locator('.material-card').first();
  const id = await card.getAttribute('data-material-id');
  await card.scrollIntoViewIfNeeded();
  const top = (await card.boundingBox())!.y;
  await card.locator('.material-card__overlay-link').click();
  await expect(page.locator('#download-card')).toBeVisible();
  await page.goBack();
  await expect(library.getByRole('button', { name: '返回搜索结果', exact: true })).toBeVisible();
  await page.waitForTimeout(1400);
  expect(Math.abs((await library.locator(`[data-material-id="${id}"]`).boundingBox())!.y - top)).toBeLessThan(6);
  await library.getByRole('button', { name: '返回搜索结果', exact: true }).click();
  await expect(folder).toBeVisible();
  await expect(page.locator('#keyword')).toHaveValue('高数');
  expect(calls).toHaveLength(1);
  expect(documents).toHaveLength(1);
});

for (const mode of ['materials', 'subjects'] as const) {
  test(`homepage restores ${mode}, filters and position on browser back without reloading the document`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const { calls, documents } = await openHomepage(page);
    const library = page.locator('#materials-list');
    if (mode === 'subjects') {
      await library.getByRole('button', { name: '按学科', exact: true }).click();
      await page.getByRole('list', { name: '学科文件夹' }).getByRole('button', { name: /^大学物理 \d/ }).click();
      await library.getByRole('button', { name: '第 2 页', exact: true }).click();
    }
    const card = library.locator('.material-card').first();
    const id = await card.getAttribute('data-material-id');
    await card.scrollIntoViewIfNeeded();
    const top = (await card.boundingBox())!.y;
    await card.locator('.material-card__overlay-link').click();
    await expect(page.locator('#download-card')).toBeVisible();
    await expect(page.getByRole('link', { name: '返回资料库', exact: true })).toHaveAttribute('href', '/materials');
    await page.goBack();
    await expect(library.getByRole('button', { name: mode === 'subjects' ? '按学科' : '按资料', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page).toHaveURL(/page=2&sort=downloads/);
    if (mode === 'subjects') await expect(library.getByRole('button', { name: '第 2 页', exact: true })).toHaveAttribute('aria-current', 'page');
    else await expect(library.locator('.material-card')).toHaveCount(24);
    await page.waitForTimeout(1400);
    expect(Math.abs((await library.locator(`[data-material-id="${id}"]`).boundingBox())!.y - top)).toBeLessThan(6);
    expect(calls).toHaveLength(0);
    expect(documents).toHaveLength(1);
  });
}

test('independent material library keeps its original controls', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/**', (route) => route.fulfill({ json: { ok: true, data: { user: null } } }));
  await page.goto('/materials');
  await expect(page.getByRole('button', { name: '紧凑双列显示' })).toBeVisible();
  await expect(page.getByRole('button', { name: '详细单列显示' })).toBeVisible();
  await expect(page.getByRole('button', { name: '按学科', exact: true })).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: '搜索资料' })).toBeVisible();
});
