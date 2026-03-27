import { MarketItemDetail, MarketListResponse } from '../types/market';
import { extractErrorMessage } from './errors';
import { resolveApiBase } from './apiBase';

type ApiEnvelope<T> = {
  ok: boolean;
  data?: T;
  msg?: string;
  error?: {
    code?: string;
    message?: string;
  };
};

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
  const json: ApiEnvelope<T> = await res.json().catch(() => ({ ok: false }));
  if (!res.ok || !json.ok || !json.data) {
    throw new Error(extractErrorMessage(json, '请求失败'));
  }
  return json.data;
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
