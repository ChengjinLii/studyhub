import { fetchBackend } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';

export interface BotSpeechConfig {
  enabled: boolean;
  message: string;
  updatedAt: string | null;
}

export const fetchBotSpeechConfig = async () => {
  const response = await fetchBackend('/bot-speech');
  return unwrapApiResponse<BotSpeechConfig>(response, '加载宠物台词失败');
};

export const updateAdminBotSpeechConfig = async (payload: {
  enabled: boolean;
  message: string;
}) => {
  const response = await fetchBackend('/admin/bot-speech', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<BotSpeechConfig>(response, '保存宠物台词失败');
};
