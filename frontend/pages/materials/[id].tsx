import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { CSSProperties, useCallback, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import NavBar from '../../components/NavBar';
import ShareSheet from '../../components/ShareSheet';
import CommentSection from '../../components/comments/CommentSection';
import StarRating from '../../components/StarRating';
import { readSession, hasRole } from '../../lib/auth';
import { fetchMaterialDetail, fetchMaterialPreview, recordMaterialView, reportTarget, setMaterialRating } from '../../lib/api';
import { fetchBackend } from '../../lib/apiBase';
import { formatDateTime } from '../../lib/format';
import { formatMajorDisplay } from '../../lib/major';
import { materialPath, parseMaterialId, slugifyTitle, userPath } from '../../lib/slug';
import { copyToClipboard, isLikelyMobile, tryNativeShare } from '../../lib/share';
import { getOrCreateViewerId, hasRecordedMaterialView, markMaterialViewRecorded } from '../../lib/viewer';
import { MaterialDetail, MaterialPreview } from '../../types/material';
import { SessionUser, RoleMask } from '../../types/user';
import { COURSE_CATEGORY_LABELS, CourseCategoryValue, normalizeCourseCategory } from '../../constants/metadata';
import PaginationBar from '../../components/PaginationBar';

interface MaterialDetailPageProps {
  material: MaterialDetail | null;
  user: SessionUser | null;
}

const extractExperienceLead = (value?: string | null) => {
  const trimmed = (value || '')
    .replace(/\[(.*?)\]\((.*?)\)/g, '$1')
    .replace(/[#>*_`~-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!trimmed) return '';
  if (trimmed.length <= 92) return trimmed;
  return `${trimmed.slice(0, 91)}…`;
};

export default function MaterialDetailPage({ material, user }: MaterialDetailPageProps) {
  const router = useRouter();
  const isOwner = Boolean(material && user && material.uploaderId === user.id);
  const isAdmin = Boolean(user && hasRole(user.roleMask, RoleMask.ADMIN));
  const isSuperAdmin = Boolean(user && hasRole(user.roleMask, RoleMask.DEVELOPER));
  const canManage = isOwner || isAdmin;
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
  const [myRating, setMyRating] = useState<number | null>(material?.myRating ?? null);
  const [ratingAvg, setRatingAvg] = useState(material?.ratingAvg ?? 0);
  const [ratingCount, setRatingCount] = useState(material?.ratingCount ?? 0);
  const [ratingSubmitting, setRatingSubmitting] = useState(false);
  const [autoDownloadTriggered, setAutoDownloadTriggered] = useState(false);
  const [preview, setPreview] = useState<MaterialPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [previewExpanded, setPreviewExpanded] = useState(false);
  const [previewPage, setPreviewPage] = useState(1);
  const [previewImageIndex, setPreviewImageIndex] = useState<number | null>(null);
  const previewPageSize = 1;
  const uploaderLabel = material?.uploaderNickname || material?.uploaderUsername || '匿名同学';
  const hasCustomPreview =
    Boolean(material?.customPreviewText?.trim()) || (material?.customPreviewImages?.length ?? 0) > 0;
  const isManualPreview = material?.previewSource === 'MANUAL';
  const isPdfMaterial = Boolean(material?.hasFile && material?.fileType?.toLowerCase() === 'pdf');
  const isExperienceMaterial = Boolean(material?.tags?.includes('经验分享'));
  const experienceImages = material?.customPreviewImages || [];
  const hasExperienceImages = experienceImages.length > 0;
  const experiencePlaceholder = user ? '暂无配图' : '登录后可查看配图（如作者已上传）';
  const hasPreviewContent = hasCustomPreview || isManualPreview || isPdfMaterial;
  const previewHint =
    hasCustomPreview && !isManualPreview && !isPdfMaterial
      ? '作者自定义预览'
      : preview?.previewPages
        ? `仅展示前 ${preview.previewPages} 页`
        : '仅供下载前浏览（前 3/5 页）';
  const copyrightOwner = material?.copyrightOwner?.trim();
  const formatFileSize = (value?: number | null) => {
    if (!value || value <= 0) return '--';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = value;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex += 1;
    }
    return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  };
  const canViewNetdisk = Boolean(material?.hasNetdisk && (material.netdiskAccessible || canManage));

  useEffect(() => {
    setPurchased(material ? material.free || material.purchased || canManage : false);
    setLiked(material?.liked ?? false);
    setLikeCount(material?.likeCount ?? 0);
    setViewCount(material?.viewCount ?? 0);
    setMyRating(material?.myRating ?? null);
    setRatingAvg(material?.ratingAvg ?? 0);
    setRatingCount(material?.ratingCount ?? 0);
  }, [material, canManage]);

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
      .catch((err: any) => {
        if (!active) return;
        setPreviewError(err?.message || '预览加载失败');
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

  const handlePreviewToggle = () => {
    setPreviewExpanded((prev) => {
      const next = !prev;
      if (next) {
        setPreviewPage(1);
      }
      return next;
    });
  };

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

  useEffect(() => {
    if (previewImageIndex === null || typeof window === 'undefined') return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPreviewImageIndex(null);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [previewImageIndex]);

  const handlePreviewImagePrev = () => {
    if (previewImageIndex === null || experienceImages.length <= 1) return;
    setPreviewImageIndex((previewImageIndex - 1 + experienceImages.length) % experienceImages.length);
  };

  const handlePreviewImageNext = () => {
    if (previewImageIndex === null || experienceImages.length <= 1) return;
    setPreviewImageIndex((previewImageIndex + 1) % experienceImages.length);
  };

  const notifyQuotaLimit = (message?: string) => {
    if (typeof window === 'undefined') return;
    window.alert(message || '下载次数已用完，如需继续下载请联系管理员重置额度。');
  };

  const handlePurchase = async () => {
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
      const resp = await fetchBackend('/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ materialId: material.id, channel: 'simulated' }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '下单失败');
      }
      setPurchased(true);
      setInfo('下单成功！已完成支付并标记为已支付，可立即下载。');
    } catch (err: any) {
      setError(err.message || '下单失败');
    } finally {
      setOrdering(false);
    }
  };

  const handleDownload = useCallback(async () => {
    if (!material) return;
    if (!ensureLoggedIn()) return;
    if (!material.free && !purchased) {
      setError('请先完成支付后再下载。');
      return;
    }
    setDownloading(true);
    setError('');
    setInfo('');
    try {
      const resp = await fetchBackend(`/materials/${material.id}/download`);
      const json = await resp.json();
      if (resp.status === 403 && json?.error?.code === 'DOWNLOAD_QUOTA_EXHAUSTED') {
        notifyQuotaLimit(json.msg);
      }
      if (!resp.ok || !json.ok || !json.data?.url) {
        throw new Error(json.msg || '获取下载链接失败');
      }
      const url = json.data.url;
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
      } else if (material.hasNetdisk) {
        setShowNetdiskLink(true);
        setInfo('下载链接已生成，请记得尊重知识创作者的辛勤付出，不要外传或用于商业用途哦~');
      }
    } catch (err: any) {
      setError(err.message || '下载失败');
    } finally {
      setDownloading(false);
    }
  }, [ensureLoggedIn, material, purchased]);

  const handleRatingChange = async (score: number) => {
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
    } catch (err: any) {
      setError(err.message || '评分失败');
    } finally {
      setRatingSubmitting(false);
    }
  };

  const formattedRatingAvg = Number(ratingAvg ?? 0).toFixed(1);
  const detailCommentCount = material?.commentCount ?? material?.reviews.length ?? 0;
  const experienceLead = extractExperienceLead(material?.description);
  const resolvedCategory: CourseCategoryValue = material
    ? normalizeCourseCategory(material.courseCategory, material.generalEducation)
    : 'MAJOR';
  const courseCategoryLabel = COURSE_CATEGORY_LABELS[resolvedCategory];
  const courseBreadcrumb =
    resolvedCategory === 'MAJOR'
      ? formatMajorDisplay(material?.major) || material?.college || '专业课'
      : courseCategoryLabel;

  useEffect(() => {
    if (!router.isReady || autoDownloadTriggered || !material) {
      return;
    }
    if (router.query.autoDownload === '1') {
      setAutoDownloadTriggered(true);
      const targetId = material.hasFile ? 'download-card' : material.hasNetdisk ? 'netdisk-card' : null;
      const proceed = async () => {
        if (material.hasFile) {
          await handleDownload();
        } else if (material.hasNetdisk) {
          setError('');
          setInfo('下载链接已生成，请记得尊重知识创作者的辛勤付出，不要外传或用于商业用途哦~');
        }
        if (targetId && typeof window !== 'undefined') {
          const el = document.getElementById(targetId);
          if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }
        try {
          await router.replace(materialPath(material.id, material.title), undefined, { shallow: true });
        } catch (err) {
          // ignore replace errors
        }
      };
      proceed();
    }
  }, [router, autoDownloadTriggered, material, handleDownload]);

  const handleToggleLike = async () => {
    if (!material) return;
    if (!ensureLoggedIn()) return;
    const optimistic = liked ? Math.max(0, likeCount - 1) : likeCount + 1;
    setLiked(!liked);
    setLikeCount(optimistic);
    try {
      const resp = await fetch(`/api/materials/${material.id}/like`, {
        method: liked ? 'DELETE' : 'POST',
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '操作失败');
      }
      if (typeof json.data === 'number') {
        setLikeCount(json.data);
      }
    } catch (err: any) {
      setLiked(liked);
      setLikeCount(likeCount);
      setError(err.message || '操作失败');
    }
  };

  const handleReport = async () => {
    if (!material) return;
    if (!ensureLoggedIn()) return;
    const reason = prompt('请输入举报理由（示例：侵权、广告、内容不实等）')?.trim();
    if (!reason) return;
    setError('');
    setInfo('');
    try {
      await reportTarget('MATERIAL', material.id, reason);
      setInfo('已收到举报，我们会尽快处理。');
    } catch (err: any) {
      setError(err.message || '举报失败');
    }
  };

  const handleShare = async () => {
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
        return;
      }
      setError('复制失败，请手动复制链接。');
    } catch (err: any) {
      setError(err?.message || '复制失败，请手动复制链接。');
    }
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container detail-container">
        {!material ? (
          <section className="card">
            <h2>未找到资料</h2>
            <p>该资料可能已下架或不存在。</p>
            <Link className="button primary" href="/">
              返回首页
            </Link>
          </section>
        ) : (
          <>
            <section className={`card detail-hero${isExperienceMaterial ? ' detail-hero--experience' : ''}`} id={isExperienceMaterial ? 'article-overview' : 'download-card'}>
              <div className="detail-main">
                {isExperienceMaterial ? (
                  <div className="experience-hero">
                    <div className="experience-hero__top-actions">
                      <button className="button ghost small" type="button" onClick={handleShare}>
                        <span className="button-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path
                              d="M7 12.5L16.6 7.8M7 11.5L16.6 16.2"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                            <circle
                              cx="6"
                              cy="12"
                              r="2.5"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                            />
                            <circle
                              cx="18"
                              cy="6"
                              r="2.5"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                            />
                            <circle
                              cx="18"
                              cy="18"
                              r="2.5"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                            />
                          </svg>
                        </span>
                        分享文章
                      </button>
                      <button className="button ghost small" type="button" onClick={handleToggleLike}>
                        <span className="button-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path
                              d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3z"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                            <path
                              d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        </span>
                        {liked ? '已点赞' : '点赞'}
                      </button>
                    </div>
                    <div className="experience-hero__eyebrow">
                      <span className="experience-hero__section">学汇专栏</span>
                      <span className="experience-hero__divider" aria-hidden="true" />
                      <span className="experience-hero__channel">经验心得</span>
                    </div>
                    <h1>{material.title}</h1>
                    {experienceLead && <p className="experience-hero__lead">{experienceLead}</p>}
                    <div className="experience-hero__facts">
                      {material.school && <span className="experience-hero__fact">{material.school}</span>}
                      {material.college && <span className="experience-hero__fact">{material.college}</span>}
                      {material.gradeValue && <span className="experience-hero__fact">{material.gradeValue}</span>}
                      {material.createdAt && <span className="experience-hero__fact">{formatDateTime(material.createdAt)} 发布</span>}
                      <span className="experience-hero__fact experience-hero__fact--author">
                        发布者：
                        {material?.uploaderId ? (
                          <Link className="experience-hero__fact-link" href={userPath(material.uploaderId, uploaderLabel)}>
                            {uploaderLabel}
                          </Link>
                        ) : (
                          <span className="experience-hero__fact-link">{uploaderLabel}</span>
                        )}
                      </span>
                    </div>
                    {copyrightOwner && (
                      <p className="material-meta experience-hero__copyright">版权持有者：{copyrightOwner}</p>
                    )}
                    <div className="material-tags material-tags--experience">
                      {material.tags
                        ?.filter((tag) => tag !== '经验分享')
                        .map((tag) => (
                          <Link key={tag} className="badge badge-outline" href={`/?tag=${encodeURIComponent(tag)}`}>
                            #{tag}
                          </Link>
                        ))}
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="breadcrumb">
                      {material.school} / {courseBreadcrumb}
                    </p>
                    <h1>{material.title}</h1>
                    <p className="material-meta">
                      发布者：
                      {material?.uploaderId ? (
                        <Link className="text-button" href={userPath(material.uploaderId, uploaderLabel)}>
                          {uploaderLabel}
                        </Link>
                      ) : (
                        uploaderLabel
                      )}
                    </p>
                    {copyrightOwner && (
                      <p className="material-meta">版权持有者：{copyrightOwner}</p>
                    )}
                  </>
                )}
                {!isExperienceMaterial &&
                  (material.description ? (
                    <div className="material-desc markdown-body">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{material.description}</ReactMarkdown>
                    </div>
                  ) : (
                    <p className="material-desc">投稿者暂无详细描述。</p>
                  ))}
                {!isExperienceMaterial && (
                  <div className="material-tags">
                    {resolvedCategory !== 'MAJOR' && <span className="badge badge-ghost">{courseCategoryLabel}</span>}
                    {material.gradeValue && <span className="badge">{material.gradeValue}</span>}
                    {material.tags?.map((tag) => (
                      <Link key={tag} className="badge badge-outline" href={`/?tag=${encodeURIComponent(tag)}`}>
                        #{tag}
                      </Link>
                    ))}
                  </div>
                )}
                {!isExperienceMaterial && (
                  <div className="rating-widget">
                    <StarRating
                      value={myRating ?? 0}
                      onChange={handleRatingChange}
                      readOnly={ratingSubmitting}
                      size={30}
                    />
                    <p>
                      平均 {formattedRatingAvg} / 5（{ratingCount} 人评分）{myRating ? ` · 我的评分 ${myRating} 星` : ''}
                    </p>
                  </div>
                )}
                {!isExperienceMaterial && (
                  <div className="detail-share">
                    <button className="button ghost small" type="button" onClick={handleShare}>
                      <span className="button-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M7 12.5L16.6 7.8M7 11.5L16.6 16.2"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                          <circle
                            cx="6"
                            cy="12"
                            r="2.5"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                          />
                          <circle
                            cx="18"
                            cy="6"
                            r="2.5"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                          />
                          <circle
                            cx="18"
                            cy="18"
                            r="2.5"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                          />
                        </svg>
                      </span>
                      分享链接
                    </button>
                  </div>
                )}
                {isExperienceMaterial && (
                  <>
                    <div className="experience-hero__inline-stats">
                      <span className="experience-hero__inline-stat">
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                          <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
                        </svg>
                        {viewCount} 阅读
                      </span>
                      <span className="experience-hero__inline-stat">
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3z"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                          <path
                            d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                        {likeCount} 点赞
                      </span>
                      <span className="experience-hero__inline-stat">
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                        {detailCommentCount} 评论
                      </span>
                    </div>
                    <div className="experience-hero__toolbar-minor">
                      <button className="text-button" type="button" onClick={handleReport}>
                        举报内容
                      </button>
                      {canManage && material && (
                        <Link className="text-button" href={`/upload?materialId=${material.id}`}>
                          编辑内容
                        </Link>
                      )}
                    </div>
                    {isExperienceMaterial && info && <p className="success-text">{info}</p>}
                    {isExperienceMaterial && error && <p className="error-text">{error}</p>}
                    {!user && (
                      <p className="help-text">
                        提示：<a className="login-link" href={`/login?next=${encodeURIComponent(router.asPath)}`}>登录</a>后可点赞与举报。
                      </p>
                    )}
                  </>
                )}
              </div>
              {!isExperienceMaterial && (
                <div className="detail-price-card">
                  <span className="price-tag detail">{material.free ? '免费' : `¥${material.price.toFixed(2)}`}</span>
                  <p>
                    下载：{material.downloadCount ?? 0} · 点赞：{likeCount} · 评论：
                    {material.commentCount ?? material.reviews.length}
                  </p>
                  {material.hasFile ? (
                    <p className="material-meta">
                      文件：{material.originalFilename || '未知'} · 大小：{formatFileSize(material.fileSize)} · 类型：
                      {material.fileType?.toUpperCase() || 'ZIP/PDF/Office 等'}
                    </p>
                  ) : (
                    <p className="material-meta">该资料通过网盘链接提供，购买后可查看链接。</p>
                  )}
                  {!material.free && !canManage && (
                    <button className="button primary" type="button" onClick={handlePurchase} disabled={ordering || purchased}>
                      {purchased ? '已下单' : ordering ? '下单中...' : '立即下单'}
                    </button>
                  )}
                  {material.hasFile && (
                    <button className="button ghost" type="button" onClick={handleDownload} disabled={downloading}>
                      {downloading ? '生成链接中...' : material.free ? '获取免费链接' : '获取下载链接'}
                    </button>
                  )}
                  <button className="button ghost" type="button" onClick={handleToggleLike}>
                    <span className="button-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path
                          d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3z"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                        <path
                          d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                    {liked ? '已点赞' : '点赞'}
                  </button>
                  <button className="button ghost" type="button" onClick={handleReport}>
                    <span className="button-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path
                          d="M12 3l9 16H3l9-16z"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                        <path
                          d="M12 9v4"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                        />
                        <circle cx="12" cy="17" r="1" fill="currentColor" />
                      </svg>
                    </span>
                    举报
                  </button>
                  {canManage && material && (
                    <Link className="button ghost" href={`/upload?materialId=${material.id}`}>
                      <span className="button-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M4 20l4-1 11-11-3-3-11 11-1 4z"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                          <path
                            d="M14 6l3 3"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </span>
                      编辑资料
                    </Link>
                  )}
                  {!user && (
                    <p className="help-text">
                      提示：<a className="login-link" href={`/login?next=${encodeURIComponent(router.asPath)}`}>登录</a>后可收藏、评分、下单与下载。
                    </p>
                  )}
                  {isAdmin && <p className="help-text">超级管理员可直接下载所有资料，无需支付。</p>}
                  {info && <p className="success-text">{info}</p>}
                  {downloadUrl && (
                    <p className="help-text">
                      如果浏览器未自动开始下载，可
                      <a href={downloadUrl} target="_blank" rel="noopener noreferrer">
                        点击此处
                      </a>
                      手动打开签名链接（15 分钟内有效）。
                    </p>
                  )}
                  {error && <p className="error-text">{error}</p>}
                </div>
              )}
            </section>

            {isExperienceMaterial ? (
              <section className="card experience-post" id="article-content">
                <div className="experience-post__body">
                  <div className="experience-post__meta">
                    <span className="experience-post__badge">经验分享</span>
                    {material.gradeValue && <span className="experience-post__chip">{material.gradeValue}</span>}
                    {material.tags
                      ?.filter((tag) => tag !== '经验分享')
                      .map((tag) => (
                        <Link key={tag} className="experience-post__chip" href={`/?tag=${encodeURIComponent(tag)}`}>
                          #{tag}
                        </Link>
                      ))}
                  </div>
                  {material.description ? (
                    <div className="experience-post__text markdown-body">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{material.description}</ReactMarkdown>
                    </div>
                  ) : (
                    <p className="help-text">投稿者暂无详细描述。</p>
                  )}
                </div>
                <div className="experience-post__carousel">
                  {hasExperienceImages ? (
                    <div className="experience-post__media-list">
                      {experienceImages.map((imageUrl, index) => (
                        <div className="experience-post__media" key={`${imageUrl}-${index}`}>
                          <img
                            src={imageUrl}
                            alt={`经验配图 ${index + 1}`}
                            loading={index === 0 ? 'eager' : 'lazy'}
                            onClick={() => setPreviewImageIndex(index)}
                          />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="experience-post__media">
                      <div className="experience-post__placeholder">
                        <span>{experiencePlaceholder}</span>
                        {!user && (
                          <Link className="button ghost small experience-post__login" href={`/login?next=${encodeURIComponent(router.asPath)}`}>
                            立即登录
                          </Link>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </section>
            ) : (
              <section className="card material-preview">
                <div className="material-preview__header">
                  <div className="material-preview__header-left">
                    <h2>资料预览</h2>
                    <span className="material-preview__hint">{previewHint}</span>
                  </div>
                  <button
                    type="button"
                    className="button ghost small material-preview__toggle"
                    onClick={handlePreviewToggle}
                  >
                    {previewExpanded ? '收起预览' : '展示预览'}
                  </button>
                </div>
                {!previewExpanded ? (
                  !hasPreviewContent ? (
                    <div className="material-preview__collapsed">
                      <p>当前资料暂不支持预览。</p>
                    </div>
                  ) : !user ? (
                    <div className="material-preview__collapsed">
                      <p>
                        <a className="login-link" href={`/login?next=${encodeURIComponent(router.asPath)}`}>登录</a>后可查看预览缩略图。
                      </p>
                      <Link className="button ghost small" href={`/login?next=${encodeURIComponent(router.asPath)}`}>
                        立即登录
                      </Link>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="material-preview__collapsed material-preview__collapsed-btn"
                      onClick={handlePreviewToggle}
                    >
                      点击查看预览
                    </button>
                  )
                ) : !user ? (
                  <div className="material-preview__locked">
                    <p>
                      <a className="login-link" href={`/login?next=${encodeURIComponent(router.asPath)}`}>登录</a>后可查看预览缩略图。
                    </p>
                    <Link className="button ghost small" href={`/login?next=${encodeURIComponent(router.asPath)}`}>
                      立即登录
                    </Link>
                  </div>
                ) : (
                  <>
                    {hasCustomPreview && (
                      <div className="material-custom-preview">
                        <div className="material-custom-preview__header">
                          <h3>作者自定义预览</h3>
                          <span className="material-custom-preview__hint">图文展示</span>
                        </div>
                        {material?.customPreviewText && (
                          <div className="material-custom-preview__text">{material.customPreviewText}</div>
                        )}
                        {material?.customPreviewImages && material.customPreviewImages.length > 0 && (
                          <div className="material-custom-preview__grid">
                            {material.customPreviewImages.map((url, index) => (
                              <img key={`${url}-${index}`} src={url} alt={`预览图 ${index + 1}`} loading="lazy" />
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                    {isManualPreview || isPdfMaterial ? (
                      previewLoading ? (
                        <p className="help-text">预览生成中，请稍候刷新。</p>
                      ) : previewError ? (
                        <p className="error-text">{previewError}</p>
                      ) : preview?.status === 'failed' ? (
                        <p className="help-text">预览生成失败，请稍后重试。</p>
                      ) : preview?.status === 'done' && preview.images.length > 0 ? (
                        <>
                          <div className="material-preview__grid">
                            {preview.images
                              .slice((previewPage - 1) * previewPageSize, previewPage * previewPageSize)
                              .map((item) => {
                                const lqipStyle = item.lqip
                                  ? ({ '--lqip': `url(${item.lqip})` } as CSSProperties)
                                  : undefined;
                                const hasLqip = Boolean(item.lqip);
                                return (
                                  <div
                                    key={item.index}
                                    className={`material-preview__page${hasLqip ? ' has-lqip' : ''}`}
                                    style={lqipStyle}
                                  >
                                    <picture>
                                      {item.avif?.srcSet && (
                                        <source
                                          type="image/avif"
                                          srcSet={item.avif.srcSet}
                                          sizes={item.avif.sizes || item.img.sizes || undefined}
                                        />
                                      )}
                                      {item.webp?.srcSet && (
                                        <source
                                          type="image/webp"
                                          srcSet={item.webp.srcSet}
                                          sizes={item.webp.sizes || item.img.sizes || undefined}
                                        />
                                      )}
                                      <img
                                        src={item.img.src}
                                        srcSet={item.img.srcSet || undefined}
                                        sizes={item.img.sizes || undefined}
                                        alt={`预览第 ${item.index} 页`}
                                        loading={previewPage === item.index ? 'eager' : 'lazy'}
                                        fetchPriority={previewPage === item.index ? 'high' : undefined}
                                      />
                                    </picture>
                                    <span className="material-preview__label">第 {item.index} 页</span>
                                  </div>
                                );
                              })}
                          </div>
                          <PaginationBar
                            currentPage={previewPage}
                            totalItems={preview.images.length}
                            pageSize={previewPageSize}
                            onPageChange={setPreviewPage}
                            className="materials-pagination material-preview__pagination"
                          />
                        </>
                      ) : (
                        <p className="help-text">预览生成中，请稍后刷新。</p>
                      )
                    ) : (
                      !hasCustomPreview && <p className="help-text">当前资料暂不支持预览。</p>
                    )}
                  </>
                )}
              </section>
            )}

            {material.hasNetdisk && !isExperienceMaterial && (
              <section className="card netdisk-card" id="netdisk-card">
                <h2>网盘资源</h2>
                {canViewNetdisk ? (
                  <>
                    {!showNetdiskLink && (
                      <button className="button primary" type="button" onClick={handleDownload} disabled={downloading}>
                        {downloading ? '处理中...' : '获取网盘链接'}
                      </button>
                    )}
                    {showNetdiskLink && (
                      <div className="netdisk-info">
                        <p className="netdisk-link">
                          链接：{downloadUrl || material.netdiskUrl || '暂无链接'}
                          {downloadUrl || material.netdiskUrl ? (
                            <button
                              type="button"
                              className="text-button"
                              onClick={() => navigator.clipboard.writeText(downloadUrl || material.netdiskUrl || '')}
                            >
                              复制
                            </button>
                          ) : null}
                          {downloadUrl || material.netdiskUrl ? (
                            <button
                              type="button"
                              className="button ghost small"
                              style={{ marginLeft: 8 }}
                              onClick={() => navigator.clipboard.writeText(downloadUrl || material.netdiskUrl || '')}
                            >
                              复制链接
                            </button>
                          ) : null}
                        </p>
                        {material.netdiskPassword && <p>提取码：{material.netdiskPassword}</p>}
                        {material.netdiskExpiredAt && <p>建议 {material.netdiskExpiredAt} 前检查链接有效性。</p>}
                        {material.netdiskReminderAt && (
                          <p className="help-text">投稿者备注提醒：{material.netdiskReminderAt}</p>
                        )}
                      </div>
                    )}
                  </>
                ) : (
                  <p className="help-text">包含付费资料，请下单完成后查看真实的网盘地址与提取码。</p>
                )}
              </section>
            )}

            <section className="card" id={isExperienceMaterial ? 'article-comments' : undefined}>
              <h2>版本与更新</h2>
              {material.versions.length === 0 ? (
                <p className="help-text">暂无版本信息。</p>
              ) : (
                <ul className="version-list">
                  {material.versions.map((version) => (
                    <li key={version.id}>
                      <strong>{version.versionLabel}</strong>
                      <span>{formatDateTime(version.createdAt)}</span>
                      <p>{version.changelog || '投稿者未填写更新说明。'}</p>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {material && (
              <CommentSection
                materialId={material.id}
                user={user}
                initialCount={material.commentCount ?? 0}
              />
            )}
          </>
        )}
      </main>
      <ShareSheet
        open={shareSheetOpen}
        title={shareSheetTitle}
        text={shareSheetText}
        linkUrl={shareSheetUrl}
        onClose={() => setShareSheetOpen(false)}
      />
      {isExperienceMaterial && previewImageIndex !== null && experienceImages[previewImageIndex] && (
        <div className="modal-mask" onClick={() => setPreviewImageIndex(null)}>
          <div
            className="modal-card experience-image-modal"
            role="dialog"
            aria-modal="true"
            aria-label="查看配图详情"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="modal-close"
              type="button"
              aria-label="关闭"
              onClick={() => setPreviewImageIndex(null)}
            >
              ×
            </button>
            {experienceImages.length > 1 && (
              <>
                <button
                  type="button"
                  className="experience-image-modal__arrow left"
                  aria-label="查看上一张图片"
                  onClick={handlePreviewImagePrev}
                >
                  ‹
                </button>
                <button
                  type="button"
                  className="experience-image-modal__arrow right"
                  aria-label="查看下一张图片"
                  onClick={handlePreviewImageNext}
                >
                  ›
                </button>
              </>
            )}
            <img src={experienceImages[previewImageIndex]} alt={`经验配图大图 ${previewImageIndex + 1}`} />
            <div className="experience-image-modal__meta">
              第 {previewImageIndex + 1} / {experienceImages.length} 张
            </div>
          </div>
        </div>
      )}
      <style jsx>{`
        .rating-widget {
          margin-top: 12px;
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .rating-widget p {
          margin: 0;
          color: var(--text-muted);
        }
      `}</style>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<MaterialDetailPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const { id } = ctx.query;
  if (!id || Array.isArray(id)) {
    return { notFound: true };
  }
  const materialId = parseMaterialId(id);
  if (!materialId) {
    return { notFound: true };
  }
  let material: MaterialDetail | null = null;
  try {
    material = await fetchMaterialDetail(materialId, session.token || undefined);
  } catch (error) {
    // eslint-disable-next-line no-console
    console.warn('Failed to fetch material detail', error);
  }
  if (material) {
    const slug = slugifyTitle(material.title);
    const canonicalId = slug ? `${material.id}-${slug}` : String(material.id);
    if (id !== canonicalId) {
      const resolvedUrl = ctx.resolvedUrl || '';
      const queryString = resolvedUrl.includes('?') ? resolvedUrl.split('?')[1] : '';
      const destination = queryString
        ? `/materials/${canonicalId}?${queryString}`
        : `/materials/${canonicalId}`;
      return {
        redirect: {
          destination,
          permanent: true,
        },
      };
    }
  }
  return {
    props: {
      material,
      user: session.user,
    },
  };
};
