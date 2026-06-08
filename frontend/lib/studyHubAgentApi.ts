import { MaterialListItem } from '../types/material';
import { fetchBackend } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';
import type { StudyHubAgentImageAttachment } from '../components/studyHubAgent/types';

interface AiRecommendationPayload {
  output?: string | null;
}

export const requestStudyHubAgentRecommendations = async (
  query: string,
  contextQuery?: string,
  imageAttachments: StudyHubAgentImageAttachment[] = []
) => {
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
  const response = await fetchBackend('/ai-recommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return unwrapApiResponse<AiRecommendationPayload>(response, 'StudyHub 学习辅导暂时无法连接资料推荐服务');
};

export const fetchStudyHubAgentMaterial = async (materialId: number) => {
  const response = await fetchBackend(`/materials/${materialId}`);
  return unwrapApiResponse<MaterialListItem>(response, '加载资料详情失败');
};
