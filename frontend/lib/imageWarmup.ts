type WarmImageOptions = {
  srcSet?: string | null;
  sizes?: string | null;
};

const warmedImageCache = new Map<string, Promise<void>>();

const buildImageCacheKey = (src: string, options?: WarmImageOptions) =>
  JSON.stringify({
    src,
    srcSet: options?.srcSet || '',
    sizes: options?.sizes || '',
  });

export const warmImage = (src?: string | null, options?: WarmImageOptions) => {
  if (typeof window === 'undefined' || !src) {
    return Promise.resolve();
  }
  const cacheKey = buildImageCacheKey(src, options);
  const cached = warmedImageCache.get(cacheKey);
  if (cached) {
    return cached;
  }
  const pending = new Promise<void>((resolve) => {
    const image = new window.Image();
    if (options?.srcSet) {
      image.srcset = options.srcSet;
    }
    if (options?.sizes) {
      image.sizes = options.sizes;
    }
    image.onload = () => resolve();
    image.onerror = () => resolve();
    image.src = src;
    if (typeof image.decode === 'function') {
      image.decode().then(resolve).catch(resolve);
    }
  });
  warmedImageCache.set(cacheKey, pending);
  return pending;
};

export const warmImages = (items: Array<{ src?: string | null; srcSet?: string | null; sizes?: string | null }>) =>
  Promise.all(items.map((item) => warmImage(item.src, item)));
