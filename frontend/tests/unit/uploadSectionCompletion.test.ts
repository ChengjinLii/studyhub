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
      'upload-overview': true,
      'upload-basic': true,
      'upload-meta': true,
      'upload-delivery': true,
      'upload-confirm': true,
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

    expect(result['upload-basic']).toBe(false);
    expect(result['upload-meta']).toBe(false);
    expect(result['upload-delivery']).toBe(false);
    expect(result['upload-confirm']).toBe(false);
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

    expect(result['upload-basic']).toBe(false);
    expect(result['upload-meta']).toBe(false);
    expect(result['upload-delivery']).toBe(true);
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

    expect(incomplete['upload-delivery']).toBe(false);
    expect(complete['upload-delivery']).toBe(true);
  });
});
