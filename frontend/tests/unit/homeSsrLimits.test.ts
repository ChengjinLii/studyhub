import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('home SSR data limits', () => {
  it('keeps homepage request preview bounded', () => {
    const source = readFileSync(join(process.cwd(), 'pages/index.tsx'), 'utf8');

    expect(source).toContain('const HOME_REQUEST_PREVIEW_LIMIT = 8;');
    expect(source).toContain("fetchMaterialRequests(\n    { sort: 'hot', limit: HOME_REQUEST_PREVIEW_LIMIT }");
    expect(source).not.toContain("fetchMaterialRequests(\n    { sort: 'hot', limit: 0 }");
  });

  it('loads a bounded recent-download-sorted list for the switchable discovery card', () => {
    const source = readFileSync(join(process.cwd(), 'pages/index.tsx'), 'utf8');

    expect(source).toContain('const HOME_POPULAR_PREVIEW_LIMIT = 20;');
    expect(source).toContain('const HOME_RECOMMENDATION_LIMIT = 30;');
    expect(source).toContain("{ sort: 'recent_downloads', page: 1, size: HOME_POPULAR_PREVIEW_LIMIT }");
    expect(source).toContain('HOME_RECOMMENDATION_LIMIT');
  });

  it('uses 24 results per page on both material list screens', () => {
    const homeSource = readFileSync(join(process.cwd(), 'pages/index.tsx'), 'utf8');
    const materialsSource = readFileSync(join(process.cwd(), 'pages/materials/index.tsx'), 'utf8');

    expect(homeSource).toContain('const MATERIALS_PAGE_SIZE = 24;');
    expect(materialsSource).toContain('const MATERIALS_PAGE_SIZE = 24;');
    expect(homeSource).toContain('当前搜索：');
    expect(materialsSource).toContain('当前搜索：');
  });
});
