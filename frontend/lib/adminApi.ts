import {
  AdminListMeta,
  AdminMarketItem,
  AdminMaterial,
  AdminReport,
  FeedbackEntry,
  UserSummary,
  VolunteerApplicationEntry,
} from '../types/admin';
import {
  AdminMonthlyPayoutOverview,
  AdminPayoutQr,
  PayoutApplication,
  PayoutSchedule,
  PayoutSettlementDetail,
} from '../types/payout';
import { fetchBackend } from './apiBase';
import { ensureApiSuccess, unwrapApiResponse } from './apiEnvelope';

interface AdminListResponse<T> {
  items: T[];
  meta: AdminListMeta;
}

interface AdminBatchResult {
  updated?: number;
  deleted?: number;
  restored?: number;
  missingIds?: number[];
  failedIds?: number[];
}

const buildQuery = (params: Record<string, string | number | undefined>) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === '') return;
    search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `?${qs}` : '';
};

export const fetchAdminUsers = async (keyword?: string) => {
  const response = await fetchBackend(`/admin/users${buildQuery({ keyword })}`);
  return unwrapApiResponse<UserSummary[]>(response, '加载用户失败');
};

export const createAdminUser = async (payload: {
  username: string;
  password: string;
  nickname: string;
  roleMask: number;
}) => {
  const response = await fetchBackend('/admin/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return ensureApiSuccess(response, '创建失败');
};

export const updateAdminUserRole = async (id: number, roleMask: number) => {
  const response = await fetchBackend(`/admin/users?id=${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ roleMask }),
  });
  return ensureApiSuccess(response, '更新失败');
};

export const fetchAdminFeedbacks = async () => {
  const response = await fetchBackend('/admin/feedbacks');
  return unwrapApiResponse<FeedbackEntry[]>(response, '加载反馈失败');
};

export const updateAdminFeedbackStatus = async (id: number, status: string) => {
  const response = await fetchBackend(`/admin/feedbacks?id=${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  return ensureApiSuccess(response, '更新失败');
};

export const fetchAdminVolunteers = async () => {
  const response = await fetchBackend('/admin/volunteers');
  return unwrapApiResponse<VolunteerApplicationEntry[]>(response, '加载志愿者申请失败');
};

export const updateAdminVolunteerStatus = async (id: number, status: string) => {
  const response = await fetchBackend(`/admin/volunteers?id=${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  return ensureApiSuccess(response, '更新失败');
};

export const fetchAdminMaterials = async (params: { page: number; size: number; status?: string }) => {
  const response = await fetchBackend(`/admin/materials${buildQuery(params)}`);
  return unwrapApiResponse<AdminListResponse<AdminMaterial>>(response, '加载资料失败');
};

export const restoreAdminMaterial = async (materialId: number) => {
  const response = await fetchBackend(`/admin/materials/${materialId}/restore`, { method: 'POST' });
  return ensureApiSuccess(response, '恢复失败');
};

export const fetchAdminMarketItems = async (params: { page: number; size: number }) => {
  const response = await fetchBackend(`/admin/market${buildQuery(params)}`);
  return unwrapApiResponse<AdminListResponse<AdminMarketItem>>(response, '加载校园集市商品失败');
};

export const broadcastAdminNotification = async (message: string) => {
  const response = await fetchBackend('/admin/notifications', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, userId: null }),
  });
  return ensureApiSuccess(response, '广播失败');
};

export const batchUpdateAdminMaterials = async (payload: object) => {
  const response = await fetchBackend('/admin/materials/batch-update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<AdminBatchResult>(response, '批量更新失败');
};

export const batchDeleteAdminMaterials = async (materialIds: number[]) => {
  const response = await fetchBackend('/admin/materials/batch-delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ materialIds }),
  });
  return unwrapApiResponse<AdminBatchResult>(response, '批量删除失败');
};

export const batchRestoreAdminMaterials = async (materialIds: number[]) => {
  const response = await fetchBackend('/admin/materials/batch-restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ materialIds }),
  });
  return unwrapApiResponse<AdminBatchResult>(response, '批量恢复失败');
};

export const batchUpdateAdminMarketItems = async (payload: object) => {
  const response = await fetchBackend('/admin/market/batch-update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<AdminBatchResult>(response, '批量更新失败');
};

export const batchDeleteAdminMarketItems = async (itemIds: number[]) => {
  const response = await fetchBackend('/admin/market/batch-delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ itemIds }),
  });
  return unwrapApiResponse<AdminBatchResult>(response, '批量删除失败');
};

export const fetchAdminReports = async (params: {
  page: number;
  size: number;
  status?: string;
  targetType?: string;
}) => {
  const response = await fetchBackend(`/admin/reports${buildQuery(params)}`);
  return unwrapApiResponse<AdminListResponse<AdminReport>>(response, '加载举报列表失败');
};

export const updateAdminReport = async (
  id: number,
  payload: { status?: string; adminNote?: string; restoreTarget?: boolean }
) => {
  const response = await fetchBackend(`/admin/reports/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<AdminReport>(response, '更新举报失败');
};

export const fetchAdminMonthlyPayoutOverview = async (month: string) => {
  const response = await fetchBackend(`/admin/monthly-payout-overview?month=${encodeURIComponent(month)}`);
  return unwrapApiResponse<AdminMonthlyPayoutOverview>(response, '加载月度打款数据失败');
};

export const updateAdminMonthlyPayoutMark = async (payload: {
  monthKey: string;
  uploaderId: number;
  markPaid: boolean;
}) => {
  const response = await fetchBackend('/admin/monthly-payout-overview/marks', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return ensureApiSuccess(response, '更新打款标记失败');
};

export const fetchAdminPayoutQr = async (uploaderId: number) => {
  const response = await fetchBackend(`/admin/monthly-payout-overview/users/${uploaderId}/payout-qr`);
  return unwrapApiResponse<AdminPayoutQr>(response, '加载收款码失败');
};

export interface PayoutApplicationList {
  items: PayoutApplication[];
}

export const fetchPayoutApplications = async () => {
  const response = await fetchBackend('/admin/creator-payout-applications');
  return unwrapApiResponse<PayoutApplicationList>(response, '加载收益申请失败');
};

export const updatePayoutApplication = async (
  id: number,
  status: 'APPROVED' | 'REJECTED',
  reviewNotes?: string
) => {
  const response = await fetchBackend(`/admin/creator-payout-applications?id=${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, reviewNotes }),
  });
  return unwrapApiResponse<PayoutApplication>(response, '操作失败', { requireData: false });
};

export const fetchPayoutSettlementDetails = async (id: number) => {
  const response = await fetchBackend(`/admin/creator-payout-applications/${id}/details`);
  return unwrapApiResponse<PayoutSettlementDetail[]>(response, '加载收益明细失败');
};

export const fetchPayoutSchedule = async () => {
  const response = await fetchBackend('/admin/payout-schedule');
  return unwrapApiResponse<PayoutSchedule>(response, '加载上线日期失败');
};

export const updatePayoutSchedule = async (payload: { launchDate: string | null; nextPayoutDate?: string }) => {
  const response = await fetchBackend('/admin/payout-schedule', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<PayoutSchedule>(response, '更新失败');
};
