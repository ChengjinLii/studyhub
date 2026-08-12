export const SUPPORTED_SCHOOL = '电子科技大学';

// Keep this catalog aligned with the university's current undergraduate admissions directory.
export const UESTC_COLLEGE_MAJOR_OPTIONS = [
  {
    college: '英才实验学院（未来技术学院）',
    majors: [
      '电工',
      '通信',
      '网络工程',
      '电磁场与无线技术',
      '电子科学与技术',
      '微电子科学与工程',
      '集成电路设计与集成系统',
      '计算机科学与技术',
      '网络空间安全',
      '人工智能',
      '光电信息科学与工程',
      '信息工程',
      '测控技术与仪器',
      '自动化',
      '材料科学与工程',
      '机械设计制造及其自动化',
      '机器人工程',
      '生物医学工程',
    ],
  },
  { college: '信通', majors: ['通信', '电工', '信息对抗技术', '网络工程', '物联网工程'] },
  {
    college: '电子科学与工程学院',
    majors: ['电子科学与技术', '电磁场与无线技术'],
  },
  {
    college: '集成电路科学与工程学院（示范性微电子学院）',
    majors: ['集成电路设计与集成系统', '微电子科学与工程', '数理基础科学'],
  },
  {
    college: '材料与能源学院',
    majors: ['材料科学与工程', '新能源材料与器件', '应用化学'],
  },
  {
    college: '机械与电气工程学院',
    majors: ['机械设计制造及其自动化', '电气工程及其自动化', '智能电网信息工程', '工业工程', '机器人工程'],
  },
  {
    college: '光电科学与工程学院',
    majors: ['光电信息科学与工程', '信息工程'],
  },
  {
    college: '自动化工程学院',
    majors: ['测控技术与仪器', '自动化'],
  },
  {
    college: '资源与环境学院',
    majors: ['遥感科学与技术', '地球信息科学与技术'],
  },
  {
    college: '计算机科学与工程学院（网络空间安全学院）',
    majors: ['计算机科学与技术', '网络空间安全', '数据科学与大数据技术', '人工智能'],
  },
  {
    college: '信息与软件工程学院（示范性软件学院）',
    majors: ['软件工程'],
  },
  {
    college: '航空航天学院',
    majors: ['航空航天工程', '无人驾驶航空器系统工程', '飞行器控制与信息工程', '低空技术与工程'],
  },
  {
    college: '数学科学学院',
    majors: ['数学与应用数学', '信息与计算科学', '数据科学与大数据技术'],
  },
  {
    college: '物理学院',
    majors: ['电子信息科学与技术', '应用物理学', '量子信息科学'],
  },
  {
    college: '医学院',
    majors: ['临床医学', '护理学'],
  },
  {
    college: '生命科学与技术学院',
    majors: ['生物医学工程', '生物技术'],
  },
  {
    college: '经济与管理学院',
    majors: ['工商管理', '金融学', '电子商务', '大数据管理与应用', '供应链管理'],
  },
  {
    college: '外国语学院',
    majors: ['英语', '日语', '法语'],
  },
  {
    college: '公共管理学院',
    majors: ['法学', '信息管理与信息系统', '行政管理', '城市管理'],
  },
  { college: '格院', majors: ['通信', '微电子', '电工'] },
] as const;

const LEGACY_COLLEGE_ALIASES = {
  信息与通信工程学院: '信通',
  格拉斯哥学院: '格院',
  格拉斯哥海南学院: '格院',
} as const;

export const UESTC_COLLEGES = UESTC_COLLEGE_MAJOR_OPTIONS.map((option) => option.college);
export const UESTC_MAJORS = Array.from(new Set(UESTC_COLLEGE_MAJOR_OPTIONS.flatMap((option) => [...option.majors])));
export const SUPPORTED_COLLEGES = [...UESTC_COLLEGES];
export const SUPPORTED_MAJORS = [...UESTC_MAJORS];
export const GRADE_STAGE_OPTIONS = ['大一', '大二', '大三', '大四', '研究生', '英语', '技能'] as const;

// Preserve existing quick-upload defaults and stored profile values.
export const defaultCollege = '格院';
export const defaultMajor = '通信';

export const getCollegeOptions = (currentValue?: string | null): string[] => {
  const current = currentValue?.trim();
  return current && !UESTC_COLLEGES.includes(current as (typeof UESTC_COLLEGES)[number])
    ? [current, ...UESTC_COLLEGES]
    : [...UESTC_COLLEGES];
};

export const getMajorOptionsForCollege = (college?: string | null, currentValue?: string | null): string[] => {
  const normalizedCollege = college?.trim() ?? '';
  const canonicalCollege = LEGACY_COLLEGE_ALIASES[normalizedCollege as keyof typeof LEGACY_COLLEGE_ALIASES] ?? normalizedCollege;
  const matched = UESTC_COLLEGE_MAJOR_OPTIONS.find((option) => option.college === canonicalCollege);
  const options = matched ? [...matched.majors] : [...UESTC_MAJORS];
  const current = currentValue?.trim();
  return current && !options.includes(current as (typeof options)[number]) ? [current, ...options] : options;
};

export const COURSE_CATEGORY_OPTIONS = [
  { value: 'GENERAL', label: '通识课', helper: '公共/任选课程，关注校内通识分享' },
  { value: 'MAJOR', label: '专业课', helper: '需填写学院与专业，精准匹配专业学习' },
  { value: 'SKILL', label: '英语/技能类', helper: '语言、竞赛与技能提升资料' },
] as const;

export type CourseCategoryValue = (typeof COURSE_CATEGORY_OPTIONS)[number]['value'];
export type CourseCategorySelection = CourseCategoryValue | '';

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
