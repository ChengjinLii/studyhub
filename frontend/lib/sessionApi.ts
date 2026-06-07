import { SessionUser } from '../types/user';
import { fetchBackend } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';

interface SessionPayload {
  user?: SessionUser | null;
}

export const fetchSessionUser = async () => {
  const response = await fetchBackend('/session');
  const data = await unwrapApiResponse<SessionPayload>(response, '读取会话失败');
  return data.user ?? null;
};

export const fetchOptionalSessionUser = async () => {
  try {
    return await fetchSessionUser();
  } catch {
    return null;
  }
};
