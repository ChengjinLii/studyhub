const SIGNATURE_HINTS = ['Signature=', 'OSSAccessKeyId=', 'AccessKeyId='];
const MARKET_PLACEHOLDER_RE = /placehold\.co\/\d+x\d+\?text=Campus\+Market(?:$|&)/i;

export const isOssUrl = (url: string) => /aliyuncs\.com/i.test(url) || /oss-/i.test(url);
export const isMarketPlaceholder = (url?: string | null) => !!url && MARKET_PLACEHOLDER_RE.test(url);

const hasSignature = (url: string) => SIGNATURE_HINTS.some((key) => url.includes(key));

const canAppendProcess = (url: string) => isOssUrl(url) && !hasSignature(url) && !url.includes('x-oss-process');

const buildProcess = (width: number, quality: number, format?: string) => {
  const resize = `image/resize,w_${Math.max(1, Math.round(width))}`;
  const qualityPart = `/quality,q_${Math.max(1, Math.min(quality, 100))}`;
  const formatPart = format ? `/format,${format}` : '';
  return `x-oss-process=${resize}${qualityPart}${formatPart}`;
};

const appendProcess = (url: string, process: string) => {
  if (!url || !process) return url;
  if (!canAppendProcess(url)) {
    return url;
  }
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}${process}`;
};

interface ResponsiveOptions {
  alt: string;
  widths: number[];
  sizes: string;
  fallback?: string;
  quality?: number;
  enableWebp?: boolean;
  loading?: 'lazy' | 'eager';
  fetchPriority?: 'high' | 'low' | 'auto';
}

export interface ResponsiveImageResult {
  img: {
    src: string;
    srcSet?: string;
    sizes?: string;
    alt: string;
    loading: 'lazy' | 'eager';
    fetchPriority?: 'high' | 'low' | 'auto';
  };
  webp?: {
    srcSet: string;
    sizes?: string;
  };
}

export const buildResponsiveImage = (source: string, options: ResponsiveOptions): ResponsiveImageResult => {
  const {
    alt,
    widths,
    sizes,
    fallback = 'https://placehold.co/400x260?text=Image',
    quality = 75,
    enableWebp = true,
    loading = 'lazy',
    fetchPriority,
  } = options;

  if (!source || !isOssUrl(source) || !canAppendProcess(source)) {
    return {
      img: {
        src: source || fallback,
        alt,
        loading,
        sizes,
        fetchPriority,
      },
    };
  }

  const widthList = widths.length ? widths : [600];
  const fallbackVariants = widthList.map((width) => appendProcess(source, buildProcess(width, quality))).filter(Boolean);
  const fallbackSrc = fallbackVariants[0] || source;
  const fallbackSrcSet = fallbackVariants
    .map((variant, idx) => `${variant} ${widthList[idx]}w`)
    .join(', ');

  let webpSrcSet: string | undefined;
  if (enableWebp) {
    const variants = widthList
      .map((width) => appendProcess(source, buildProcess(width, quality, 'webp')))
      .filter((variant) => variant && variant !== source);
    if (variants.length) {
      webpSrcSet = variants.map((variant, idx) => `${variant} ${widthList[idx]}w`).join(', ');
    }
  }

  return {
    img: {
      src: fallbackSrc,
      srcSet: fallbackSrcSet || undefined,
      sizes,
      alt,
      loading,
      fetchPriority,
    },
    webp: webpSrcSet
      ? {
          srcSet: webpSrcSet,
          sizes,
        }
      : undefined,
  };
};
