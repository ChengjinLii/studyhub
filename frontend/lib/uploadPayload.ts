import { CourseCategoryValue } from '../constants/metadata';
import { serializeMajorList } from './major';

export type UploadDeliveryMethod = 'FILE' | 'NETDISK';
export type UploadPreviewSource = 'AUTO' | 'MANUAL';

export interface BuildUploadPayloadInput {
  title: string;
  description: string;
  priceValue: number;
  school: string;
  college: string;
  majors: string[];
  gradeValue: string;
  courseCategory: CourseCategoryValue;
  tags: string[];
  deliveryMethod: UploadDeliveryMethod;
  netdiskUrl: string;
  netdiskPassword: string;
  netdiskExpiredAt: string;
  netdiskReminderAt: string;
  previewWatermarkEnabled: boolean;
  previewSource: UploadPreviewSource;
  customPreviewText: string;
  copyrightOwner: string;
  isExperience: boolean;
  isQuickMode: boolean;
  isEditing: boolean;
  requestId: number | null;
  customPreviewClear: boolean;
}

export interface UploadPayload {
  title: string;
  description: string;
  price: number;
  school: string;
  college: string;
  major: string;
  gradeValue: string;
  gradeType: string;
  generalCourse: boolean;
  courseCategory: CourseCategoryValue;
  tags: string;
  deliveryMethod: UploadDeliveryMethod;
  netdiskUrl: string | null;
  netdiskPassword: string | null;
  netdiskExpiredAt: string | null;
  netdiskReminderAt: string | null;
  previewWatermarkEnabled: boolean;
  previewSource: UploadPreviewSource;
  customPreviewText: string | null;
  copyrightOwner: string | null;
  requestId?: number;
  customPreviewClear?: boolean;
  submissionId?: string;
}

export const deriveUploadGradeType = (stage: string) => {
  if (stage === '研究生') return 'GR';
  if (stage === '英语' || stage === '技能') return 'SKILL';
  return 'UG';
};

export function buildUploadPayload({
  title,
  description,
  priceValue,
  school,
  college,
  majors,
  gradeValue,
  courseCategory,
  tags,
  deliveryMethod,
  netdiskUrl,
  netdiskPassword,
  netdiskExpiredAt,
  netdiskReminderAt,
  previewWatermarkEnabled,
  previewSource,
  customPreviewText,
  copyrightOwner,
  isExperience,
  isQuickMode,
  isEditing,
  requestId,
  customPreviewClear,
}: BuildUploadPayloadInput): UploadPayload {
  const payload: UploadPayload = {
    title,
    description,
    price: priceValue * 100,
    school,
    college,
    major: majors.length > 0 ? serializeMajorList(majors) : '',
    gradeValue,
    gradeType: deriveUploadGradeType(gradeValue),
    generalCourse: courseCategory === 'GENERAL',
    courseCategory,
    tags: tags.join(','),
    deliveryMethod,
    netdiskUrl: isExperience ? null : netdiskUrl.trim() || null,
    netdiskPassword: isExperience ? null : netdiskPassword.trim() || null,
    netdiskExpiredAt: isExperience ? null : netdiskExpiredAt || null,
    netdiskReminderAt: isExperience ? null : netdiskReminderAt || null,
    previewWatermarkEnabled,
    previewSource,
    customPreviewText: customPreviewText.trim() || null,
    copyrightOwner: isExperience || isQuickMode ? null : copyrightOwner.trim() || null,
  };
  if (!isEditing && requestId) {
    payload.requestId = requestId;
  }
  if (isEditing) {
    payload.customPreviewClear = customPreviewClear;
  }
  return payload;
}
