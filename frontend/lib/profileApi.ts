import { MarketListingItem, UploadItem } from '../types/profile';
import { UserAccountProfile } from '../types/userProfile';
import { fetchBackend } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';

export interface AccountProfileUpdatePayload {
  nickname?: string;
  emailPrivacy: boolean;
  signature: string;
  school: string;
  college: string;
  major: string;
  gradeStages: string[];
}

export const updateAccountProfile = async (payload: AccountProfileUpdatePayload) => {
  const response = await fetchBackend('/me/account', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<UserAccountProfile>(response, '更新失败');
};

export const fetchUserUploads = async (userId: number) => {
  const response = await fetchBackend(`/users/${userId}/uploads`);
  return unwrapApiResponse<UploadItem[]>(response, '加载资料失败');
};

export const fetchUserMarketListings = async (userId: number) => {
  const response = await fetchBackend(`/users/${userId}/market`);
  return unwrapApiResponse<MarketListingItem[]>(response, '加载校园集市商品失败');
};

export const uploadPayoutQr = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetchBackend('/me/payout-qr', {
    method: 'POST',
    body: formData,
  });
  return unwrapApiResponse<UserAccountProfile>(response, '上传失败');
};

export const clearPayoutQr = async () => {
  const response = await fetchBackend('/me/payout-qr', { method: 'DELETE' });
  return unwrapApiResponse<UserAccountProfile>(response, '删除失败');
};
