import { MarketItemDetail, MarketListResponse } from '../types/market';
import { unwrapApiResponse } from './apiEnvelope';
import { resolveApiBase } from './apiBase';

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
  const res = await fetch(`${apiBase}${path}`, { headers, cache: 'no-store' });
  return unwrapApiResponse<T>(res, '请求失败');
}

export async function fetchMarketItems(
  params: { page?: number; keyword?: string; category?: string },
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
