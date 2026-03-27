const MAJOR_SPLIT_REGEX = /[,，、/|]+/;

export const parseMajorList = (value?: string | null): string[] => {
  if (!value) return [];
  return value
    .split(MAJOR_SPLIT_REGEX)
    .map((item) => item.trim())
    .filter(Boolean);
};

export const formatMajorDisplay = (value?: string | null): string => {
  const majors = parseMajorList(value);
  return majors.join(' / ');
};

export const serializeMajorList = (values: string[]): string => values.map((item) => item.trim()).filter(Boolean).join(',');
