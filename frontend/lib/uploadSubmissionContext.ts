import type { CourseCategorySelection } from '../constants/metadata';

export interface UploadSubmissionContextInput {
  title: string;
  zipFile: { name: string } | null;
  maxTitleLength: number;
  isQuickMode: boolean;
  isExperience: boolean;
  isRequestResponse: boolean;
  quickProfile: { gradeValue: string; college: string; majors: string[] };
  fallbackGradeValue: string;
  gradeValue: string;
  courseCategory: CourseCategorySelection;
  college: string;
  selectedMajors: string[];
  tagList: string[];
  netdiskUrl: string;
  deliveryMethod: 'FILE' | 'NETDISK';
  previewSource: 'AUTO' | 'MANUAL';
}

export const deriveUploadAutoTitle = (name: string, maxTitleLength: number) => {
  const withoutExt = name.replace(/\.[^/.]+$/, '');
  return withoutExt.slice(0, maxTitleLength);
};

// Resolve existing mode precedence without validation, mutation, or I/O.
export const resolveUploadSubmissionContext = ({
  title, zipFile, maxTitleLength, isQuickMode, isExperience, isRequestResponse,
  quickProfile, fallbackGradeValue, gradeValue, courseCategory, college,
  selectedMajors, tagList, netdiskUrl, deliveryMethod, previewSource,
}: UploadSubmissionContextInput) => {
  const effectiveTitle = (title.trim() || (isQuickMode && zipFile ? deriveUploadAutoTitle(zipFile.name, maxTitleLength) : '')).slice(0, maxTitleLength);
  const effectiveGradeValue = isQuickMode ? quickProfile.gradeValue || fallbackGradeValue : gradeValue;
  const effectiveCourseCategory: CourseCategorySelection = isExperience ? 'GENERAL' : courseCategory;
  const effectiveCollege = effectiveCourseCategory === 'MAJOR' ? (isQuickMode ? quickProfile.college : college) : '';
  const effectiveMajors = effectiveCourseCategory === 'MAJOR' ? (isQuickMode ? quickProfile.majors : selectedMajors) : [];
  const effectiveTagList = isQuickMode ? [] : tagList;
  const trimmedNetdiskUrl = netdiskUrl.trim();
  const resolvedDelivery: 'FILE' | 'NETDISK' = isExperience ? 'FILE' : deliveryMethod === 'NETDISK' ? 'NETDISK' : 'FILE';
  const effectivePreviewSource: 'AUTO' | 'MANUAL' = isExperience
    ? 'AUTO'
    : isRequestResponse
      ? 'MANUAL'
      : isQuickMode
        ? 'AUTO'
        : previewSource;
  const allowCustomPreview = isExperience;

  return {
    effectiveTitle, effectiveGradeValue, effectiveCourseCategory, effectiveCollege,
    effectiveMajors, effectiveTagList, trimmedNetdiskUrl, resolvedDelivery,
    effectivePreviewSource, allowCustomPreview,
  };
};
