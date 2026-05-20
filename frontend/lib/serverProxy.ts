import type { NextApiRequest, NextApiResponse } from 'next';
import { readSession } from './auth';

const DEFAULT_API_BASE = 'http://127.0.0.1:8111/api';

type CookieAwareHeaders = Headers & {
  getSetCookie?: () => string[];
  raw?: () => Record<string, string[]>;
};

const getHeaderValue = (value?: string | string[]) => {
  if (Array.isArray(value)) {
    return value.join('; ');
  }
  return value || undefined;
};

const getSetCookies = (headers: Headers): string[] => {
  const cookieAwareHeaders = headers as CookieAwareHeaders;
  if (typeof cookieAwareHeaders.getSetCookie === 'function') {
    return cookieAwareHeaders.getSetCookie();
  }
  if (typeof cookieAwareHeaders.raw === 'function') {
    const raw = cookieAwareHeaders.raw();
    if (raw && raw['set-cookie']) {
      return raw['set-cookie'];
    }
  }
  const single = headers.get('set-cookie');
  return single ? [single] : [];
};

export const resolveBackendApiBase = () =>
  process.env.API_BASE_INTERNAL || process.env.NEXT_PUBLIC_API_BASE || DEFAULT_API_BASE;

export const extractQueryString = (req: NextApiRequest) => {
  const url = req.url || '';
  const idx = url.indexOf('?');
  return idx >= 0 ? url.slice(idx) : '';
};

export const buildProxyHeaders = (req: NextApiRequest) => {
  const headers: Record<string, string> = {};
  const accept = getHeaderValue(req.headers.accept);
  headers['Accept'] = accept || 'application/json';

  const authHeader = getHeaderValue(req.headers.authorization);
  if (authHeader) {
    headers['Authorization'] = authHeader;
  } else {
    const session = readSession(req);
    if (session.token) {
      headers['Authorization'] = `Bearer ${session.token}`;
    }
  }

  const cookie = getHeaderValue(req.headers.cookie);
  if (cookie) {
    headers['Cookie'] = cookie;
  }

  const contentType = getHeaderValue(req.headers['content-type']);
  if (contentType) {
    headers['Content-Type'] = contentType;
  }

  return headers;
};

export const readRequestBody = async (req: NextApiRequest) =>
  new Promise<Buffer>((resolve, reject) => {
    const chunks: Uint8Array[] = [];
    req.on('data', (chunk: Buffer | string) => {
      chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', (err) => reject(err));
  });

export const forwardBackendResponse = async (backendResp: Response, res: NextApiResponse) => {
  const cookies = getSetCookies(backendResp.headers);
  if (cookies.length) {
    res.setHeader('Set-Cookie', cookies);
  }
  const contentType = backendResp.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const json = await backendResp.json().catch(() => null);
    if (json !== null) {
      return res.status(backendResp.status).json(json);
    }
  }
  const buffer = Buffer.from(await backendResp.arrayBuffer());
  return res.status(backendResp.status).send(buffer);
};
