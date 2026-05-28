import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import AppImage from '../../components/AppImage';
import ExperienceImageModal from '../../components/materials/ExperienceImageModal';
import MaterialPreviewPanel from '../../components/materials/MaterialPreviewPanel';
import NavBar from '../../components/NavBar';
import ShareSheet from '../../components/ShareSheet';
import CommentSection from '../../components/comments/CommentSection';
import StarRating from '../../components/StarRating';
import { readSession, hasRole } from '../../lib/auth';
import { fetchMaterialDetail } from '../../lib/api';
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
    myRating,
    ratingAvg,
    ratingCount,
    ratingSubmitting,
    handlePurchase,
    handleDownload,
    handleRatingChange,
    handleToggleLike,
    handleReport,
    handleShare,
  } = useMaterialActions({ material, user, canManage, isSuperAdmin, router });
  const [autoDownloadTriggered, setAutoDownloadTriggered] = useState(false);
  const previewPageSize = 1;
  const uploaderLabel = material?.uploaderNickname || material?.uploaderUsername || '匿名同学';
  const hasCustomPreview =
    Boolean(material?.customPreviewText?.trim()) || (material?.customPreviewImages?.length ?? 0) > 0;
  const isManualPreview = Boolean(material?.previewSource === 'MANUAL');
  const isPdfMaterial = Boolean(material?.hasFile && material?.fileType?.toLowerCase() === 'pdf');
  const isExperienceMaterial = Boolean(material?.tags?.includes('经验分享'));
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
  const canViewNetdisk = Boolean(material?.hasNetdisk && (material.netdiskAccessible || canManage));

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
              <MaterialPreviewPanel
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
