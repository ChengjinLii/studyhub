import { forwardRef, ImgHTMLAttributes } from 'react';

export type AppImageProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'alt'> & {
  alt: string;
};

const AppImage = forwardRef<HTMLImageElement, AppImageProps>(function AppImage(props, ref) {
  // Many StudyHub images are runtime URLs, captcha data URLs, or user-uploaded assets.
  // Keep one shared rendering entry so future image policy changes happen in one place.
  /* eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text */
  return <img ref={ref} {...props} />;
});

export default AppImage;
