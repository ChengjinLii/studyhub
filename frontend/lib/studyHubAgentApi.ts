import { MaterialListItem } from '../types/material';
import { buildBackendUrl, fetchBackend } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';
import type { StudyHubAgentImageAttachment } from '../components/studyHubAgent/types';

interface AiRecommendationPayload {
  output?: string | null;
}

type AgentStreamHandlers = {
  onStage?: (stage: string) => void;
  onDelta?: (delta: string) => void;
};

export const requestStudyHubAgentRecommendations = async (
  query: string,
  contextQuery?: string,
  imageAttachments: StudyHubAgentImageAttachment[] = []
) => {
  const body = buildAgentRecommendationBody(query, contextQuery, imageAttachments);
  const response = await fetchBackend('/ai-recommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return unwrapApiResponse<AiRecommendationPayload>(response, 'StudyHub 学习辅导暂时无法连接资料推荐服务');
};

export const requestStudyHubAgentRecommendationsStream = async (
  query: string,
  contextQuery?: string,
  imageAttachments: StudyHubAgentImageAttachment[] = [],
  handlers: AgentStreamHandlers = {}
) => {
  const body = buildAgentRecommendationBody(query, contextQuery, imageAttachments);
  const response = await fetch(buildBackendUrl('/ai-recommendations/stream'), {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    credentials: typeof window !== 'undefined' ? 'include' : undefined,
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    throw new Error('StudyHub 学习辅导暂时无法连接资料推荐服务');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result: AiRecommendationPayload | null = null;

  const dispatch = (rawEvent: string) => {
    const lines = rawEvent.split(/\r?\n/);
    let eventName = 'message';
    const dataLines: string[] = [];
    lines.forEach((line) => {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart());
      }
    });
    if (dataLines.length === 0) return;
    const rawData = dataLines.join('\n');
    let payload: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(rawData);
      if (parsed && typeof parsed === 'object') {
        payload = parsed as Record<string, unknown>;
      }
    } catch {
      payload = { text: rawData };
    }
    if (eventName === 'stage' && typeof payload.stage === 'string') {
      handlers.onStage?.(payload.stage);
    } else if (eventName === 'delta' && typeof payload.delta === 'string') {
      handlers.onDelta?.(payload.delta);
    } else if (eventName === 'result') {
      result = payload as AiRecommendationPayload;
    } else if (eventName === 'error') {
      throw new Error(typeof payload.message === 'string' ? payload.message : '推荐失败，请稍后重试');
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const events = buffer.split(/\n\n/);
    buffer = events.pop() || '';
    events.forEach(dispatch);
    if (done) break;
  }
  if (buffer.trim()) {
    dispatch(buffer);
  }
  if (!result) {
    throw new Error('AI 响应为空，请稍后再试');
  }
  return result;
};

export const fetchStudyHubAgentMaterial = async (materialId: number) => {
  const response = await fetchBackend(`/materials/${materialId}`);
  return unwrapApiResponse<MaterialListItem>(response, '加载资料详情失败');
};

function buildAgentRecommendationBody(
  query: string,
  contextQuery?: string,
  imageAttachments: StudyHubAgentImageAttachment[] = []
) {
  const body: {
    query: string;
    contextQuery?: string;
    imageAttachments?: Array<Pick<StudyHubAgentImageAttachment, 'name' | 'mimeType' | 'dataUrl' | 'sizeBytes'>>;
  } = { query };
  if (contextQuery && contextQuery.trim()) {
    body.contextQuery = contextQuery.trim().slice(-1000);
  }
  const attachments = imageAttachments
    .filter((item) => item.dataUrl)
    .slice(0, 1)
    .map((item) => ({
      name: item.name,
      mimeType: item.mimeType,
      dataUrl: item.dataUrl,
      sizeBytes: item.sizeBytes,
    }));
  if (attachments.length > 0) {
    body.imageAttachments = attachments;
  }
  return body;
}
