import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, webApiFetch } from '../../lib/apiTransport';

const response = (data: unknown) => new Response(JSON.stringify({ ok: true, data }), {
  headers: { 'content-type': 'application/json' },
});

describe('API transport policies', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('preserves server URL, bearer precedence, headers and no-store policy', async () => {
    vi.stubEnv('API_BASE_INTERNAL', 'http://backend.test/api');
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => response({ id: 1 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(apiFetch('/me', {
      headers: { Accept: 'custom/type', Authorization: 'old', 'X-Test': 'yes' },
      cache: 'force-cache',
    }, 'current-token')).resolves.toEqual({ id: 1 });
    expect(fetchMock).toHaveBeenCalledWith('http://backend.test/api/me', expect.objectContaining({
      headers: { Accept: 'custom/type', Authorization: 'Bearer current-token', 'X-Test': 'yes' },
      cache: 'no-store',
    }));
    expect(fetchMock.mock.calls[0][1]).not.toHaveProperty('credentials');
  });

  it('coalesces anonymous reads but never caches authenticated reads', async () => {
    vi.stubEnv('API_BASE_INTERNAL', 'http://transport-cache.test/api');
    const fetchMock = vi.fn(async () => response({ items: [1] }));
    vi.stubGlobal('fetch', fetchMock);
    const [first, second] = await Promise.all([apiFetch('/materials'), apiFetch('/materials')]);
    expect(first).toEqual(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await apiFetch('/materials', {}, 'user-one');
    await apiFetch('/materials', {}, 'user-two');
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('forwards cancellation and removes listeners and timers after failed reads', async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const remove = vi.spyOn(controller.signal, 'removeEventListener');
    const fetchMock = vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    vi.stubGlobal('fetch', fetchMock);
    const result = expect(apiFetch('/me', { signal: controller.signal }, 'token')).rejects.toMatchObject({ name: 'AbortError' });
    controller.abort();
    await result;
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
    expect(vi.getTimerCount()).toBe(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not impose a read deadline or replace the signal on mutations', async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const fetchMock = vi.fn(async () => {
      expect(vi.getTimerCount()).toBe(0);
      return response({ saved: true });
    });
    vi.stubGlobal('fetch', fetchMock);
    await apiFetch('/comments', { method: 'POST', body: 'payload', signal: controller.signal }, 'token');
    expect(fetchMock).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
      method: 'POST', body: 'payload', signal: controller.signal,
    }));
  });

  it.each(['include', 'omit'] as const)('keeps browser credentials %s and caller signal without server deadlines', async (credentials) => {
    vi.useFakeTimers();
    vi.stubEnv('API_BASE_INTERNAL', 'http://browser-request.test/api');
    const controller = new AbortController();
    const fetchMock = vi.fn(async () => response({ success: true }));
    vi.stubGlobal('fetch', fetchMock);
    await webApiFetch('/api/comments', {
      method: 'POST', signal: controller.signal,
      ...(credentials === 'omit' ? { credentials } : {}),
    });
    expect(fetchMock).toHaveBeenCalledWith('http://browser-request.test/api/comments', {
      method: 'POST', signal: controller.signal, credentials,
      headers: { Accept: 'application/json' },
    });
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([apiFetch, webApiFetch])('keeps API errors and does not retry writes', async (request) => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      ok: false, error: { code: 'CONFLICT', message: 'Conflict' },
    }), { status: 409 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(request('/comments', { method: 'POST' })).rejects.toMatchObject({
      status: 409, code: 'CONFLICT',
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
