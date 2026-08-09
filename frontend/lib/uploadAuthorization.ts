import { fetchBackend } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';

export type UploadFileRole = 'MATERIAL' | 'PREVIEW' | 'CUSTOM_PREVIEW';

export interface UploadFileDescriptor {
  role: UploadFileRole;
  name: string;
  sizeBytes: number;
  contentType: string;
}

export interface MaterialUploadAuthorizationResult {
  uploadToken: string;
  expiresInSeconds: number;
  remainingDailySubmissions: number;
  remainingDailyBytes: number;
}

export const describeUploadFile = (role: UploadFileRole, file: File): UploadFileDescriptor => ({
  role,
  name: file.name,
  sizeBytes: file.size,
  contentType: file.type || '',
});

export const requestMaterialUploadAuthorization = async (
  submissionId: string,
  files: UploadFileDescriptor[],
  token?: string | null
) => {
  const response = await fetchBackend('/material-upload-authorizations', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ submissionId, files }),
  });
  return unwrapApiResponse<MaterialUploadAuthorizationResult>(response, '获取上传授权失败');
};
