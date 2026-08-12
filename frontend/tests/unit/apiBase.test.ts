import { afterEach, describe, expect, it, vi } from 'vitest';
import { resolveApiBase } from '../../lib/apiBase';
import { getServerApiBase } from '../../lib/serverApiBase';
import { resolveBackendApiBase } from '../../lib/serverProxy';

const clearApiEnv = () => {
  vi.unstubAllEnvs();
  delete process.env.API_BASE_INTERNAL;
  delete process.env.API_BASE_URL;
  delete process.env.NEXT_PUBLIC_API_BASE;
  delete process.env.NEXT_PUBLIC_DEV_API_BASE;
  delete process.env.VERCEL_URL;
};

describe('api base resolution', () => {
  afterEach(() => {
    clearApiEnv();
    vi.unstubAllGlobals();
  });

  it('uses the internal API base first for server-side calls', () => {
    vi.stubEnv('API_BASE_INTERNAL', 'http://127.0.0.1:8311');
    vi.stubEnv('API_BASE_URL', 'https://study-hub.store/api');
    vi.stubEnv('NEXT_PUBLIC_API_BASE', 'https://study-hub.cn/api');

    expect(resolveApiBase()).toBe('http://127.0.0.1:8311/api');
    expect(getServerApiBase()).toBe('http://127.0.0.1:8311/api');
    expect(resolveBackendApiBase()).toBe('http://127.0.0.1:8311/api');
  });

  it('falls back to the production backend port instead of a fixed public domain during SSR', () => {
    vi.stubEnv('NODE_ENV', 'production');

    expect(resolveApiBase()).toBe('http://127.0.0.1:8311/api');
    expect(getServerApiBase()).toBe('http://127.0.0.1:8311/api');
    expect(resolveBackendApiBase()).toBe('http://127.0.0.1:8311/api');
  });

  it('keeps non-loopback browser origins on the same site when the public API base points elsewhere', () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE', 'https://study-hub.store/api');
    vi.stubGlobal('window', {
      location: {
        origin: 'https://203.0.113.10',
      },
    });

    expect(resolveApiBase('https://203.0.113.10')).toBe('https://203.0.113.10/api');
    vi.stubGlobal('window', {
      location: {
        origin: 'https://study-hub.cn',
      },
    });
    expect(resolveApiBase('https://study-hub.cn')).toBe('https://study-hub.cn/api');
  });
});
