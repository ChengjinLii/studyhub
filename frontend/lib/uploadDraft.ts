export const UPLOAD_DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export interface UploadTextDraft {
  version: 1;
  updatedAt: number;
  title: string;
  description: string;
  uploadMode: 'material' | 'experience';
  experienceTopic: string;
  experienceCustomTag: string;
  price: string;
  school: string;
  college: string;
  selectedMajors: string[];
  gradeValue: string;
  courseCategory: string;
  selectedTags: string[];
  customTags: string;
  yearTag: string;
  deliveryMethod: 'FILE' | 'NETDISK';
  previewSource: 'AUTO' | 'MANUAL';
  previewWatermarkEnabled: boolean;
  customPreviewText: string;
}

export type UploadTextDraftValue = Omit<UploadTextDraft, 'version' | 'updatedAt'>;

const cleanString = (value: unknown, maxLength: number) =>
  typeof value === 'string' ? value.slice(0, maxLength) : '';

const cleanStringList = (value: unknown, maxItems: number, maxLength: number) =>
  Array.isArray(value)
    ? value
        .filter((item): item is string => typeof item === 'string')
        .slice(0, maxItems)
        .map((item) => item.slice(0, maxLength))
    : [];

export const buildUploadDraftKey = (userId: number, scope: string) =>
  `studyhub:upload-draft:v1:${userId}:${scope.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 80) || 'material'}`;

export const hasMeaningfulUploadDraft = (draft: UploadTextDraft) =>
  Boolean(
    draft.title.trim() ||
      draft.description.trim() ||
      draft.experienceCustomTag.trim() ||
      draft.customTags.trim() ||
      draft.yearTag.trim() ||
      draft.customPreviewText.trim() ||
      draft.selectedTags.length ||
      draft.courseCategory ||
      draft.price !== '0' ||
      draft.deliveryMethod !== 'FILE' ||
      draft.previewSource !== 'AUTO' ||
      draft.uploadMode !== 'material'
  );

export function writeUploadDraft(storage: Storage, key: string, draft: UploadTextDraft) {
  try {
    if (!hasMeaningfulUploadDraft(draft)) {
      storage.removeItem(key);
      return;
    }
    storage.setItem(key, JSON.stringify(draft));
  } catch {
    // Local draft persistence must never block the upload form.
  }
}

export function readUploadDraft(
  storage: Storage,
  key: string,
  now = Date.now()
): UploadTextDraft | null {
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const value = JSON.parse(raw) as Record<string, unknown>;
    const updatedAt = Number(value.updatedAt);
    if (
      value.version !== 1 ||
      !Number.isFinite(updatedAt) ||
      now - updatedAt > UPLOAD_DRAFT_TTL_MS
    ) {
      storage.removeItem(key);
      return null;
    }
    return {
      version: 1,
      updatedAt,
      title: cleanString(value.title, 80),
      description: cleanString(value.description, 3000),
      uploadMode: value.uploadMode === 'experience' ? 'experience' : 'material',
      experienceTopic: cleanString(value.experienceTopic, 60),
      experienceCustomTag: cleanString(value.experienceCustomTag, 60),
      price: cleanString(value.price, 20) || '0',
      school: cleanString(value.school, 100),
      college: cleanString(value.college, 100),
      selectedMajors: cleanStringList(value.selectedMajors, 10, 100),
      gradeValue: cleanString(value.gradeValue, 50),
      courseCategory: ['GENERAL', 'MAJOR', 'SKILL'].includes(String(value.courseCategory))
        ? String(value.courseCategory)
        : '',
      selectedTags: cleanStringList(value.selectedTags, 3, 30),
      customTags: cleanString(value.customTags, 120),
      yearTag: cleanString(value.yearTag, 30),
      deliveryMethod: value.deliveryMethod === 'NETDISK' ? 'NETDISK' : 'FILE',
      previewSource: value.previewSource === 'MANUAL' ? 'MANUAL' : 'AUTO',
      previewWatermarkEnabled: value.previewWatermarkEnabled !== false,
      customPreviewText: cleanString(value.customPreviewText, 800),
    };
  } catch {
    try {
      storage.removeItem(key);
    } catch {
      // Ignore unavailable storage and continue with an empty draft.
    }
    return null;
  }
}

export function clearUploadDraft(storage: Storage, key: string) {
  try {
    storage.removeItem(key);
  } catch {
    // Storage can be unavailable in private browsing; submission still succeeds.
  }
}
