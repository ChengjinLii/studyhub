import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const readSource = (relativePath: string) =>
  readFileSync(join(process.cwd(), relativePath), 'utf8');

describe('public UX regressions', () => {
  it('keeps netdisk actions clickable so anonymous users can reach login', () => {
    const detail = readSource('pages/materials/[id].tsx');

    expect(detail).not.toContain(
      'disabled={downloading || (material.hasNetdisk && !canViewNetdisk)}'
    );
    expect(detail).toContain('disabled={downloading || securityScanBlocked}');
    expect(detail).not.toContain('disabled={downloading || !canViewNetdisk}');
    expect(detail).toContain('onPrimary: shouldPurchase ? handlePurchase : handleDownload');
    expect(detail).toContain('primaryDisabled: shouldPurchase ? ordering : downloading || !canDownload');
  });

  it('uses one shared session source for global interactive components', () => {
    const app = readSource('pages/_app.tsx');
    const bot = readSource('components/FloatingSidebar.tsx');

    expect(app).toContain('<AppProviders initialUser={initialSessionUser}>');
    expect(app).not.toContain('fetchOptionalSessionUser');
    expect(bot).not.toContain('fetchOptionalSessionUser');
  });

  it('keeps request creation wording consistent', () => {
    const requests = readSource('pages/requests/index.tsx');

    expect(requests).not.toContain('我要购买');
    expect(requests).toContain('暂时没有公开的求购需求');
    expect(requests).toContain('发布求购');
  });
});
