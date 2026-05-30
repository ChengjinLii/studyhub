import { fetchBackend } from './apiBase';
import { ensureApiSuccess } from './apiEnvelope';

export interface RequestCreatePayload {
  course: string;
  keyword: string;
  budget: number | null;
  urgencyTier: string;
  creatorFloor: number | null;
  previewRequirement: string | null;
  school: string | null;
  college: string | null;
  major: string | null;
}

export interface RequestCreateResult {
  id?: number;
  paymentRequired?: boolean;
  form?: string | null;
}

export const createMaterialRequest = async (payload: RequestCreatePayload) => {
  const response = await fetchBackend('/requests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const envelope = await ensureApiSuccess<RequestCreateResult>(response, '发布失败');
  return envelope.data || {};
};
