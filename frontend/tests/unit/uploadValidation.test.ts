import { describe, expect, it } from 'vitest';
import {
  formatPriceSummary,
  normalizePriceInput,
  parsePriceValue,
  validateUploadSubmitInput,
} from '../../lib/uploadValidation';

const limits = {
  maxTitleLength: 80,
  maxDescLength: 300,
  maxExperienceLength: 3000,
  maxCopyrightLength: 8,
  maxPreviewImageBytes: 5 * 1024 * 1024,
  maxCustomPreviewText: 800,
  maxCustomPreviewImages: 5,
  minManualPreviewImages: 1,
  minRequestPreviewImages: 2,
};

const validInput = {
  token: 'token',
  isExperience: false,
  description: 'course notes',
  isExperienceCustomTopic: false,
  experienceCustomTag: '',
  customTags: '',
  zipPreparing: false,
  resolvedDelivery: 'NETDISK' as const,
  zipFile: null,
  hasExistingFile: false,
  trimmedNetdiskUrl: 'https://example.com/file',
  effectivePreviewSource: 'AUTO' as const,
  isRequestResponse: false,
  isEditing: false,
  manualPreviewFiles: [],
  customPreviewText: '',
  isQuickMode: false,
  customPreviewFiles: [],
  customPreviewLabel: '自定义预览图',
  effectiveTitle: 'Linear Algebra Notes',
  descriptionLimit: 300,
  copyrightOwner: '',
  price: '0',
  limits,
};

describe('uploadValidation', () => {
  it('normalizes integer-only prices', () => {
    expect(normalizePriceInput('0012元')).toBe('12');
    expect(parsePriceValue('free')).toBe(0);
    expect(formatPriceSummary('25')).toBe('当前：¥25');
  });

  it('accepts a valid netdisk material submission', () => {
    expect(validateUploadSubmitInput(validInput)).toEqual({ error: null, priceValue: 0 });
  });

  it('requires login before upload submission', () => {
    const result = validateUploadSubmitInput({ ...validInput, token: null });
    expect(result.error).toBe('请先登录后再投稿。');
  });

  it('rejects manual previews when required images are missing', () => {
    const result = validateUploadSubmitInput({
      ...validInput,
      effectivePreviewSource: 'MANUAL',
      resolvedDelivery: 'FILE',
      hasExistingFile: true,
    });
    expect(result.error).toBe('请至少上传 1 张预览图。');
  });
});
