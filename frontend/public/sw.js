/* Business requests are network-only. Never store API, account, payment or file responses. */
const STATIC_CACHE = 'studyhub-static-v4';
const MAX_ENTRIES = 160;
const OFFLINE_PAGE = '/offline.html';
const SHELL_ASSETS = [OFFLINE_PAGE, '/icons/bot-192.png', '/icons/bot-512.png', '/icons/bot-apple-touch-icon.png', '/icons/bot-maskable.png'];
const CACHEABLE_FILES = new Set([...SHELL_ASSETS, '/favicon.png']);

const isCacheableStaticRequest = (request) => {
  if (request.method !== 'GET' || request.headers.has('authorization')) return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.search) return false;
  return CACHEABLE_FILES.has(url.pathname) || url.pathname.startsWith('/_next/static/');
};

const remember = async (request, response) => {
  if (!response.ok || response.redirected || !['basic', 'default'].includes(response.type)) return;
  try {
    const cache = await caches.open(STATIC_CACHE);
    await cache.put(request, response);
    const keys = await cache.keys();
    const removable = keys.filter(key => !SHELL_ASSETS.includes(new URL(key.url).pathname));
    for (const key of removable.slice(0, Math.max(0, keys.length - MAX_ENTRIES))) await cache.delete(key);
  } catch {
    // Storage denial or quota exhaustion must not break a successful network response.
  }
};

const staticAsset = async (request) => {
  let cached;
  try { cached = await caches.match(request, { cacheName: STATIC_CACHE }); } catch { /* Use network. */ }
  if (cached) return { response: cached, save: Promise.resolve() };
  const response = await fetch(request);
  return { response, save: remember(request, response.clone()) };
};

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then(cache => cache.addAll(SHELL_ASSETS)));
  // Do not replace a worker mid-upload or reload open pages during an update.
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(key => key.startsWith('studyhub-static-') && key !== STATIC_CACHE).map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (request.mode === 'navigate' && !/^\/(api|pay|mcp)(\/|$)/.test(url.pathname)) {
    event.respondWith(fetch(request).catch(async () => {
      try {
        const offline = await caches.match(OFFLINE_PAGE, { cacheName: STATIC_CACHE });
        if (offline) return offline;
      } catch { /* No local storage available. */ }
      return new Response('Offline. Please reconnect and reload.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    }));
    return;
  }
  if (isCacheableStaticRequest(request)) {
    const task = staticAsset(request);
    event.respondWith(task.then(result => result.response));
    event.waitUntil(task.then(result => result.save).catch(() => {}));
  }
});
