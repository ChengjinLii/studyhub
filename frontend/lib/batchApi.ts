import { webApiFetch } from './apiTransport';
import { buildBackendUrl } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';
import { BatchDetail, BatchId, BatchPage, CreateBatch, PublishBatch } from '../types/batch';

const path = (id: BatchId, admin = false) => `/api/${admin ? 'admin/' : ''}batch-submissions/${encodeURIComponent(id)}`;
const post = <T>(url: string, body?: unknown) => webApiFetch<T>(url, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}),
});
export const listOwnBatches = (offset: number, limit = 10, signal?: AbortSignal) =>
  webApiFetch<BatchPage>(`/api/batch-submissions?offset=${offset}&limit=${limit}`, { signal });
export const listAdminBatches = (offset: number, limit = 10, signal?: AbortSignal) =>
  webApiFetch<BatchPage>(`/api/admin/batch-submissions?offset=${offset}&limit=${limit}`, { signal });
export const getAdminBatch = (id: BatchId) => webApiFetch<BatchDetail>(path(id, true));
export const createBatch = (payload: CreateBatch) => post<BatchDetail>('/api/batch-submissions', payload);
export const submitBatch = (id: BatchId) => post<BatchDetail>(`${path(id)}/submit`);
export const amendBatch = (id: BatchId, note: string) => webApiFetch<BatchDetail>(path(id), {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }),
});
export const getOwnBatch = (id: BatchId) => webApiFetch<BatchDetail>(path(id));
export async function uploadBatchItem(id: BatchId, itemId: BatchId, file: File, onProgress?: (percentage: number) => void) {
  const base = `${path(id)}/items/${encodeURIComponent(itemId)}`;
  const { uploadToken, alreadyUploaded } = await post<{ uploadToken?: string; alreadyUploaded?: boolean }>(`${base}/authorize`);
  if (alreadyUploaded) return;
  const body = new FormData();
  body.append('file', file);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', buildBackendUrl(`${base}/file`));
    xhr.withCredentials = true;
    xhr.timeout = 600000;
    xhr.setRequestHeader('x-studyhub-upload-token', uploadToken!);
    xhr.upload.onprogress = event => { if (event.lengthComputable) onProgress?.(Math.round(event.loaded / event.total * 100)); };
    xhr.onerror = () => reject(new Error('网络中断，请重试；已保存的文件不会重复上传'));
    xhr.ontimeout = () => reject(new Error('上传超时，请重试以确认保存状态'));
    xhr.onload = () => unwrapApiResponse(new Response(xhr.responseText, { status: xhr.status }), '上传失败').then(resolve, reject);
    xhr.send(body);
  });
}
export const reviewBatch = (id: BatchId, itemIds: BatchId[], action: 'REVIEW' | 'RETURN' | 'REJECT', reason: string) =>
  post(`${path(id, true)}/review`, { itemIds, action, reason });
export const publishBatch = (id: BatchId, payload: PublishBatch) => post(`${path(id, true)}/publish`, payload);
export const downloadBatchItem = (id: BatchId, itemId: BatchId) =>
  webApiFetch<{ url: string }>(`${path(id, true)}/items/${encodeURIComponent(itemId)}/download`);
