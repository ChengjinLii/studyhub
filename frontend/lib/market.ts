import { MarketItemDetail, MarketListResponse } from '../types/market';
import { unwrapApiResponse } from './apiEnvelope';
import { resolveApiBase } from './apiBase';
import {
  readServerPublicApiCache,
  refreshServerPublicApiCache,
  shouldUseServerPublicApiCache,
  writeServerPublicApiCache,
} from './serverPublicApiCache';

const buildQuery = (params: Record<string, string | number | undefined>) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `?${qs}` : '';
};

async function apiFetch<T>(path: string, token?: string, origin?: string) {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const apiBase = resolveApiBase(origin);
  const cacheKey = `${apiBase}${path}`;
  const requestBackend = async () => {
    const res = await fetch(cacheKey, { headers, cache: 'no-store' });
    return unwrapApiResponse<T>(res, '请求失败');
  };
  if (shouldUseServerPublicApiCache(path, {}, token)) {
    const cached = readServerPublicApiCache<T>(cacheKey);
    if (cached) {
      if (cached.state === 'stale') {
        refreshServerPublicApiCache(cacheKey, requestBackend);
      }
      return cached.value;
    }
  }
  const data = await requestBackend();
  if (shouldUseServerPublicApiCache(path, {}, token)) {
    writeServerPublicApiCache(cacheKey, data);
  }
  return data;
}

export async function fetchMarketItems(
  params: { page?: number | string; keyword?: string; category?: string },
  origin?: string,
  token?: string
) {
  return apiFetch<MarketListResponse>(`/market${buildQuery(params)}`, token, origin);
}

export async function fetchMarketItemDetail(id: string, token?: string, origin?: string) {
  return apiFetch<MarketItemDetail>(`/market/${id}`, token, origin);
}

export async function createMarketItem(formData: FormData, token: string, origin?: string) {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const apiBase = resolveApiBase(origin);
  const response = await fetch(`${apiBase}/market`, {
    method: 'POST',
    headers,
    body: formData,
  });
  return unwrapApiResponse<MarketItemDetail>(response, '发布失败');
}
