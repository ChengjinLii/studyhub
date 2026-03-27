import type { IncomingMessage } from 'http';
import { normalizeMockAssets } from './mockAsset';

const normalizeApiBase = (value: string) => {
  const trimmed = value.replace(/\/+$/, '');
  if (/\/api$/i.test(trimmed)) {
    return trimmed;
  }
  return `${trimmed}/api`;
};

const isLoopbackBase = (value: string) => /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/i.test(value);

export const resolveApiBase = (origin?: string) => {
  const isBrowser = typeof window !== 'undefined';
  const serverBase = process.env.API_BASE_URL;
  const publicBase = process.env.NEXT_PUBLIC_API_BASE;
  if (!isBrowser && serverBase) {
    return normalizeApiBase(serverBase);
  }
  if (publicBase) {
    const normalizedEnv = normalizeApiBase(publicBase);
    if (isBrowser && origin) {
      try {
        const originUrl = new URL(origin);
        const envUrl = new URL(normalizedEnv);
        if (originUrl.protocol === 'https:' && envUrl.protocol === 'http:') {
          return normalizeApiBase(originUrl.origin);
        }
        if (!isLoopbackBase(originUrl.origin) && !isLoopbackBase(envUrl.origin) && originUrl.host !== envUrl.host) {
          return normalizeApiBase(originUrl.origin);
        }
      } catch {
        // ignore invalid origin/env values
      }
    }
    if (isBrowser && origin && !isLoopbackBase(origin) && isLoopbackBase(normalizedEnv)) {
      return normalizeApiBase(origin);
    }
    return normalizedEnv;
  }
  if (serverBase) {
    return normalizeApiBase(serverBase);
  }
  if (origin) {
    if (isLoopbackBase(origin)) {
      const devFallback = process.env.NEXT_PUBLIC_DEV_API_BASE || 'http://localhost:8080/api';
      return normalizeApiBase(devFallback);
    }
    return normalizeApiBase(origin);
  }
  if (isBrowser && window.location?.origin) {
    return normalizeApiBase(window.location.origin);
  }
  if (process.env.VERCEL_URL) {
    return normalizeApiBase(`https://${process.env.VERCEL_URL}`);
  }
  const fallbackOrigin = process.env.NODE_ENV === 'production' ? 'https://study-hub.store' : 'http://localhost:8080';
  return normalizeApiBase(fallbackOrigin);
};

export const getRequestOrigin = (req?: IncomingMessage | null) => {
  if (!req) return undefined;
  const host = req.headers.host;
  if (!host) return undefined;
  const proto = (req.headers['x-forwarded-proto'] as string) || (req.socket?.encrypted ? 'https' : 'http');
  return `${proto}://${host}`;
};

const normalizeApiPath = (path: string) => {
  if (!path) return '';
  const ensured = path.startsWith('/') ? path : `/${path}`;
  if (ensured.startsWith('/api/')) {
    return ensured.slice(4);
  }
  if (ensured === '/api') {
    return '';
  }
  return ensured;
};

const resolveBrowserOrigin = (origin?: string) => {
  if (origin) return origin;
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin;
  }
  return undefined;
};

export const buildBackendUrl = (path: string, origin?: string) => {
  const apiBase = resolveApiBase(resolveBrowserOrigin(origin));
  return `${apiBase}${normalizeApiPath(path)}`;
};

export const fetchBackend = async (path: string, init: RequestInit = {}, origin?: string) => {
  const target = buildBackendUrl(path, origin);
  const isBrowser = typeof window !== 'undefined';
  const headers = {
    Accept: 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  const credentials = init.credentials ?? (isBrowser ? 'include' : undefined);
  const response = await fetch(target, {
    ...init,
    headers,
    credentials,
  });
  return new Proxy(response, {
    get(targetResponse, prop) {
      if (prop === 'json') {
        return async () => normalizeMockAssets(await targetResponse.clone().json());
      }
      const value = Reflect.get(targetResponse, prop, targetResponse);
      return typeof value === 'function' ? value.bind(targetResponse) : value;
    },
  });
};
