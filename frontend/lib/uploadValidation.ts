import { CourseCategorySelection } from '../constants/metadata';

export const sanitizePriceInput = (value: string) => value.replace(/[^\d]/g, '');

export const normalizePriceInput = (value: string) => {
  const cleaned = sanitizePriceInput(value);
  if (!cleaned) return '0';
  return cleaned.replace(/^0+(?=\d)/, '');
};

export const parsePriceValue = (value: string) => {
  const normalized = normalizePriceInput(value);
  if (!/^\d+$/.test(normalized)) return null;
  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed) || parsed < 0) return null;
  return parsed;
};

export const formatPriceSummary = (value: string) => {
  const parsed = parsePriceValue(value);
  if (parsed === null) return '';
  return parsed === 0 ? '当前：免费' : `当前：¥${parsed}`;
};

interface UploadValidationLimits {
  maxTitleLength: number;
  maxDescLength: number;
  maxExperienceLength: number;
  maxCopyrightLength: number;
  maxPreviewImageBytes: number;
  maxCustomPreviewText: number;
  maxCustomPreviewImages: number;
  minManualPreviewImages: number;
  minRequestPreviewImages: number;
}

interface UploadSubmitValidationInput {
  token: string | null;
  isExperience: boolean;
  description: string;
  isExperienceCustomTopic: boolean;
  experienceCustomTag: string;
  customTags: string;
  zipPreparing: boolean;
  resolvedDelivery: 'FILE' | 'NETDISK';
  zipFile: File | null;
  hasExistingFile: boolean;
  trimmedNetdiskUrl: string;
  effectivePreviewSource: 'AUTO' | 'MANUAL';
  isRequestResponse: boolean;
  isEditing: boolean;
  manualPreviewFiles: File[];
  customPreviewText: string;
  isQuickMode: boolean;
  customPreviewFiles: File[];
  customPreviewLabel: string;
  effectiveTitle: string;
  descriptionLimit: number;
  copyrightOwner: string;
  price: string;
  courseCategory: CourseCategorySelection;
  limits: UploadValidationLimits;
}

export const validateUploadSubmitInput = ({
  token,
  isExperience,
  description,
  isExperienceCustomTopic,
  experienceCustomTag,
  customTags,
  zipPreparing,
  resolvedDelivery,
  zipFile,
  hasExistingFile,
  trimmedNetdiskUrl,
  effectivePreviewSource,
  isRequestResponse,
  isEditing,
  manualPreviewFiles,
  customPreviewText,
  isQuickMode,
  customPreviewFiles,
  customPreviewLabel,
  effectiveTitle,
  descriptionLimit,
  copyrightOwner,
  price,
  courseCategory,
  limits,
}: UploadSubmitValidationInput): { error: string | null; priceValue: number } => {
  if (!token) {
    return { error: '请先登录后再投稿。', priceValue: 0 };
  }
  if (isExperience && !description.trim()) {
    return { error: '请填写经验分享内容。', priceValue: 0 };
  }
  if (isExperience && isExperienceCustomTopic && !experienceCustomTag.trim()) {
    return { error: '请选择自定义标签时，请填写标签名称。', priceValue: 0 };
  }
  if (!isExperience && customTags.split(/[,，\s]+/).some((tag) => tag.trim() === '经验分享')) {
    return { error: '“经验分享”标签仅用于经验分享投稿。', priceValue: 0 };
  }
  if (!isExperience && !courseCategory) {
    return { error: '请选择课程类型。', priceValue: 0 };
  }
  if (zipPreparing) {
    return { error: '正在打包文件，请稍后再提交。', priceValue: 0 };
  }
  if (!isExperience && resolvedDelivery === 'FILE' && !zipFile && !hasExistingFile) {
    return { error: '请上传 50MB 以内的资料文件。', priceValue: 0 };
  }
  if (!isExperience && resolvedDelivery === 'NETDISK' && !trimmedNetdiskUrl) {
    return { error: '使用网盘链接时请填写链接地址。', priceValue: 0 };
  }
  if (!isExperience && effectivePreviewSource === 'MANUAL') {
    const minRequired = isRequestResponse ? limits.minRequestPreviewImages : limits.minManualPreviewImages;
    if (!isEditing && manualPreviewFiles.length < minRequired) {
      return { error: `请至少上传 ${minRequired} 张预览图。`, priceValue: 0 };
    }
    if (manualPreviewFiles.length > 0 && manualPreviewFiles.length < minRequired) {
      return { error: `预览图数量不足（至少 ${minRequired} 张）。`, priceValue: 0 };
    }
    const oversized = manualPreviewFiles.find((file) => file.size > limits.maxPreviewImageBytes);
    if (oversized) {
      return { error: `预览图 ${oversized.name} 超过 5MB。`, priceValue: 0 };
    }
  }
  if (!isExperience && !isQuickMode && customPreviewText.trim().length > limits.maxCustomPreviewText) {
    return { error: `自定义预览文字需在 ${limits.maxCustomPreviewText} 字以内。`, priceValue: 0 };
  }
  if (!isQuickMode && customPreviewFiles.length > limits.maxCustomPreviewImages) {
    return { error: `${customPreviewLabel}最多上传 ${limits.maxCustomPreviewImages} 张。`, priceValue: 0 };
  }
  const customOversized = !isQuickMode && customPreviewFiles.find((file) => file.size > limits.maxPreviewImageBytes);
  if (customOversized) {
    return { error: `${customPreviewLabel} ${customOversized.name} 超过 5MB。`, priceValue: 0 };
  }
  if (!effectiveTitle) {
    return {
      error: isQuickMode ? '请填写资料标题或上传文件以自动生成标题。' : '请填写资料标题。',
      priceValue: 0,
    };
  }
  if (effectiveTitle.length > limits.maxTitleLength) {
    return { error: `标题需在 ${limits.maxTitleLength} 个字符以内。`, priceValue: 0 };
  }
  if ((description || '').length > descriptionLimit) {
    return {
      error: isExperience
        ? `经验分享内容需在 ${limits.maxExperienceLength} 个字符以内。`
        : `资料简介需在 ${limits.maxDescLength} 个字符以内。`,
      priceValue: 0,
    };
  }
  if (!isQuickMode && copyrightOwner.trim().length > limits.maxCopyrightLength) {
    return { error: `版权持有者需在 ${limits.maxCopyrightLength} 个字符以内。`, priceValue: 0 };
  }
  const priceValue = isExperience ? 0 : parsePriceValue(price);
  if (!isExperience && priceValue === null) {
    return { error: '价格需为正整数，免费请填 0。', priceValue: 0 };
  }
  return { error: null, priceValue: priceValue ?? 0 };
};
