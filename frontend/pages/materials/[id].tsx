import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useEffect, useMemo, useState } from 'react';
import AppImage from '../../components/AppImage';
import ExperienceImageModal from '../../components/materials/ExperienceImageModal';
import MaterialPreviewPanel from '../../components/materials/MaterialPreviewPanel';
import NetdiskAccessModal from '../../components/materials/NetdiskAccessModal';
import NavBar from '../../components/NavBar';
import SafeMarkdown from '../../components/SafeMarkdown';
import ShareSheet from '../../components/ShareSheet';
import CommentSection from '../../components/comments/CommentSection';
import StarRating from '../../components/StarRating';
import MaterialIconSprite from '../../components/MaterialIconSprite';
import styles from '../../styles/MaterialDetail.module.css';
import { useMobileBottomBar } from '../../components/mobile/MobileBottomBarProvider';
import { readSession, hasRole } from '../../lib/auth';
import { fetchMaterialDetail } from '../../lib/api';
import { getRequestOrigin } from '../../lib/apiBase';
import { formatDateTime } from '../../lib/format';
import { formatMajorDisplay } from '../../lib/major';
import { materialPath, parseMaterialId, slugifyTitle, userPath } from '../../lib/slug';
import { useExperienceImageModal } from '../../lib/useExperienceImageModal';
import { useMaterialActions } from '../../lib/useMaterialActions';
import { useMaterialPreview } from '../../lib/useMaterialPreview';
import { MaterialDetail } from '../../types/material';
import { SessionUser, RoleMask } from '../../types/user';
import { COURSE_CATEGORY_LABELS, CourseCategoryValue, normalizeCourseCategory } from '../../constants/metadata';

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
  const { setDetailActions } = useMobileBottomBar();
  const isOwner = Boolean(material && user && material.uploaderId === user.id);
  const isAdmin = Boolean(user && hasRole(user.roleMask, RoleMask.ADMIN));
  const isSuperAdmin = Boolean(user && hasRole(user.roleMask, RoleMask.DEVELOPER));
  const canManage = isOwner || isAdmin;
  const {
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
  } = useMaterialActions({ material, user, canManage, isSuperAdmin, router });
  const [autoDownloadTriggered, setAutoDownloadTriggered] = useState(false);
  const [contentTab, setContentTab] = useState<'preview' | 'comments'>('preview');
  const previewPageSize = 1;
  const uploaderLabel = material?.uploaderNickname || material?.uploaderUsername || '匿名同学';
  const hasCustomPreview = Boolean(material?.customPreviewText?.trim()) || (material?.customPreviewImages?.length ?? 0) > 0;
  const isManualPreview = Boolean(material?.previewSource === 'MANUAL');
  const isPdfMaterial = Boolean(material?.hasFile && material?.fileType?.toLowerCase() === 'pdf');
  const isExperienceMaterial = Boolean(material?.tags?.includes('经验分享'));
  const securityScanStatus = material?.securityScanStatus ?? null;
  const securityScanBlocked = Boolean(securityScanStatus && securityScanStatus !== 'CLEAN');

  useEffect(() => {
    if (!material || isExperienceMaterial) {
      setDetailActions(null);
      return;
    }
    const shouldPurchase = !material.free && !canManage && !purchased;
    const canDownload = (material.hasFile || material.hasNetdisk) && !securityScanBlocked;
    const primaryLabel = shouldPurchase
      ? ordering
        ? '下单中...'
        : '立即下单'
      : !canDownload
        ? securityScanBlocked
          ? securityScanStatus === 'INFECTED'
            ? '文件未通过安全检查'
            : '安全检查中'
          : '暂不可获取'
        : downloading
          ? material.hasNetdisk
            ? '处理中...'
            : '生成链接中...'
          : material.hasNetdisk
            ? '获取网盘链接'
            : material.free
              ? '获取免费链接'
              : '获取下载链接';
    setDetailActions({
      liked,
      likeDisabled: likeSubmitting,
      primaryLabel,
      primaryDisabled: shouldPurchase ? ordering : downloading || !canDownload,
      onLike: handleToggleLike,
      onPrimary: shouldPurchase ? handlePurchase : handleDownload,
    });
    return () => setDetailActions(null);
  }, [
    canManage,
    downloading,
    handleDownload,
    handlePurchase,
    handleToggleLike,
    isExperienceMaterial,
    likeSubmitting,
    liked,
    material,
    ordering,
    purchased,
    securityScanBlocked,
    securityScanStatus,
    setDetailActions,
  ]);
  const experienceImages = useMemo(() => material?.customPreviewImages ?? [], [material?.customPreviewImages]);
  const hasExperienceImages = experienceImages.length > 0;
  const experiencePlaceholder = user ? '暂无配图' : '登录后可查看配图（如作者已上传）';
  const hasPreviewContent = hasCustomPreview || isManualPreview || isPdfMaterial;
  const previewState = useMaterialPreview({ material, user, isManualPreview, isPdfMaterial });
  const imageModal = useExperienceImageModal(experienceImages);
  const previewHint =
    hasCustomPreview && !isManualPreview && !isPdfMaterial
      ? '作者自定义预览'
      : previewState.preview?.previewPages
        ? `仅展示前 ${previewState.preview.previewPages} 页`
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

  const formattedRatingAvg = Number(ratingAvg ?? 0).toFixed(1);
  const detailCommentCount = material?.commentCount ?? material?.reviews.length ?? 0;
  const experienceLead = extractExperienceLead(material?.description);
  const resolvedCategory: CourseCategoryValue = material
    ? normalizeCourseCategory(material.courseCategory, material.generalEducation)
    : 'MAJOR';
  const courseCategoryLabel = COURSE_CATEGORY_LABELS[resolvedCategory];
  const courseBreadcrumb =
    resolvedCategory === 'MAJOR' ? formatMajorDisplay(material?.major) || material?.college || '专业课' : courseCategoryLabel;

  useEffect(() => {
    if (!router.isReady || autoDownloadTriggered || !material) {
      return;
    }
    if (router.query.autoDownload === '1') {
      setAutoDownloadTriggered(true);
      const targetId = material.hasFile || material.hasNetdisk ? 'download-card' : null;
      const proceed = async () => {
        if (material.hasFile) {
          await handleDownload();
        } else if (material.hasNetdisk) {
          await handleDownload();
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

  return (
    <>
      <NavBar user={user} />
      <MaterialIconSprite />
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
            {!isExperienceMaterial && (
              <nav className={styles.returnNav} aria-label="资料导航">
                <Link href="/materials">返回资料库</Link>
                <span aria-hidden="true">/</span>
                <span>资料详情</span>
              </nav>
            )}
            <section
              className={isExperienceMaterial ? 'card detail-hero detail-hero--experience' : styles.sheet}
              id={isExperienceMaterial ? 'article-overview' : 'download-card'}
            >
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
                            <circle cx="6" cy="12" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                            <circle cx="18" cy="6" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                            <circle cx="18" cy="18" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                          </svg>
                        </span>
                        分享文章
                      </button>
                      <button className="button ghost small" type="button" onClick={handleToggleLike} disabled={likeSubmitting}>
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
                    {copyrightOwner && <p className="material-meta experience-hero__copyright">版权持有者：{copyrightOwner}</p>}
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
                  <div className={styles.reading}>
                    <div className={styles.header}>
                      <div className={styles.metadata}>
                        {material.school && <span>{material.school}</span>}
                        <span>{courseBreadcrumb}</span>
                        {material.gradeValue && <span>{material.gradeValue}</span>}
                      </div>
                      <h1>{material.title}</h1>
                      <div className={styles.byline}>
                        <span className={styles.avatar} aria-hidden="true">
                          {Array.from(uploaderLabel)[0]}
                        </span>
                        <span>
                          {material?.uploaderId ? (
                            <Link className="text-button" href={userPath(material.uploaderId, uploaderLabel)}>
                              {uploaderLabel}
                            </Link>
                          ) : (
                            uploaderLabel
                          )}
                        </span>
                        <span className={styles.bylineLabel}>发布的资料</span>
                        {copyrightOwner && <span>版权持有者：{copyrightOwner}</span>}
                      </div>
                    </div>
                    <section className={styles.description} aria-label="资料简介">
                      <h2>资料简介</h2>
                      {material.description ? (
                        <div className="markdown-body">
                          <SafeMarkdown>{material.description}</SafeMarkdown>
                        </div>
                      ) : (
                        <p>投稿者暂无详细描述。</p>
                      )}
                    </section>
                    <div className={styles.tags}>
                      {material.tags?.map((tag) => (
                        <Link key={tag} href={`/?tag=${encodeURIComponent(tag)}`}>
                          #{tag}
                        </Link>
                      ))}
                    </div>
                    <div className={styles.footer}>
                      <div className={styles.rating}>
                        <StarRating value={myRating ?? 0} onChange={handleRatingChange} readOnly={ratingSubmitting} size={20} />
                        <p>
                          {ratingCount ? `${formattedRatingAvg} / 5 · ${ratingCount} 人评分` : '暂无评分 · 0 人评价'}
                          {myRating ? ` · 我的评分 ${myRating} 星` : ''}
                        </p>
                      </div>
                      <div className={styles.share}>
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
                              <circle cx="6" cy="12" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                              <circle cx="18" cy="6" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                              <circle cx="18" cy="18" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                            </svg>
                          </span>
                          分享
                        </button>
                      </div>
                    </div>
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
                        提示：
                        <a className="login-link" href={`/login?next=${encodeURIComponent(router.asPath)}`}>
                          登录
                        </a>
                        后可点赞与举报。
                      </p>
                    )}
                  </>
                )}
              </div>
              {!isExperienceMaterial && (
                <aside className={styles.access} aria-label="资料获取">
                  <div className={styles.summary}>
                    <div className={styles.priceGroup}>
                      <span className={styles.eyebrow}>{material.free ? '公开资料' : '付费资料'}</span>
                      <span className={`${styles.price}${material.free ? ` ${styles.free}` : ''}`}>
                        {material.free ? '免费' : `¥${material.price.toFixed(2)}`}
                      </span>
                      <span className={styles.priceCaption}>
                        {material.free ? '由创作者免费分享' : purchased && !canManage ? '已购买，可直接获取' : '一次购买，获取这份资料'}
                      </span>
                    </div>
                    <span className={styles.deliveryType}>
                      {material.hasFile ? '站内文件' : material.hasNetdisk ? '网盘交付' : '暂无交付文件'}
                    </span>
                  </div>
                  {material.hasFile ? (
                    <div className={styles.file}>
                      <span className={styles.fileLabel}>文件</span>
                      <p>{material.originalFilename || '未知'}</p>
                      <span className="material-meta">
                        {formatFileSize(material.fileSize)} · {material.fileType?.toUpperCase() || 'ZIP/PDF/Office 等'}
                      </span>
                    </div>
                  ) : (
                    <div className={styles.file}>
                      <span className={styles.fileLabel}>网盘</span>
                      <p>{material.hasNetdisk ? '网盘资源' : '暂未提供交付内容'}</p>
                      {material.hasNetdisk && <span className="material-meta">网盘链接 · 提取码（如有）</span>}
                    </div>
                  )}
                  {securityScanBlocked && (
                    <div className={`detail-security-status detail-security-status--${securityScanStatus?.toLowerCase()}`} role="status">
                      <strong>
                        {securityScanStatus === 'INFECTED'
                          ? '文件未通过安全检查'
                          : securityScanStatus === 'ERROR'
                            ? '安全检查暂未完成'
                            : '文件安全检查中'}
                      </strong>
                      <span>
                        {securityScanStatus === 'INFECTED' ? '该文件已被隔离，无法下载。' : '检查通过后会自动开放，无需重复投稿。'}
                      </span>
                    </div>
                  )}
                  {((!material.free && !canManage) || material.hasFile || material.hasNetdisk) && (
                    <div className={styles.actions}>
                      {!material.free && !canManage && !purchased && (
                        <button
                          className="button primary detail-action-order"
                          type="button"
                          onClick={handlePurchase}
                          disabled={ordering || purchased}
                        >
                          {purchased ? '已下单' : ordering ? '下单中...' : '立即下单'}
                        </button>
                      )}
                      {(material.hasFile || material.hasNetdisk) && (material.free || canManage || purchased) && (
                        <button
                          className={`button detail-action-download ${material.free || canManage || purchased ? 'primary' : 'ghost'}`}
                          type="button"
                          onClick={handleDownload}
                          disabled={downloading || securityScanBlocked}
                        >
                          <span className="button-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24"><use href="#studyhub-material-icon-download" /></svg>
                          </span>
                          {securityScanBlocked
                            ? securityScanStatus === 'INFECTED'
                              ? '文件已隔离'
                              : '安全检查中'
                            : downloading
                              ? material.hasNetdisk
                                ? '处理中...'
                                : '生成链接中...'
                              : material.hasNetdisk
                                ? '获取网盘链接'
                                : material.free
                                  ? '获取免费链接'
                                  : '获取下载链接'}
                        </button>
                      )}
                    </div>
                  )}
                  <p className={styles.actionNote}>
                    {material.free || canManage || purchased
                      ? material.hasFile
                        ? '文件由创作者上传至 StudyHub'
                        : '链接及提取码由发布者提供'
                      : '通过支付宝完成支付'}
                  </p>
                  <div className={styles.stats} aria-label="资料数据">
                    <span className={styles.stat}>
                      <strong>{material.downloadCount ?? 0}</strong>
                      <span>下载</span>
                    </span>
                    <span className={styles.stat}>
                      <strong>{likeCount}</strong>
                      <span>点赞</span>
                    </span>
                    <span className={styles.stat}>
                      <strong>{material.commentCount ?? material.reviews.length}</strong>
                      <span>评论</span>
                    </span>
                  </div>
                  <div className={styles.secondary}>
                    <button
                      className={`button ghost detail-action-like${liked ? ' is-active' : ''}`}
                      type="button"
                      onClick={handleToggleLike}
                      disabled={likeSubmitting}
                      aria-pressed={liked}
                    >
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
                    <button className="button ghost detail-action-report" type="button" onClick={handleReport}>
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
                          <path d="M12 9v4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                          <circle cx="12" cy="17" r="1" fill="currentColor" />
                        </svg>
                      </span>
                      举报
                    </button>
                    {canManage && material && (
                      <Link className="button ghost detail-action-edit" href={`/upload?materialId=${material.id}`}>
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
                  </div>
                  {material.hasNetdisk && showNetdiskLink && (
                    <button type="button" className={styles.reopen} onClick={() => setNetdiskModalOpen(true)}>
                      再次查看网盘链接
                    </button>
                  )}
                  {!user && (
                    <p className="help-text detail-price-card__note">
                      提示：
                      <a className="login-link" href={`/login?next=${encodeURIComponent(router.asPath)}`}>
                        登录
                      </a>
                      后可收藏、评分、下单与下载。
                    </p>
                  )}
                  {info && <p className="success-text">{info}</p>}
                  {material.hasFile && downloadUrl && (
                    <p className="help-text detail-price-card__note">
                      如果浏览器未自动开始下载，可
                      <a href={downloadUrl} target="_blank" rel="noopener noreferrer">
                        点击此处
                      </a>
                      手动打开签名链接（15 分钟内有效）。
                    </p>
                  )}
                  {error && <p className="error-text">{error}</p>}
                </aside>
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
                      <SafeMarkdown>{material.description}</SafeMarkdown>
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
                          <AppImage
                            src={imageUrl}
                            alt={`经验配图 ${index + 1}`}
                            decoding="async"
                            loading={index === 0 ? 'eager' : 'lazy'}
                            onClick={() => imageModal.handleOpenExperienceImage(index)}
                          />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="experience-post__media">
                      <div className="experience-post__placeholder">
                        <span>{experiencePlaceholder}</span>
                        {!user && (
                          <Link
                            className="button ghost small experience-post__login"
                            href={`/login?next=${encodeURIComponent(router.asPath)}`}
                          >
                            立即登录
                          </Link>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </section>
            ) : (
              <section className={styles.content} aria-label="资料内容">
                <div className={styles.tabs} role="tablist" aria-label="预览与评论">
                  {(['preview', 'comments'] as const).map((tab) => (
                    <button
                      key={tab}
                      type="button"
                      role="tab"
                      id={`material-${tab}-tab`}
                      aria-controls={`material-${tab}-panel`}
                      aria-selected={contentTab === tab}
                      tabIndex={contentTab === tab ? 0 : -1}
                      onClick={() => setContentTab(tab)}
                      onKeyDown={(event) => {
                        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
                          event.preventDefault();
                          const next =
                            event.key === 'Home'
                              ? 'preview'
                              : event.key === 'End'
                                ? 'comments'
                                : tab === 'preview'
                                  ? 'comments'
                                  : 'preview';
                          setContentTab(next);
                          document.getElementById(`material-${next}-tab`)?.focus();
                        }
                      }}
                    >
                      {tab === 'preview' ? (
                        '资料预览'
                      ) : (
                        <>
                          评论 <small>{detailCommentCount}</small>
                        </>
                      )}
                    </button>
                  ))}
                </div>
                <div role="tabpanel" id="material-preview-panel" aria-labelledby="material-preview-tab" hidden={contentTab !== 'preview'}>
                  <MaterialPreviewPanel
                    embedded
                    material={material}
                    user={user}
                    loginHref={`/login?next=${encodeURIComponent(router.asPath)}`}
                    hasPreviewContent={hasPreviewContent}
                    hasCustomPreview={hasCustomPreview}
                    isManualPreview={Boolean(isManualPreview)}
                    isPdfMaterial={isPdfMaterial}
                    previewHint={previewHint}
                    preview={previewState.preview}
                    previewLoading={previewState.previewLoading}
                    previewError={previewState.previewError}
                    previewExpanded={previewState.previewExpanded}
                    previewPage={previewState.previewPage}
                    previewPageSize={previewPageSize}
                    onPreviewToggle={previewState.handlePreviewToggle}
                    onPreviewPageChange={previewState.setPreviewPage}
                  />
                </div>
                <div
                  role="tabpanel"
                  id="material-comments-panel"
                  aria-labelledby="material-comments-tab"
                  hidden={contentTab !== 'comments'}
                >
                  <CommentSection materialId={material.id} user={user} initialCount={material.commentCount ?? 0} />
                </div>
              </section>
            )}

            <section className={isExperienceMaterial ? 'card' : styles.versions} id={isExperienceMaterial ? 'article-comments' : undefined}>
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

            {isExperienceMaterial && <CommentSection materialId={material.id} user={user} initialCount={material.commentCount ?? 0} />}
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
      {material?.hasNetdisk && (
        <NetdiskAccessModal
          open={netdiskModalOpen}
          title={material.title}
          url={downloadUrl || material.netdiskUrl || ''}
          password={material.netdiskPassword}
          expiredAt={material.netdiskExpiredAt}
          reminder={material.netdiskReminderAt}
          onClose={() => setNetdiskModalOpen(false)}
        />
      )}
      {isExperienceMaterial && (
        <ExperienceImageModal
          images={experienceImages}
          currentIndex={imageModal.previewImageIndex}
          imageReady={imageModal.previewModalImageReady}
          onImageReady={() => imageModal.setPreviewModalImageReady(true)}
          onClose={imageModal.handleCloseExperienceImage}
          onPrev={imageModal.handlePreviewImagePrev}
          onNext={imageModal.handlePreviewImageNext}
        />
      )}
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
    material = await fetchMaterialDetail(materialId, session.token || undefined, getRequestOrigin(ctx.req));
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
      const encodedCanonicalId = encodeURIComponent(canonicalId);
      const destination = queryString ? `/materials/${encodedCanonicalId}?${queryString}` : `/materials/${encodedCanonicalId}`;
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
