const parseNumericId = (value: string): string | null => {
  if (!value) return null;
  const match = value.match(/^(\d+)/);
  return match ? match[1] : null;
};

export const parseMaterialId = parseNumericId;
export const parseUserId = parseNumericId;
export const parseMarketId = parseNumericId;

export const slugifyTitle = (value: string): string => {
  if (!value) return '';
  return value
    .trim()
    .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
    .replace(/_+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
};

export const materialPath = (id: number | string, title?: string): string => {
  const rawId = String(id);
  const normalizedId = parseMaterialId(rawId) ?? rawId;
  const slug = title ? slugifyTitle(title) : '';
  return slug ? `/materials/${normalizedId}-${slug}` : `/materials/${normalizedId}`;
};

export const userPath = (id: number | string, name?: string): string => {
  const rawId = String(id);
  const normalizedId = parseUserId(rawId) ?? rawId;
  const slug = name ? slugifyTitle(name) : '';
  return slug ? `/u/${normalizedId}-${slug}` : `/u/${normalizedId}`;
};

export const marketPath = (id: number | string, title?: string): string => {
  const rawId = String(id);
  const normalizedId = parseMarketId(rawId) ?? rawId;
  const slug = title ? slugifyTitle(title) : '';
  return slug ? `/market/${normalizedId}-${slug}` : `/market/${normalizedId}`;
};
