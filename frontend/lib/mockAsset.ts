const SAMPLE_STATIC_HOST = 'static.studyhub.local';

const PLACEHOLDER_PATHS = {
  avatar: '/placeholders/avatar.svg',
  market: '/placeholders/market-item.svg',
  material: '/placeholders/material-preview.svg',
  payout: '/placeholders/payout-qr.svg',
  generic: '/placeholders/generic-asset.svg',
} as const;

const isSampleStaticUrl = (value: string) => {
  try {
    return new URL(value).hostname === SAMPLE_STATIC_HOST;
  } catch {
    return false;
  }
};

const isPlaceholderPath = (value: string) => value.startsWith('/placeholders/');

const resolvePlaceholderPath = (pathname: string) => {
  if (pathname.startsWith('/avatar/')) return PLACEHOLDER_PATHS.avatar;
  if (pathname.startsWith('/market/')) return PLACEHOLDER_PATHS.market;
  if (pathname.startsWith('/materials/')) return PLACEHOLDER_PATHS.material;
  if (pathname.startsWith('/payout/')) return PLACEHOLDER_PATHS.payout;
  return PLACEHOLDER_PATHS.generic;
};

const normalizeSampleStaticUrl = (value: string) => {
  if (!value.includes(SAMPLE_STATIC_HOST)) return value;
  if (value.includes(',')) {
    return value
      .split(',')
      .map((part) => {
        const trimmed = part.trim();
        if (!trimmed) return trimmed;
        const [rawUrl, ...descriptors] = trimmed.split(/\s+/);
        const mapped = normalizeSampleStaticUrl(rawUrl);
        return [mapped, ...descriptors].join(' ');
      })
      .join(', ');
  }
  if (!isSampleStaticUrl(value)) return value;
  const parsed = new URL(value);
  return resolvePlaceholderPath(parsed.pathname);
};

const normalizeVariantLikeObject = (value: Record<string, unknown>) => {
  const next: Record<string, unknown> = { ...value };
  const normalizedSrc = typeof next.src === 'string' ? normalizeSampleStaticUrl(next.src) : next.src;
  if (typeof normalizedSrc === 'string') {
    next.src = normalizedSrc;
    if (isPlaceholderPath(normalizedSrc)) {
      if ('srcSet' in next) next.srcSet = null;
      if ('webpSrcSet' in next) next.webpSrcSet = null;
      if ('avifSrcSet' in next) next.avifSrcSet = null;
      if ('lqip' in next) next.lqip = null;
      return next;
    }
  }
  if (typeof next.srcSet === 'string') next.srcSet = normalizeSampleStaticUrl(next.srcSet);
  if (typeof next.webpSrcSet === 'string') next.webpSrcSet = normalizeSampleStaticUrl(next.webpSrcSet);
  if (typeof next.avifSrcSet === 'string') next.avifSrcSet = normalizeSampleStaticUrl(next.avifSrcSet);
  return next;
};

const normalizePreviewImageObject = (value: Record<string, unknown>) => {
  const next: Record<string, unknown> = { ...value };
  if (next.img && typeof next.img === 'object' && !Array.isArray(next.img)) {
    next.img = normalizeVariantLikeObject(next.img as Record<string, unknown>);
    const imgSrc = (next.img as Record<string, unknown>).src;
    if (typeof imgSrc === 'string' && isPlaceholderPath(imgSrc)) {
      next.webp = null;
      next.avif = null;
      next.lqip = null;
      return next;
    }
  }
  if (next.webp && typeof next.webp === 'object' && !Array.isArray(next.webp)) {
    next.webp = normalizeVariantLikeObject(next.webp as Record<string, unknown>);
  }
  if (next.avif && typeof next.avif === 'object' && !Array.isArray(next.avif)) {
    next.avif = normalizeVariantLikeObject(next.avif as Record<string, unknown>);
  }
  return next;
};

export const normalizeMockAssets = <T>(value: T): T => {
  if (typeof value === 'string') {
    return normalizeSampleStaticUrl(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeMockAssets(item)) as T;
  }
  if (!value || typeof value !== 'object') {
    return value;
  }

  const raw = value as Record<string, unknown>;
  if ('img' in raw) {
    return normalizePreviewImageObject(raw) as T;
  }
  if ('src' in raw) {
    return normalizeVariantLikeObject(raw) as T;
  }

  const next: Record<string, unknown> = {};
  Object.entries(raw).forEach(([key, item]) => {
    next[key] = normalizeMockAssets(item);
  });
  return next as T;
};

export const placeholderAssetPath = PLACEHOLDER_PATHS;
