import { createRequire } from 'node:module';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

type HeaderRule = { source: string; headers: { key: string; value: string }[] };

const require = createRequire(import.meta.url);
const nextConfig = require(join(process.cwd(), 'next.config.js')) as {
  headers: () => Promise<HeaderRule[]>;
};

const headersFor = async (nodeEnv: string) => {
  vi.stubEnv('NODE_ENV', nodeEnv);
  return nextConfig.headers();
};

const staticChunkRule = (rules: HeaderRule[]) =>
  rules.find((rule) => rule.source === '/_next/static/:path*');

// Finding (2026-11-15): the dev server sent `immutable` for /_next/static/*. The browser then kept
// an old webpack.js whose build hash no longer matched, the hot update returned 404, and the
// page reloaded without end.
describe('next.config.js cache headers', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('marks build chunks immutable in production', async () => {
    const rules = await headersFor('production');
    expect(rules[0]?.source).toBe('/_next/static/:path*');
    const rule = staticChunkRule(rules);
    expect(rule?.headers).toEqual([
      { key: 'Cache-Control', value: 'public, max-age=31536000, immutable' },
    ]);
  });

  it('leaves build chunks to the Next default in development', async () => {
    const rules = await headersFor('development');
    expect(staticChunkRule(rules)).toBeUndefined();
    expect(JSON.stringify(rules)).not.toContain('immutable');
  });

  it('keeps the other asset rules in development', async () => {
    const sources = (await headersFor('development')).map((rule) => rule.source);
    expect(sources).toEqual(
      expect.arrayContaining(['/icons/:path*', '/manifest.json', '/sw.js'])
    );
  });
});
