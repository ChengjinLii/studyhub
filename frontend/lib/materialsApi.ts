import { fetchBackend } from './apiBase';
import { ApiError, ensureApiSuccess, readApiEnvelope, unwrapApiResponse } from './apiEnvelope';

export interface MaterialOrderResult {
  orderNo?: string;
  status?: string;
  paid?: boolean;
}

export interface MaterialDownloadResult {
  url: string;
}

export const createSimulatedMaterialOrder = async (materialId: number) => {
  const response = await fetchBackend('/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ materialId, channel: 'simulated' }),
  });
  await ensureApiSuccess<MaterialOrderResult>(response, '下单失败');
};

export const fetchMaterialDownloadLink = async (materialId: number) => {
  const response = await fetchBackend(`/materials/${materialId}/download`);
  const json = await readApiEnvelope<MaterialDownloadResult>(response);
  if (response.status === 403 && json?.error?.code === 'DOWNLOAD_QUOTA_EXHAUSTED') {
    throw new ApiError(json.msg || '下载次数已用完，如需继续下载请联系管理员重置额度。', response.status, json.error.code, json);
  }
  return unwrapApiResponse<MaterialDownloadResult>(response, '获取下载链接失败');
};

export const toggleMaterialLike = async (materialId: number, liked: boolean) => {
  const response = await fetchBackend(`/materials/${materialId}/like`, {
    method: liked ? 'DELETE' : 'POST',
  });
  return unwrapApiResponse<number>(response, '操作失败');
};
