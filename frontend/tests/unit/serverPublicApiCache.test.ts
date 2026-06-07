import { describe, expect, it } from 'vitest';
import {
  readServerPublicApiCache,
  shouldUseServerPublicApiCache,
  writeServerPublicApiCache,
} from '../../lib/serverPublicApiCache';

describe('serverPublicApiCache', () => {
  it('only allows anonymous server-side GET requests', () => {
    expect(shouldUseServerPublicApiCache('/materials', {}, undefined)).toBe(true);
    expect(shouldUseServerPublicApiCache('/materials', {}, 'token')).toBe(false);
    expect(shouldUseServerPublicApiCache('/materials', { method: 'POST' }, undefined)).toBe(false);
    expect(shouldUseServerPublicApiCache('/materials', { body: 'payload' }, undefined)).toBe(false);
    expect(shouldUseServerPublicApiCache('https://example.test/materials', {}, undefined)).toBe(false);
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
