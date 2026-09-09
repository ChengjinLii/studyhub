import { describe, expect, it, vi } from 'vitest';
import {
  readServerPublicApiCache,
  shouldUseServerPublicApiCache,
  writeServerPublicApiCache,
  loadServerPublicApiCache,
} from '../../lib/serverPublicApiCache';

describe('serverPublicApiCache', () => {
  it('only allows anonymous server-side GET requests', () => {
    expect(shouldUseServerPublicApiCache('/materials', {}, undefined)).toBe(true);
    expect(shouldUseServerPublicApiCache('/materials', {}, 'token')).toBe(false);
    expect(shouldUseServerPublicApiCache('/materials', { headers: { Authorization: 'Bearer test' } })).toBe(false);
    expect(shouldUseServerPublicApiCache('/materials', { headers: { Cookie: 'session=test' } })).toBe(false);
    expect(shouldUseServerPublicApiCache('/materials', { signal: new AbortController().signal })).toBe(false);
    expect(shouldUseServerPublicApiCache('/materials', { method: 'POST' }, undefined)).toBe(false);
    expect(shouldUseServerPublicApiCache('/materials', { body: 'payload' }, undefined)).toBe(false);
    expect(shouldUseServerPublicApiCache('https://example.test/materials', {}, undefined)).toBe(false);
  });

  it('coalesces cold loads and gives each caller its own value', async () => {
    const loader = vi.fn(async () => ({ items: [1] }));
    const values = await Promise.all(Array.from({ length: 5 }, () => loadServerPublicApiCache('cold-test', loader)));
    expect(loader).toHaveBeenCalledTimes(1);
    values[0].items.push(2);
    expect(values[1].items).toEqual([1]);
    expect(readServerPublicApiCache('cold-test')?.value).toEqual({ items: [1] });
  });

  it('releases a failed cold load so the next call can recover', async () => {
    await expect(loadServerPublicApiCache('failed-test', async () => { throw new Error('offline'); })).rejects.toThrow('offline');
    expect(await loadServerPublicApiCache('failed-test', async () => 42)).toBe(42);
  });

  it('clones cached payloads before returning them', () => {
    const key = `unit:${Date.now()}:${Math.random()}`;
    writeServerPublicApiCache(key, { items: [{ id: 1, title: '资料' }] });
    const cached = readServerPublicApiCache<{ items: Array<{ id: number; title: string }> }>(key);
    expect(cached?.state).toBe('fresh');
    expect(cached?.value.items[0]?.title).toBe('资料');
    if (cached) {
      cached.value.items[0].title = 'changed';
    }
    expect(readServerPublicApiCache<{ items: Array<{ id: number; title: string }> }>(key)?.value.items[0]?.title).toBe('资料');
  });
});
