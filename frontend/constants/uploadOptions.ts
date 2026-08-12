export const UPLOAD_PRESET_TAGS = [
  '日常学习笔记',
  '期末速成',
  '期末真题',
  '期末真题标答',
  '期末答案（自制解析）',
  '期中速成',
  '期中真题',
  '期中真题标答',
  '期中答案（自制解析）',
  '一页纸',
  '开卷资料',
  '教材',
  '教材答案',
];

const currentYear = new Date().getFullYear();

export const UPLOAD_YEAR_SUGGESTIONS = Array.from({ length: 6 }, (_, index) => currentYear - index)
  .flatMap((year) => [year.toString(), `${year}-${year + 1}`])
  .filter((value, index, array) => array.indexOf(value) === index);
