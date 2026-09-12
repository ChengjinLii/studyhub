import { resolveApiBase, buildBackendUrl } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';
import {
  readServerPublicApiCache,
  refreshServerPublicApiCache,
  shouldUseServerPublicApiCache,
  loadServerPublicApiCache,
} from './serverPublicApiCache';

// Keep server cache/deadline policy separate from browser cookie requests.
export async function apiFetch<T>(path: string, init: RequestInit = {}, token?: string, origin?: string): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const apiBase = resolveApiBase(origin);
  const cacheKey = `${apiBase}${path}`;
  const requestBackend = async () => {
    const isRead = ['GET', 'HEAD'].includes((init.method || 'GET').toUpperCase());
    const controller = new AbortController();
    const cancel = () => controller.abort();
    if (init.signal?.aborted) controller.abort();
    init.signal?.addEventListener('abort', cancel, { once: true });
    const timer = isRead ? setTimeout(cancel, 15000) : undefined;
    try {
      const res = await fetch(cacheKey, {
        ...init,
        headers,
        cache: 'no-store',
        signal: isRead ? controller.signal : init.signal,
      });
      return await unwrapApiResponse<T>(res, '请求失败');
    } finally {
      if (timer) clearTimeout(timer);
      init.signal?.removeEventListener('abort', cancel);
    }
  };
  if (shouldUseServerPublicApiCache(path, init, token)) {
    const cached = readServerPublicApiCache<T>(cacheKey);
    if (cached) {
      if (cached.state === 'stale') {
        refreshServerPublicApiCache(cacheKey, requestBackend);
      }
      return cached.value;
    }
    return loadServerPublicApiCache(cacheKey, requestBackend);
  }
  return requestBackend();
}

export async function webApiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  const res = await fetch(buildBackendUrl(path), {
    ...init,
    headers,
    credentials: init.credentials ?? 'include',
  });
  return unwrapApiResponse<T>(res, '请求失败');
}
