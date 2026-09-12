import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

const source = readFileSync(new URL('../../public/sw.js', import.meta.url), 'utf8');
const origin = 'https://studyhub.test';
function worker() {
  const handlers: Record<string, (event: any) => void> = {};
  const cache = { put: vi.fn().mockResolvedValue(undefined), keys: vi.fn().mockResolvedValue([]), delete: vi.fn(), addAll: vi.fn() };
  const caches = { match: vi.fn().mockResolvedValue(undefined), open: vi.fn().mockResolvedValue(cache), keys: vi.fn().mockResolvedValue([]), delete: vi.fn() };
  const fetch = vi.fn().mockResolvedValue(new Response('network'));
  runInNewContext(source, { self: { location: { origin }, clients: { claim: vi.fn() }, addEventListener: (name, handler) => { handlers[name] = handler; } }, caches, fetch, URL, Response, Set, Promise });
  const request = (path: string, method = 'GET', mode = 'cors', headers = new Headers()) => {
    const event = { request: { url: new URL(path, origin).href, method, mode, headers }, respondWith: vi.fn(), waitUntil: vi.fn() };
    handlers.fetch(event);
    return event;
  };
  return { request, cache, caches, fetch, handlers };
}

describe('PWA network and privacy boundary', () => {
  it.each(['/api/session', '/api/materials/1/download', '/api/pay/alipay/create', '/pay/1', '/mcp', 'https://oss.example/file.pdf', '/materials/1/file.pdf'])('does not intercept protected or third-party resource %s', path => {
    expect(worker().request(path).respondWith).not.toHaveBeenCalled();
  });
  it.each(['POST', 'PUT', 'PATCH', 'DELETE'])('never queues or intercepts %s requests', method => {
    expect(worker().request('/api/materials', method).respondWith).not.toHaveBeenCalled();
  });
  it('does not cache authenticated static requests or query-string tokens', () => {
    const w = worker();
    expect(w.request('/icons/bot-192.png', 'GET', 'cors', new Headers({ authorization: 'Bearer private' })).respondWith).not.toHaveBeenCalled();
    expect(w.request('/icons/bot-192.png?token=private').respondWith).not.toHaveBeenCalled();
  });
  it('serves online navigation directly and never caches its HTML', async () => {
    const w = worker();
    const event = w.request('/me', 'GET', 'navigate');
    expect(await (await event.respondWith.mock.calls[0][0]).text()).toBe('network');
    expect(w.cache.put).not.toHaveBeenCalled();
  });
  it('uses only the neutral offline page when navigation fails', async () => {
    const w = worker();
    w.fetch.mockRejectedValue(new TypeError('offline'));
    w.caches.match.mockResolvedValue(new Response('offline page'));
    const event = w.request('/materials', 'GET', 'navigate');
    expect(await (await event.respondWith.mock.calls[0][0]).text()).toBe('offline page');
    expect(w.caches.match).toHaveBeenCalledWith('/offline.html', { cacheName: 'studyhub-static-v4' });
    expect(w.cache.put).not.toHaveBeenCalled();
  });
  it('does not mask payment navigation failures with an offline success page', () => {
    expect(worker().request('/pay/result?orderNo=private', 'GET', 'navigate').respondWith).not.toHaveBeenCalled();
  });
  it('keeps successful responses working when browser storage fails', async () => {
    const w = worker();
    w.caches.match.mockRejectedValue(new Error('denied'));
    w.caches.open.mockRejectedValue(new Error('quota'));
    const event = w.request('/_next/static/chunk.js');
    expect(await (await event.respondWith.mock.calls[0][0]).text()).toBe('network');
    await event.waitUntil.mock.calls[0][0];
  });
  it('bounds static cache entries and preserves offline assets', async () => {
    const w = worker();
    w.cache.keys.mockResolvedValue(Array.from({ length: 170 }, (_, i) => ({ url: `${origin}/_next/static/${i}.js` })));
    const event = w.request('/_next/static/new.js');
    await event.waitUntil.mock.calls[0][0];
    expect(w.cache.delete).toHaveBeenCalledTimes(10);
  });
});
