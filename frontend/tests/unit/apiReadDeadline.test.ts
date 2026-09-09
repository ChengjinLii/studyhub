import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchProfile } from '../../lib/api';

describe('API read deadline', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('aborts a stalled authenticated read without retrying it', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    vi.stubGlobal('fetch', fetchMock);
    const result = expect(fetchProfile('test-token')).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(15000);
    await result;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('clears the deadline after a successful read', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      ok: true, data: { id: 1 },
    }), { status: 200, headers: { 'content-type': 'application/json' } })));
    await fetchProfile('test-token');
    expect(vi.getTimerCount()).toBe(0);
  });
});
