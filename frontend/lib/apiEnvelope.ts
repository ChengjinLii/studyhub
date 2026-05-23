import { normalizeMockAssets } from './mockAsset';
import { extractErrorCode, extractErrorMessage } from './errors';

export interface ApiEnvelope<T> {
  ok: boolean;
  data?: T;
  msg?: string;
  error?: {
    code?: string;
    message?: string;
  };
  code?: string;
}

export class ApiError extends Error {
  status: number;
  code: string | null;
  payload: unknown;

  constructor(message: string, status: number, code: string | null, payload: unknown) {
    super(code ? `${message}（${code}）` : message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

export const readApiEnvelope = async <T>(response: Response): Promise<ApiEnvelope<T>> => {
  const payload = await response
    .clone()
    .json()
    .catch(() => ({ ok: false }));
  return normalizeMockAssets(payload) as ApiEnvelope<T>;
};

export const unwrapApiResponse = async <T>(
  response: Response,
  fallback: string,
  options: { requireData?: boolean } = {}
): Promise<T> => {
  const { requireData = true } = options;
  const json = await readApiEnvelope<T>(response);
  if (!response.ok || !json.ok || (requireData && json.data == null)) {
    const msg = extractErrorMessage(json, response.statusText || fallback);
    const code = extractErrorCode(json);
    throw new ApiError(msg, response.status, code, json);
  }
  return normalizeMockAssets(json.data) as T;
};

export const ensureApiSuccess = async <T>(response: Response, fallback: string): Promise<ApiEnvelope<T>> => {
  const json = await readApiEnvelope<T>(response);
  if (!response.ok || !json.ok) {
    const msg = extractErrorMessage(json, response.statusText || fallback);
    const code = extractErrorCode(json);
    throw new ApiError(msg, response.status, code, json);
  }
  return json;
};
