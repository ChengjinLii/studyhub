import { useEffect, useState } from 'react';
import { fetchMaterialPreview } from './api';
import { toErrorMessage } from './errors';
import { warmImages } from './imageWarmup';
import { MaterialDetail, MaterialPreview } from '../types/material';
import { SessionUser } from '../types/user';

interface UseMaterialPreviewOptions {
  material: MaterialDetail | null;
  user: SessionUser | null;
  isManualPreview: boolean;
  isPdfMaterial: boolean;
}

export function useMaterialPreview({
  material,
  user,
  isManualPreview,
  isPdfMaterial,
}: UseMaterialPreviewOptions) {
  const [preview, setPreview] = useState<MaterialPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [previewExpanded, setPreviewExpanded] = useState(false);
  const [previewPage, setPreviewPage] = useState(1);

  useEffect(() => {
    if (!previewExpanded) {
      return;
    }
    if (!material || !user) {
      setPreview(null);
      return;
    }
    if (!isManualPreview && !isPdfMaterial) {
      setPreview(null);
      return;
    }
    let active = true;
    setPreviewLoading(true);
    setPreviewError('');
    fetchMaterialPreview(material.id)
      .then((data) => {
        if (!active) return;
        setPreview(data);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setPreviewError(toErrorMessage(err, '预览加载失败'));
      })
      .finally(() => {
        if (!active) return;
        setPreviewLoading(false);
      });
    return () => {
      active = false;
    };
  }, [material, previewExpanded, user, isManualPreview, isPdfMaterial]);

  useEffect(() => {
    setPreviewPage(1);
  }, [preview?.images?.length]);

  useEffect(() => {
    if (!previewExpanded || !preview?.images?.length) {
      return;
    }
    const currentIndex = Math.max(0, previewPage - 1);
    const targets = [preview.images[currentIndex - 1], preview.images[currentIndex], preview.images[currentIndex + 1]]
      .filter((item): item is NonNullable<typeof item> => Boolean(item))
      .map((item) => ({
        src: item.img.src,
        srcSet: item.img.srcSet || undefined,
        sizes: item.img.sizes || undefined,
      }));
    void warmImages(targets);
  }, [previewExpanded, preview, previewPage]);

  const handlePreviewToggle = () => {
    setPreviewExpanded((prev) => {
      const next = !prev;
      if (next) {
        setPreviewPage(1);
      }
      return next;
    });
  };

  return {
    preview,
    previewLoading,
    previewError,
    previewExpanded,
    previewPage,
    setPreviewPage,
    handlePreviewToggle,
  };
}
