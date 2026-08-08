import { describe, expect, it } from 'vitest';
import {
  resolveUploadSectionCompletion,
  UploadSectionCompletionInput,
} from '../../lib/uploadSectionCompletion';

const completeInput: UploadSectionCompletionInput = {
  isExperience: false,
  isQuickMode: false,
  isExperienceCustomTopic: false,
  title: '通信原理复习资料',
  description: '',
  experienceCustomTag: '',
  price: '0',
  school: '电子科技大学',
  college: '信通',
  gradeValue: '研究生',
  courseCategory: 'MAJOR',
  deliveryMethod: 'FILE',
  hasSelectedFile: true,
  hasExistingFile: false,
  zipPreparing: false,
  netdiskUrl: '',
  previewSource: 'AUTO',
  isRequestResponse: false,
  isEditing: false,
  manualPreviewCount: 0,
  minManualPreviewImages: 1,
  minRequestPreviewImages: 2,
  agreementAccepted: true,
};

describe('resolveUploadSectionCompletion', () => {
  it('marks all required material sections complete', () => {
    expect(resolveUploadSectionCompletion(completeInput)).toEqual({
      'upload-basic': { complete: true, missing: [] },
      'upload-meta': { complete: true, missing: [] },
      'upload-delivery': { complete: true, missing: [] },
      'upload-confirm': { complete: true, missing: [] },
    });
  });

  it('keeps sections incomplete while required values are missing', () => {
    const result = resolveUploadSectionCompletion({
      ...completeInput,
      title: '',
      college: '',
      hasSelectedFile: false,
      agreementAccepted: false,
    });

    expect(result['upload-basic']).toEqual({ complete: false, missing: ['资料标题'] });
    expect(result['upload-meta']).toEqual({ complete: false, missing: ['学院'] });
    expect(result['upload-delivery']).toEqual({ complete: false, missing: ['资料文件'] });
    expect(result['upload-confirm']).toEqual({ complete: false, missing: ['同意平台协议'] });
  });

  it('requires experience content and a selected custom topic name', () => {
    const result = resolveUploadSectionCompletion({
      ...completeInput,
      isExperience: true,
      isExperienceCustomTopic: true,
      description: '',
      experienceCustomTag: '',
      hasSelectedFile: false,
    });

    expect(result['upload-basic']).toEqual({ complete: false, missing: ['经验分享内容'] });
    expect(result['upload-meta']).toEqual({ complete: false, missing: ['自定义标签名称'] });
    expect(result['upload-delivery']).toEqual({ complete: true, missing: [] });
  });

  it('keeps standard and quick upload metadata incomplete until a course category is selected', () => {
    const standard = resolveUploadSectionCompletion({ ...completeInput, courseCategory: '' });
    const quick = resolveUploadSectionCompletion({ ...completeInput, isQuickMode: true, courseCategory: '' });

    expect(standard['upload-meta']).toEqual({ complete: false, missing: ['课程类型'] });
    expect(quick['upload-meta']).toEqual({ complete: false, missing: ['课程类型'] });
  });

  it('requires the configured number of manual preview images for a new submission', () => {
    const incomplete = resolveUploadSectionCompletion({
      ...completeInput,
      previewSource: 'MANUAL',
      manualPreviewCount: 0,
    });
    const complete = resolveUploadSectionCompletion({
      ...completeInput,
      previewSource: 'MANUAL',
      manualPreviewCount: 1,
    });

    expect(incomplete['upload-delivery']).toEqual({ complete: false, missing: ['至少 1 张预览图'] });
    expect(complete['upload-delivery']).toEqual({ complete: true, missing: [] });
  });
});
