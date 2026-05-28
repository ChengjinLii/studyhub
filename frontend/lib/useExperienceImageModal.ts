import { useEffect, useState } from 'react';
import { warmImages } from './imageWarmup';

export function useExperienceImageModal(images: string[]) {
  const [previewImageIndex, setPreviewImageIndex] = useState<number | null>(null);
  const [previewModalImageReady, setPreviewModalImageReady] = useState(false);

  useEffect(() => {
    if (previewImageIndex === null || typeof window === 'undefined') return;
    setPreviewModalImageReady(false);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPreviewImageIndex(null);
      }
    };
    const current = images[previewImageIndex];
    const prev = images[(previewImageIndex - 1 + images.length) % images.length];
    const next = images[(previewImageIndex + 1) % images.length];
    void warmImages([{ src: current }, { src: prev }, { src: next }]);
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [images, previewImageIndex]);

  const handlePreviewImagePrev = () => {
    if (previewImageIndex === null || images.length <= 1) return;
    setPreviewImageIndex((previewImageIndex - 1 + images.length) % images.length);
  };

  const handlePreviewImageNext = () => {
    if (previewImageIndex === null || images.length <= 1) return;
    setPreviewImageIndex((previewImageIndex + 1) % images.length);
  };

  return {
    previewImageIndex,
    previewModalImageReady,
    setPreviewModalImageReady,
    handleOpenExperienceImage: setPreviewImageIndex,
    handleCloseExperienceImage: () => setPreviewImageIndex(null),
    handlePreviewImagePrev,
    handlePreviewImageNext,
  };
}
