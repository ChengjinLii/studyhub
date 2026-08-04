export const MATERIAL_SORT_OPTIONS = [
  { value: 'latest', label: '综合推荐' },
  { value: 'newest', label: '最新发布（从新到旧）' },
  { value: 'downloads', label: '下载量（从高到低）' },
] as const;

export const MATERIAL_SORT_VALUES = MATERIAL_SORT_OPTIONS.map((option) => option.value);

export const normalizeMaterialSort = (value?: string | null) =>
  MATERIAL_SORT_VALUES.includes(value as (typeof MATERIAL_SORT_VALUES)[number]) ? value! : 'latest';
