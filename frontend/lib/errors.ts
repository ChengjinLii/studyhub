export const extractErrorMessage = (payload: any, fallback: string) => {
  if (!payload) return fallback;
  if (payload.error?.message) return payload.error.message;
  if (payload.msg) return payload.msg;
  if (typeof payload === 'string') return payload;
  return fallback;
};

export const extractErrorCode = (payload: any) => payload?.error?.code || payload?.code || null;
