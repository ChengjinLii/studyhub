import {
  MaterialDetail,
  MaterialListItem,
  PaginationMeta,
  CommentListResponse,
  Comment,
  MaterialPreview,
} from '../types/material';
import { ProfileSummary } from '../types/profile';
import { ContributorRank, LeaderboardPeriod } from '../types/contributor';
import { PublicUserProfile, UserAccountProfile } from '../types/userProfile';
import { MaterialRequestItem } from '../types/request';
import { resolveApiBase, buildBackendUrl } from './apiBase';
import { extractErrorMessage, extractErrorCode } from './errors';
import { normalizeMockAssets } from './mockAsset';

type ApiEnvelope<T> = {
  ok: boolean;
  data?: T;
  msg?: string;
  error?: {
    code?: string;
    message?: string;
  };
  code?: string;
};

export interface MaterialListResponse {
  items: MaterialListItem[];
  meta: PaginationMeta;
  stats?: MaterialListStats;
  availableTags?: string[];
}

export interface MaterialListStats {
  totalMaterials: number;
  freeMaterials: number;
  totalDownloads: number;
  userCount: number;
}

async function apiFetch<T>(path: string, init: RequestInit = {}, token?: string, origin?: string): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const apiBase = resolveApiBase(origin);
  const res = await fetch(`${apiBase}${path}`, {
    ...init,
    headers,
    cache: 'no-store',
  });
  const json: ApiEnvelope<T> = await res.json().catch(() => ({ ok: false } as ApiEnvelope<T>));
  if (!res.ok || !json.ok || !json.data) {
    const msg = extractErrorMessage(json, res.statusText || '请求失败');
    const code = extractErrorCode(json);
    const error = new Error(code ? `${msg}（${code}）` : msg);
    throw error;
  }
  return normalizeMockAssets(json.data);
}

const buildQuery = (params: Record<string, string | number | undefined>) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `?${qs}` : '';
};

async function webApiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  const res = await fetch(buildBackendUrl(path), {
    ...init,
    headers,
    credentials: init.credentials ?? 'include',
  });
  const json: ApiEnvelope<T> = await res.json().catch(() => ({ ok: false } as ApiEnvelope<T>));
  if (!res.ok || !json.ok || !json.data) {
    const msg = extractErrorMessage(json, res.statusText || '请求失败');
    throw new Error(msg);
  }
  return normalizeMockAssets(json.data);
}

export async function fetchMaterials(
  params: Record<string, string | number | undefined>,
  token?: string,
  origin?: string
) {
  return apiFetch<MaterialListResponse>(`/materials${buildQuery(params)}`, {}, token, origin);
}

export async function fetchColumnPosts(
  params: {
    topic?: string;
    page?: number;
    size?: number;
  },
  token?: string,
  origin?: string
) {
  return apiFetch<MaterialListResponse>(
    `/materials/column${buildQuery({
      topic: params.topic,
      page: params.page ?? 1,
      size: params.size ?? 12,
    })}`,
    {},
    token,
    origin
  );
}

export async function fetchColumnPostsClient(params: {
  topic?: string;
  page?: number;
  size?: number;
}, options: { signal?: AbortSignal } = {}) {
  return webApiFetch<MaterialListResponse>(
    `/api/materials/column${buildQuery({
      topic: params.topic,
      page: params.page ?? 1,
      size: params.size ?? 12,
    })}`,
    { signal: options.signal }
  );
}

export async function fetchRecommendations(token?: string, origin?: string, limit = 6) {
  return apiFetch<MaterialListItem[]>(`/materials/recommendations${buildQuery({ limit })}`, {}, token, origin);
}

export async function fetchMaterialRequests(
  params: Record<string, string | number | undefined>,
  token?: string,
  origin?: string
) {
  return apiFetch<MaterialRequestItem[]>(`/requests${buildQuery(params)}`, {}, token, origin);
}

export async function fetchRequestLeaderboard(limit = 6, token?: string, origin?: string) {
  return apiFetch<MaterialRequestItem[]>(
    `/requests/leaderboard${buildQuery({ limit })}`,
    {},
    token,
    origin
  );
}

export async function fetchMaterialDetail(id: string, token?: string, origin?: string) {
  return apiFetch<MaterialDetail>(`/materials/${id}`, {}, token, origin);
}

export async function recordMaterialView(id: number | string, viewerToken?: string) {
  return webApiFetch<{ viewCount: number }>(`/api/materials/${id}/view`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ viewerToken }),
  });
}

export async function fetchMaterialPreview(id: number | string) {
  return webApiFetch<MaterialPreview>(`/api/materials/${id}/preview`);
}

export async function fetchProfile(token: string, origin?: string) {
  return apiFetch<ProfileSummary>(`/me`, {}, token, origin);
}

export async function fetchAccountProfile(token: string, origin?: string) {
  return apiFetch<UserAccountProfile>(`/me/account`, {}, token, origin);
}

export async function fetchUserProfile(userId: string | number, token: string, origin?: string) {
  return apiFetch<PublicUserProfile>(`/users/${userId}/profile`, {}, token, origin);
}

export interface CommentPayload {
  materialId: number;
  parentId?: number | null;
  content: string;
}

export async function fetchComments(params: {
  materialId: number;
  sort?: string;
  page?: number;
  size?: number;
}) {
  return webApiFetch<CommentListResponse>(
    `/api/comments${buildQuery({
      materialId: params.materialId,
      sort: params.sort ?? 'latest',
      page: params.page ?? 0,
      size: params.size ?? 20,
    })}`
  );
}

export async function fetchCommentReplies(commentId: number, page = 0, size = 20) {
  return webApiFetch<CommentListResponse>(
    `/api/comments/${commentId}/replies${buildQuery({ page, size })}`
  );
}

export async function fetchContributorRanks(params: {
  limit?: number;
  period?: LeaderboardPeriod;
  origin?: string;
} = {}) {
  const { limit = 100, period = 'all', origin } = params;
  return apiFetch<ContributorRank[]>(
    `/leaderboard/contributors${buildQuery({ limit, period })}`,
    {},
    undefined,
    origin
  );
}

export async function createComment(payload: CommentPayload) {
  return webApiFetch<Comment>(`/api/comments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function updateComment(commentId: number, content: string) {
  return webApiFetch<Comment>(`/api/comments/${commentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
}

export async function deleteComment(commentId: number) {
  return webApiFetch<{ success: boolean }>(`/api/comments/${commentId}`, {
    method: 'DELETE',
  });
}

export async function likeComment(commentId: number) {
  return webApiFetch<{ likeCount: number }>(`/api/comments/${commentId}/like`, {
    method: 'POST',
  });
}

export async function unlikeComment(commentId: number) {
  return webApiFetch<{ likeCount: number }>(`/api/comments/${commentId}/like`, {
    method: 'DELETE',
  });
}

export async function reportTarget(targetType: string, targetId: number, reason: string) {
  return webApiFetch<{ id: number }>(`/api/reports`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targetType, targetId, reason }),
  });
}

export async function reportComment(commentId: number, reason: string, detail: string | undefined) {
  return reportTarget('COMMENT', commentId, reason);
}

export async function setMaterialRating(materialId: number, rating: number) {
  return webApiFetch<{ ratingAvg: number; ratingCount: number; rating: number }>(
    `/api/materials/${materialId}/rating`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating }),
    }
  );
}
