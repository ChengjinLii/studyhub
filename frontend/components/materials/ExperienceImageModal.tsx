import AppImage from '../AppImage';

interface ExperienceImageModalProps {
  images: string[];
  currentIndex: number | null;
  imageReady: boolean;
  onImageReady: () => void;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
}

export default function ExperienceImageModal({
  images,
  currentIndex,
  imageReady,
  onImageReady,
  onClose,
  onPrev,
  onNext,
}: ExperienceImageModalProps) {
  if (currentIndex === null || !images[currentIndex]) {
    return null;
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div
        className="modal-card experience-image-modal"
        role="dialog"
        aria-modal="true"
        aria-label="查看配图详情"
        onClick={(event) => event.stopPropagation()}
      >
        <button className="modal-close" type="button" aria-label="关闭" onClick={onClose}>
          ×
        </button>
        {images.length > 1 && (
          <>
            <button
              type="button"
              className="experience-image-modal__arrow left"
              aria-label="查看上一张图片"
              onClick={onPrev}
            >
              ‹
            </button>
            <button
              type="button"
              className="experience-image-modal__arrow right"
              aria-label="查看下一张图片"
              onClick={onNext}
            >
              ›
            </button>
          </>
        )}
        <div className={`experience-image-modal__frame${imageReady ? ' is-ready' : ' is-loading'}`}>
          {!imageReady && <div className="experience-image-modal__loading">高清图加载中...</div>}
          <AppImage
            src={images[currentIndex]}
            alt={`经验配图大图 ${currentIndex + 1}`}
            decoding="async"
            onLoad={onImageReady}
          />
        </div>
        <div className="experience-image-modal__meta">
          第 {currentIndex + 1} / {images.length} 张
        </div>
      </div>
    </div>
  );
}
