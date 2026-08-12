import { NextRouter } from 'next/router';
import { useCallback, useEffect, useState } from 'react';
import { recordMaterialView, reportTarget, setMaterialRating } from './api';
import { ApiError } from './apiEnvelope';
import { createSimulatedMaterialOrder, fetchMaterialDownloadLink, toggleMaterialLike } from './materialsApi';
import { toErrorMessage } from './errors';
import { materialPath } from './slug';
import { copyToClipboard, isLikelyMobile, tryNativeShare } from './share';
import { getOrCreateViewerId, hasRecordedMaterialView, markMaterialViewRecorded } from './viewer';
import { useAppDialog } from '../components/AppDialogProvider';
import { useAppToast } from '../components/AppToastProvider';
import { MaterialDetail } from '../types/material';
import { SessionUser } from '../types/user';

interface UseMaterialActionsOptions {
  material: MaterialDetail | null;
  user: SessionUser | null;
  canManage: boolean;
  isSuperAdmin: boolean;
  router: NextRouter;
}

export const useMaterialActions = ({
  material,
  user,
  canManage,
  isSuperAdmin,
  router,
}: UseMaterialActionsOptions) => {
  const dialog = useAppDialog();
  const toast = useAppToast();
  const [purchased, setPurchased] = useState(
    material ? material.free || material.purchased || canManage : false
  );
  const [liked, setLiked] = useState(material?.liked ?? false);
  const [likeCount, setLikeCount] = useState(material?.likeCount ?? 0);
  const [viewCount, setViewCount] = useState(material?.viewCount ?? 0);
  const [info, setInfo] = useState('');
  const [error, setError] = useState('');
  const [shareSheetOpen, setShareSheetOpen] = useState(false);
  const [shareSheetTitle, setShareSheetTitle] = useState('');
  const [shareSheetText, setShareSheetText] = useState('');
  const [shareSheetUrl, setShareSheetUrl] = useState('');
  const [ordering, setOrdering] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [showNetdiskLink, setShowNetdiskLink] = useState(false);
  const [netdiskModalOpen, setNetdiskModalOpen] = useState(false);
  const [myRating, setMyRating] = useState<number | null>(material?.myRating ?? null);
  const [ratingAvg, setRatingAvg] = useState(material?.ratingAvg ?? 0);
  const [ratingCount, setRatingCount] = useState(material?.ratingCount ?? 0);
  const [ratingSubmitting, setRatingSubmitting] = useState(false);
  const [likeSubmitting, setLikeSubmitting] = useState(false);

  useEffect(() => {
    setPurchased(material ? material.free || material.purchased || canManage : false);
    setLiked(material?.liked ?? false);
    setLikeCount(material?.likeCount ?? 0);
    setViewCount(material?.viewCount ?? 0);
    setMyRating(material?.myRating ?? null);
    setRatingAvg(material?.ratingAvg ?? 0);
    setRatingCount(material?.ratingCount ?? 0);
    setDownloadUrl(null);
    setShowNetdiskLink(false);
    setNetdiskModalOpen(false);
  }, [material, canManage]);

  useEffect(() => {
    if (!material?.id || typeof window === 'undefined') {
      return;
    }
    const viewerId = getOrCreateViewerId();
    if (!viewerId || hasRecordedMaterialView(material.id, viewerId)) {
      return;
    }
    let active = true;
    recordMaterialView(material.id, viewerId)
      .then((data) => {
        if (!active) return;
        if (typeof data?.viewCount === 'number') {
          setViewCount(data.viewCount);
        }
        markMaterialViewRecorded(material.id, viewerId);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [material?.id]);

  const ensureLoggedIn = useCallback(() => {
    if (!user) {
      router.push({
        pathname: '/login',
        query: { next: router.asPath },
      });
      return false;
    }
    return true;
  }, [router, user]);

  const handleDownload = useCallback(async () => {
    if (!material) return;
    if (!ensureLoggedIn()) return;
    if (!material.free && !purchased) {
      const message = '请先完成支付后再下载。';
      setError(message);
      toast.show(message, { tone: 'warning' });
      return;
    }
    if (material.hasNetdisk && showNetdiskLink && downloadUrl) {
      setNetdiskModalOpen(true);
      toast.show('网盘链接已准备好', { tone: 'info' });
      return;
    }
    const toastId = toast.show(
      material.hasNetdisk ? '正在获取网盘链接…' : '正在生成下载链接…',
      { id: `material-download-${material.id}`, tone: 'loading' }
    );
    setDownloading(true);
    setError('');
    setInfo('');
    try {
      const data = await fetchMaterialDownloadLink(material.id);
      const url = data.url;
      setDownloadUrl(url);
      setPurchased(true);
      if (material.hasFile) {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.target = '_self';
        anchor.rel = 'noopener noreferrer';
        anchor.style.display = 'none';
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        setInfo('下载链接已生成，请记得尊重知识创作者的辛勤付出，不要外传或用于商业用途哦~');
        toast.show('下载已开始', { id: toastId, tone: 'success' });
      } else if (material.hasNetdisk) {
        setShowNetdiskLink(true);
        setNetdiskModalOpen(true);
        setInfo('下载链接已生成，请记得尊重知识创作者的辛勤付出，不要外传或用于商业用途哦~');
        toast.show('网盘链接已获取', { id: toastId, tone: 'success' });
      }
    } catch (err: unknown) {
      if (err instanceof ApiError && err.code === 'DOWNLOAD_QUOTA_EXHAUSTED') {
        void dialog.alert({
          title: '下载次数已用完',
          message: err.message || '下载次数已用完，如需继续下载请联系管理员重置额度。',
        });
      }
      const message = toErrorMessage(err, '下载失败');
      setError(message);
      toast.show(message, { id: toastId, tone: 'error' });
    } finally {
      setDownloading(false);
    }
  }, [dialog, downloadUrl, ensureLoggedIn, material, purchased, showNetdiskLink, toast]);

  const handlePurchase = useCallback(async () => {
    if (!material) return;
    if (material.free) {
      return handleDownload();
    }
    if (!ensureLoggedIn()) return;
    if (!isSuperAdmin) {
      router.push(`/pay/${material.id}`);
      return;
    }
    setOrdering(true);
    setError('');
    setInfo('');
    try {
      await createSimulatedMaterialOrder(material.id);
      setPurchased(true);
      setInfo('下单成功！已完成支付并标记为已支付，可立即下载。');
    } catch (err: unknown) {
      setError(toErrorMessage(err, '下单失败'));
    } finally {
      setOrdering(false);
    }
  }, [ensureLoggedIn, handleDownload, isSuperAdmin, material, router]);

  const handleRatingChange = useCallback(async (score: number) => {
    if (!material) return;
    if (!ensureLoggedIn()) return;
    setRatingSubmitting(true);
    setError('');
    setInfo('');
    try {
      const resp = await setMaterialRating(material.id, score);
      setMyRating(score);
      setRatingAvg(Number(resp.ratingAvg ?? 0));
      setRatingCount(resp.ratingCount ?? 0);
      setInfo('评分提交成功！');
    } catch (err: unknown) {
      setError(toErrorMessage(err, '评分失败'));
    } finally {
      setRatingSubmitting(false);
    }
  }, [ensureLoggedIn, material]);

  const handleToggleLike = useCallback(async () => {
    if (!material) return;
    if (!ensureLoggedIn()) return;
    if (likeSubmitting) return;
    const nextLiked = !liked;
    const toastId = toast.show(nextLiked ? '正在点赞…' : '正在取消点赞…', {
      id: `material-like-${material.id}`,
      tone: 'loading',
    });
    const optimistic = liked ? Math.max(0, likeCount - 1) : likeCount + 1;
    setLikeSubmitting(true);
    setLiked(nextLiked);
    setLikeCount(optimistic);
    try {
      const nextLikeCount = await toggleMaterialLike(material.id, liked);
      if (typeof nextLikeCount === 'number') {
        setLikeCount(nextLikeCount);
      }
      toast.show(nextLiked ? '已点赞' : '已取消点赞', { id: toastId, tone: 'success' });
    } catch (err: unknown) {
      setLiked(liked);
      setLikeCount(likeCount);
      const message = toErrorMessage(err, '操作失败');
      setError(message);
      toast.show(message, { id: toastId, tone: 'error' });
    } finally {
      setLikeSubmitting(false);
    }
  }, [ensureLoggedIn, likeSubmitting, liked, likeCount, material, toast]);

  const handleReport = useCallback(async () => {
    if (!material) return;
    if (!ensureLoggedIn()) return;
    const reason = (
      await dialog.prompt({
        title: '举报资料',
        message: '请输入举报理由。',
        placeholder: '示例：侵权、广告、内容不实等',
        multiline: true,
        confirmText: '提交举报',
      })
    )?.trim();
    if (!reason) return;
    setError('');
    setInfo('');
    try {
      await reportTarget('MATERIAL', material.id, reason);
      setInfo('已收到举报，我们会尽快处理。');
    } catch (err: unknown) {
      setError(toErrorMessage(err, '举报失败'));
    }
  }, [dialog, ensureLoggedIn, material]);

  const handleShare = useCallback(async () => {
    if (!material) return;
    setError('');
    try {
      const sharePath = materialPath(material.id, material.title);
      const shareUrl = typeof window === 'undefined' ? sharePath : `${window.location.origin}${sharePath}`;
      const shareTitle = material.title || 'StudyHub 资料';
      const shareText = `${shareTitle}\n${shareUrl}`;
      if (isLikelyMobile()) {
        const shared = await tryNativeShare({ title: shareTitle, text: shareText, url: shareUrl });
        if (shared) {
          setInfo('已唤起系统分享。');
          toast.show('已唤起系统分享', { tone: 'success' });
          return;
        }
        setShareSheetTitle('分享资料');
        setShareSheetText(shareText);
        setShareSheetUrl(shareUrl);
        setShareSheetOpen(true);
        return;
      }
      const copied = await copyToClipboard(shareUrl);
      if (copied) {
        setInfo('资料链接已复制，可以直接分享给同学。');
        toast.show('资料链接已复制', { tone: 'success' });
        return;
      }
      setError('复制失败，请手动复制链接。');
      toast.show('复制失败，请手动复制链接。', { tone: 'error' });
    } catch (err: unknown) {
      const message = toErrorMessage(err, '复制失败，请手动复制链接。');
      setError(message);
      toast.show(message, { tone: 'error' });
    }
  }, [material, toast]);

  return {
    purchased,
    liked,
    likeCount,
    viewCount,
    info,
    error,
    shareSheetOpen,
    setShareSheetOpen,
    shareSheetTitle,
    shareSheetText,
    shareSheetUrl,
    ordering,
    downloading,
    downloadUrl,
    showNetdiskLink,
    netdiskModalOpen,
    setNetdiskModalOpen,
    myRating,
    ratingAvg,
    ratingCount,
    ratingSubmitting,
    likeSubmitting,
    handlePurchase,
    handleDownload,
    handleRatingChange,
    handleToggleLike,
    handleReport,
    handleShare,
  };
};
