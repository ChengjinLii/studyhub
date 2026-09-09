import { describe, expect, it } from 'vitest';
import {
  deriveUploadAutoTitle,
  resolveUploadSubmissionContext,
  type UploadSubmissionContextInput,
} from '../../lib/uploadSubmissionContext';

const base: UploadSubmissionContextInput = {
  title: '  Course notes  ',
  zipFile: { name: 'review.notes.pdf' },
  maxTitleLength: 80,
  isQuickMode: false,
  isExperience: false,
  isRequestResponse: false,
  quickProfile: { gradeValue: 'quick-grade', college: 'quick-college', majors: ['quick-major'] },
  fallbackGradeValue: 'fallback-grade',
  gradeValue: 'form-grade',
  courseCategory: 'MAJOR',
  college: 'form-college',
  selectedMajors: ['form-major'],
  tagList: ['exam', 'notes'],
  netdiskUrl: ' https://example.com/resource ',
  deliveryMethod: 'FILE',
  previewSource: 'AUTO',
};

// Frozen characterization of upload.tsx at efdc1a7, before extraction.
// Keep this independent of the new helper to detect accidental policy changes.
const previousPageContext = (input: UploadSubmissionContextInput) => {
  const { title, zipFile, maxTitleLength: MAX_TITLE_LENGTH, isQuickMode, isExperience,
    isRequestResponse, quickProfile, fallbackGradeValue, gradeValue, courseCategory,
    college, selectedMajors, tagList, netdiskUrl, deliveryMethod, previewSource } = input;
  const deriveAutoTitle = (name: string) => name.replace(/\.[^/.]+$/, '').slice(0, MAX_TITLE_LENGTH);
  const effectiveTitle = (title.trim() || (isQuickMode && zipFile ? deriveAutoTitle(zipFile.name) : '')).slice(0, MAX_TITLE_LENGTH);
  const effectiveGradeValue = isQuickMode ? quickProfile.gradeValue || fallbackGradeValue : gradeValue;
  const effectiveCourseCategory = isExperience ? 'GENERAL' : courseCategory;
  const effectiveCollege = effectiveCourseCategory === 'MAJOR' ? (isQuickMode ? quickProfile.college : college) : '';
  const effectiveMajors = effectiveCourseCategory === 'MAJOR' ? (isQuickMode ? quickProfile.majors : selectedMajors) : [];
  const effectiveTagList = isQuickMode ? [] : tagList;
  const trimmedNetdiskUrl = netdiskUrl.trim();
  const resolvedDelivery = isExperience ? 'FILE' : deliveryMethod === 'NETDISK' ? 'NETDISK' : 'FILE';
  const effectivePreviewSource = isExperience ? 'AUTO' : isRequestResponse ? 'MANUAL' : isQuickMode ? 'AUTO' : previewSource;
  const allowCustomPreview = isExperience;
  return { effectiveTitle, effectiveGradeValue, effectiveCourseCategory, effectiveCollege,
    effectiveMajors, effectiveTagList, trimmedNetdiskUrl, resolvedDelivery, effectivePreviewSource, allowCustomPreview };
};

const cases: UploadSubmissionContextInput[] = [];
for (const isExperience of [false, true]) {
  for (const isQuickMode of [false, true]) {
    for (const isRequestResponse of [false, true]) {
      for (const courseCategory of ['', 'GENERAL', 'MAJOR', 'SKILL'] as const) {
        for (const deliveryMethod of ['FILE', 'NETDISK'] as const) {
          for (const previewSource of ['AUTO', 'MANUAL'] as const) {
            cases.push({ ...base, isExperience, isQuickMode, isRequestResponse, courseCategory, deliveryMethod, previewSource });
          }
        }
      }
    }
  }
}

describe('upload submission context', () => {
  it.each(cases)('preserves previous mode precedence (%#)', (input) => {
    const variants = [
      input,
      { ...input, title: '   ' },
      { ...input, title: '   ', zipFile: null },
      { ...input, title: 'x'.repeat(90) },
      { ...input, quickProfile: { ...input.quickProfile, gradeValue: '' } },
      { ...input, gradeValue: '', selectedMajors: [], tagList: [], netdiskUrl: '' },
    ];
    for (const variant of variants) {
      expect(resolveUploadSubmissionContext(variant)).toEqual(previousPageContext(variant));
    }
  });

  it.each([
    ['review.notes.pdf', 80, 'review.notes'],
    ['notes', 80, 'notes'],
    ['.hidden', 80, ''],
    ['long-title.docx', 4, 'long'],
    ['  notes .pdf', 80, '  notes '],
    ['folder.with.dot/file', 80, 'folder.with.dot/file'],
  ])('preserves filename handling for %s', (name, limit, expected) => {
    expect(deriveUploadAutoTitle(name, limit)).toBe(expected);
  });

  it('leaves missing course selection to the existing validator', () => {
    expect(resolveUploadSubmissionContext({ ...base, courseCategory: '' }).effectiveCourseCategory).toBe('');
  });

  it('preserves request precedence over quick mode and experience precedence over both', () => {
    const input = { ...base, isQuickMode: true, isRequestResponse: true };
    expect(resolveUploadSubmissionContext(input).effectivePreviewSource).toBe('MANUAL');
    expect(resolveUploadSubmissionContext({ ...input, isExperience: true })).toMatchObject({
      effectivePreviewSource: 'AUTO', effectiveCourseCategory: 'GENERAL', resolvedDelivery: 'FILE', allowCustomPreview: true,
    });
  });

  it('does not mutate input and preserves selected array references', () => {
    const input = structuredClone(base);
    const before = structuredClone(input);
    Object.freeze(input.quickProfile.majors);
    Object.freeze(input.quickProfile);
    Object.freeze(input.selectedMajors);
    Object.freeze(input.tagList);
    Object.freeze(input.zipFile);
    Object.freeze(input);
    const result = resolveUploadSubmissionContext(input);
    expect(input).toEqual(before);
    expect(result.effectiveMajors).toBe(input.selectedMajors);
    expect(result.effectiveTagList).toBe(input.tagList);
  });
});
