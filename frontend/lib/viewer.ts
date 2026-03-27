const VIEWER_ID_STORAGE_KEY = 'studyhub.viewer.id.v1';
const materialViewStorageKey = (materialId: number | string) => `studyhub.material.viewed.${materialId}`;

const randomToken = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `viewer_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
};

export const getOrCreateViewerId = () => {
  if (typeof window === 'undefined') {
    return '';
  }
  const existing = window.localStorage.getItem(VIEWER_ID_STORAGE_KEY);
  if (existing) {
    return existing;
  }
  const next = randomToken();
  window.localStorage.setItem(VIEWER_ID_STORAGE_KEY, next);
  return next;
};

export const hasRecordedMaterialView = (materialId: number | string, viewerId: string) => {
  if (typeof window === 'undefined' || !viewerId) {
    return false;
  }
  return window.localStorage.getItem(materialViewStorageKey(materialId)) === viewerId;
};

export const markMaterialViewRecorded = (materialId: number | string, viewerId: string) => {
  if (typeof window === 'undefined' || !viewerId) {
    return;
  }
  window.localStorage.setItem(materialViewStorageKey(materialId), viewerId);
};
