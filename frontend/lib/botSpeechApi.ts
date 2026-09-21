import { fetchBackend } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';

export type BotSpeechStyle = 'STANDARD' | 'EMPHASIS' | 'TYPEWRITER';
export type BotSpeechStatus = 'DRAFT' | 'SCHEDULED' | 'PUBLISHED' | 'EXPIRED' | 'REVOKED';

export interface BotSpeechMessage {
  id: number;
  message: string;
  displayStyle: BotSpeechStyle;
  displayDurationSeconds: number;
  priority: number;
  status: BotSpeechStatus;
  startsAt: string | null;
  endsAt: string | null;
  updatedAt: string | null;
  createdAt?: string | null;
  createdByUserId?: number;
  updatedByUserId?: number;
  revokedAt?: string | null;
  revokedByUserId?: number | null;
}

export interface BotSpeechConfig {
  enabled: boolean;
  message: string;
  updatedAt: string | null;
  messages: BotSpeechMessage[];
  pollIntervalSeconds: number;
}

export interface BotSpeechMessageInput {
  message: string;
  displayStyle: BotSpeechStyle;
  displayDurationSeconds: number;
  priority: number;
  startsAt: string | null;
  endsAt: string | null;
  publish: boolean;
}

export const fetchBotSpeechConfig = async () => {
  const response = await fetchBackend('/bot-speech');
  const config = await unwrapApiResponse<BotSpeechConfig>(response, '加载宠物台词失败');
  if (Array.isArray(config.messages)) return config;
  return {
    ...config,
    pollIntervalSeconds: 15,
    messages: config.enabled && config.message
      ? [{
          id: 0,
          message: config.message,
          displayStyle: 'STANDARD' as const,
          displayDurationSeconds: 0,
          priority: 0,
          status: 'PUBLISHED' as const,
          startsAt: null,
          endsAt: null,
          updatedAt: config.updatedAt,
        }]
      : [],
  };
};

export const fetchAdminBotSpeechMessages = async () => {
  const response = await fetchBackend('/admin/bot-speech/messages');
  return unwrapApiResponse<{ items: BotSpeechMessage[]; total: number }>(response, '加载宠物台词队列失败');
};

export const createAdminBotSpeechMessage = async (payload: BotSpeechMessageInput) => {
  const response = await fetchBackend('/admin/bot-speech/messages', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<BotSpeechMessage>(response, '创建宠物台词失败');
};

export const updateAdminBotSpeechMessage = async (id: number, payload: BotSpeechMessageInput) => {
  const response = await fetchBackend(`/admin/bot-speech/messages/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<BotSpeechMessage>(response, '更新宠物台词失败');
};

export const revokeAdminBotSpeechMessage = async (id: number) => {
  const response = await fetchBackend(`/admin/bot-speech/messages/${id}/revoke`, { method: 'POST' });
  return unwrapApiResponse<BotSpeechMessage>(response, '撤回宠物台词失败');
};
