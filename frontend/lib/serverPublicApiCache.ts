interface PublicApiCacheEntry<T> {
  expiresAt: number;
  staleUntil: number;
  value: T;
}

const PUBLIC_API_CACHE_TTL_MS = Math.max(
  0,
  Number.parseInt(process.env.STUDYHUB_FRONTEND_PUBLIC_API_CACHE_TTL_MS || '5000', 10) || 0
);
const PUBLIC_API_CACHE_MAX_ENTRIES = Math.max(
  32,
  Number.parseInt(process.env.STUDYHUB_FRONTEND_PUBLIC_API_CACHE_MAX_ENTRIES || '256', 10) || 256
);
const PUBLIC_API_CACHE_STALE_WHILE_REVALIDATE_MS = Math.max(
  0,
  Number.parseInt(process.env.STUDYHUB_FRONTEND_PUBLIC_API_CACHE_STALE_MS || '30000', 10) || 0
);

const publicApiCacheStore = () => {
  const globalStore = globalThis as typeof globalThis & {
    __studyhubPublicApiCache?: Map<string, PublicApiCacheEntry<unknown>>;
  };
  if (!globalStore.__studyhubPublicApiCache) {
    globalStore.__studyhubPublicApiCache = new Map();
  }
  return globalStore.__studyhubPublicApiCache;
};

const publicApiRefreshStore = () => {
  const globalStore = globalThis as typeof globalThis & {
    __studyhubPublicApiCacheRefreshes?: Set<string>;
  };
  if (!globalStore.__studyhubPublicApiCacheRefreshes) {
    globalStore.__studyhubPublicApiCacheRefreshes = new Set();
  }
  return globalStore.__studyhubPublicApiCacheRefreshes;
};

const cloneCacheValue = <T,>(value: T): T => {
  if (typeof structuredClone === 'function') {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
};

export const shouldUseServerPublicApiCache = (path: string, init: RequestInit = {}, token?: string) => {
  if (typeof window !== 'undefined') return false;
  if (token) return false;
  if (PUBLIC_API_CACHE_TTL_MS <= 0) return false;
  const method = (init.method || 'GET').toUpperCase();
  if (method !== 'GET') return false;
  if (init.body) return false;
  return path.startsWith('/');
};

export const readServerPublicApiCache = <T,>(key: string): { state: 'fresh' | 'stale'; value: T } | null => {
  const now = Date.now();
  const cached = publicApiCacheStore().get(key);
  if (!cached) {
    return null;
  }
  if (cached.expiresAt > now) {
    return { state: 'fresh', value: cloneCacheValue(cached.value as T) };
  }
  if (cached.staleUntil > now) {
    return { state: 'stale', value: cloneCacheValue(cached.value as T) };
  }
  if (cached) {
    publicApiCacheStore().delete(key);
  }
  return null;
};

export const refreshServerPublicApiCache = <T,>(key: string, refresh: () => Promise<T>) => {
  const refreshes = publicApiRefreshStore();
  if (refreshes.has(key)) {
    return;
  }
  refreshes.add(key);
  void refresh()
    .then((value) => writeServerPublicApiCache(key, value))
    .catch(() => {
      // Keep stale data until staleUntil; foreground requests can refresh later.
    })
    .finally(() => {
      refreshes.delete(key);
    });
};

export const deleteExpiredServerPublicApiCache = () => {
  const now = Date.now();
  const cache = publicApiCacheStore();
  cache.forEach((entry, entryKey) => {
    if (entry.staleUntil <= now) {
      cache.delete(entryKey);
    }
  });
};

export const pruneServerPublicApiCache = () => {
  deleteExpiredServerPublicApiCache();
  const cache = publicApiCacheStore();
  if (cache.size < PUBLIC_API_CACHE_MAX_ENTRIES) {
    return;
  }
  let firstKey: string | undefined;
  cache.forEach((_entry, entryKey) => {
    if (!firstKey) {
      firstKey = entryKey;
    }
  });
  if (firstKey) {
    cache.delete(firstKey);
  }
};

export const getServerPublicApiCacheTtlMs = () => PUBLIC_API_CACHE_TTL_MS;

export const getServerPublicApiCacheStaleMs = () => PUBLIC_API_CACHE_STALE_WHILE_REVALIDATE_MS;

export const getServerPublicApiCacheMaxEntries = () => PUBLIC_API_CACHE_MAX_ENTRIES;

export const hasServerPublicApiCache = (key: string) => {
  const cached = publicApiCacheStore().get(key);
  if (!cached) {
    return false;
  }
  if (cached.staleUntil <= Date.now()) {
    if (cached) {
      publicApiCacheStore().delete(key);
    }
    return false;
  }
  return true;
};

export const writeServerPublicApiCache = <T,>(key: string, value: T) => {
  const now = Date.now();
  pruneServerPublicApiCache();
  publicApiCacheStore().set(key, {
    expiresAt: now + PUBLIC_API_CACHE_TTL_MS,
    staleUntil: now + PUBLIC_API_CACHE_TTL_MS + PUBLIC_API_CACHE_STALE_WHILE_REVALIDATE_MS,
    value: cloneCacheValue(value),
  });
};
