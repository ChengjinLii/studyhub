export interface ApiErrorEnvelope {
  msg?: string | null;
  code?: string | null;
  error?: {
    code?: string | null;
    message?: string | null;
  } | null;
}

const isApiErrorEnvelope = (payload: unknown): payload is ApiErrorEnvelope =>
  Boolean(payload) && typeof payload === 'object';

export const extractErrorMessage = (payload: unknown, fallback: string) => {
  if (!payload) return fallback;
  if (typeof payload === 'string') return payload;
  if (!isApiErrorEnvelope(payload)) return fallback;
  if (typeof payload.error?.message === 'string' && payload.error.message) {
    return payload.error.message;
  }
  if (typeof payload.msg === 'string' && payload.msg) {
    return payload.msg;
  }
  return fallback;
};

export const extractErrorCode = (payload: unknown) => {
  if (!isApiErrorEnvelope(payload)) return null;
  if (typeof payload.error?.code === 'string' && payload.error.code) {
    return payload.error.code;
  }
  if (typeof payload.code === 'string' && payload.code) {
    return payload.code;
  }
  return null;
};

export const toErrorMessage = (error: unknown, fallback: string) =>
  error instanceof Error && error.message ? error.message : fallback;
