import type { CSSProperties } from 'react';

export type BrandLogoTheme = 'light' | 'dark';

interface BrandLogoProps {
  theme?: BrandLogoTheme;
  size?: number;
  className?: string;
  style?: CSSProperties;
  alt?: string;
}

export default function BrandLogo({
  theme = 'light',
  size = 28,
  className,
  style,
  alt = '',
}: BrandLogoProps) {
  const src = theme === 'dark' ? '/brand/logo-dark.png' : '/brand/logo-light.png';
  return (
    // eslint-disable-next-line @next/next/no-img-element -- synchronous raster render needed for opening splash animation
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      loading="eager"
      decoding="sync"
      className={className}
      style={{ display: 'block', width: size, height: size, objectFit: 'contain', ...style }}
    />
  );
}
