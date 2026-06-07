const STATIC_CACHE = 'studyhub-static-v3';
const CACHEABLE_PREFIXES = [
  '/_next/static/',
  '/icons/',
  '/local/',
  '/wechat/',
  '/payments/',
  '/xmas/',
  '/placeholders/',
];
const CACHEABLE_FILES = new Set(['/favicon.png', '/manifest.json']);

const isCacheableStaticRequest = (request) => {
  if (request.method !== 'GET') return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  if (url.pathname === '/sw.js') return false;
  return CACHEABLE_FILES.has(url.pathname) || CACHEABLE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
};

const cacheStaticAsset = async (request) => {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);
  const refresh = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => cached);
  if (cached) {
    return cached;
  }
  return refresh;
};

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith('studyhub-static-') && key !== STATIC_CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (!isCacheableStaticRequest(event.request)) {
    return;
  }
  event.respondWith(cacheStaticAsset(event.request));
});
