export const SUPPORTED_SCHOOL = '电子科技大学';
export const SUPPORTED_COLLEGES = ['格院', '信通'] as const;
export const SUPPORTED_MAJORS = ['通信', '微电子', '电工'] as const;
export const GRADE_STAGE_OPTIONS = ['大一', '大二', '大三', '大四', '研究生', '英语', '技能'] as const;

export const defaultCollege = SUPPORTED_COLLEGES[0];
export const defaultMajor = SUPPORTED_MAJORS[0];

export const COURSE_CATEGORY_OPTIONS = [
  { value: 'GENERAL', label: '通识课', helper: '公共/任选课程，关注校内通识分享' },
  { value: 'MAJOR', label: '专业课', helper: '需填写学院与专业，精准匹配专业学习' },
  { value: 'SKILL', label: '英语/技能类', helper: '语言、竞赛与技能提升资料' },
] as const;

export type CourseCategoryValue = (typeof COURSE_CATEGORY_OPTIONS)[number]['value'];

export const COURSE_CATEGORY_LABELS: Record<CourseCategoryValue, string> = COURSE_CATEGORY_OPTIONS.reduce(
  (acc, option) => {
    acc[option.value] = option.label;
    return acc;
  },
  {} as Record<CourseCategoryValue, string>
);

export const COURSE_CATEGORY_VALUES = COURSE_CATEGORY_OPTIONS.map((option) => option.value) as CourseCategoryValue[];

export const normalizeCourseCategory = (value?: string | null, generalFlag = false): CourseCategoryValue => {
  const normalized = (value ?? '').toString().trim().toUpperCase() as CourseCategoryValue;
  if (COURSE_CATEGORY_VALUES.includes(normalized)) {
    return normalized;
  }
  return generalFlag ? 'GENERAL' : 'MAJOR';
};
