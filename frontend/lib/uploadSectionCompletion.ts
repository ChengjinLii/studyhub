import { CourseCategorySelection } from '../constants/metadata';
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
  courseCategory: CourseCategorySelection;
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

export interface UploadSectionStatus {
  complete: boolean;
  missing: string[];
}

const statusFromMissing = (missing: string[]): UploadSectionStatus => ({
  complete: missing.length === 0,
  missing,
});

export const resolveUploadSectionCompletion = (
  input: UploadSectionCompletionInput
): Record<string, UploadSectionStatus> => {
  const hasEffectiveTitle = Boolean(input.title.trim()) || (input.isQuickMode && input.hasSelectedFile);
  const basicMissing: string[] = [];
  if (!hasEffectiveTitle) basicMissing.push('资料标题');
  if (input.isExperience && !input.description.trim()) basicMissing.push('经验分享内容');
  if (!input.isExperience && parsePriceValue(input.price) === null) basicMissing.push('有效价格');

  const metaMissing: string[] = [];
  if (input.isExperience) {
    if (input.isExperienceCustomTopic && !input.experienceCustomTag.trim()) {
      metaMissing.push('自定义标签名称');
    }
  } else {
    if (!input.courseCategory) metaMissing.push('课程类型');
    if (!input.school.trim()) metaMissing.push('学校');
    if (input.courseCategory === 'MAJOR' && !input.college.trim()) metaMissing.push('学院');
    if (!input.gradeValue.trim()) metaMissing.push('年级/阶段');
  }

  const requiredPreviewCount = input.isRequestResponse
    ? input.minRequestPreviewImages
    : input.minManualPreviewImages;
  const deliveryMissing: string[] = [];
  if (!input.isExperience) {
    if (input.zipPreparing) deliveryMissing.push('等待文件打包完成');
    if (input.deliveryMethod === 'NETDISK' && !input.netdiskUrl.trim()) {
      deliveryMissing.push('网盘链接');
    }
    if (input.deliveryMethod === 'FILE' && !input.hasSelectedFile && !input.hasExistingFile) {
      deliveryMissing.push('资料文件');
    }
    if (
      input.previewSource === 'MANUAL' &&
      !input.isEditing &&
      input.manualPreviewCount < requiredPreviewCount
    ) {
      deliveryMissing.push(`至少 ${requiredPreviewCount} 张预览图`);
    }
  }

  return {
    'upload-basic': statusFromMissing(basicMissing),
    'upload-meta': statusFromMissing(metaMissing),
    'upload-delivery': statusFromMissing(deliveryMissing),
    'upload-confirm': statusFromMissing(input.agreementAccepted ? [] : ['同意平台协议']),
  };
};
