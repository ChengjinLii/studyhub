import { CourseCategoryValue } from '../constants/metadata';
import { parsePriceValue } from './uploadValidation';

export interface UploadSectionCompletionInput {
  isExperience: boolean;
  isQuickMode: boolean;
  isExperienceCustomTopic: boolean;
  title: string;
  description: string;
  experienceCustomTag: string;
  price: string;
  school: string;
  college: string;
  gradeValue: string;
  courseCategory: CourseCategoryValue;
  deliveryMethod: 'FILE' | 'NETDISK';
  hasSelectedFile: boolean;
  hasExistingFile: boolean;
  zipPreparing: boolean;
  netdiskUrl: string;
  previewSource: 'AUTO' | 'MANUAL';
  isRequestResponse: boolean;
  isEditing: boolean;
  manualPreviewCount: number;
  minManualPreviewImages: number;
  minRequestPreviewImages: number;
  agreementAccepted: boolean;
}

export const resolveUploadSectionCompletion = (input: UploadSectionCompletionInput): Record<string, boolean> => {
  const hasEffectiveTitle = Boolean(input.title.trim()) || (input.isQuickMode && input.hasSelectedFile);
  const basicComplete =
    hasEffectiveTitle &&
    (!input.isExperience || Boolean(input.description.trim())) &&
    (input.isExperience || parsePriceValue(input.price) !== null);
  const metaComplete = input.isExperience
    ? !input.isExperienceCustomTopic || Boolean(input.experienceCustomTag.trim())
    : Boolean(input.school.trim()) &&
      Boolean(input.gradeValue.trim()) &&
      input.courseCategory !== undefined &&
      (input.courseCategory !== 'MAJOR' || Boolean(input.college.trim()));
  const requiredPreviewCount = input.isRequestResponse
    ? input.minRequestPreviewImages
    : input.minManualPreviewImages;
  const previewComplete =
    input.previewSource === 'AUTO' || input.isEditing || input.manualPreviewCount >= requiredPreviewCount;
  const deliveryComplete =
    input.isExperience ||
    (!input.zipPreparing &&
      previewComplete &&
      (input.deliveryMethod === 'NETDISK'
        ? Boolean(input.netdiskUrl.trim())
        : input.hasSelectedFile || input.hasExistingFile));

  return {
    'upload-overview': true,
    'upload-basic': basicComplete,
    'upload-meta': metaComplete,
    'upload-delivery': deliveryComplete,
    'upload-confirm': input.agreementAccepted,
  };
};
