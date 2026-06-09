import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { CSSProperties, useEffect, useState } from 'react';
import AppImage from '../../components/AppImage';
import { useAppDialog } from '../../components/AppDialogProvider';
import NavBar from '../../components/NavBar';
import ShareSheet from '../../components/ShareSheet';
import { readSession, hasRole } from '../../lib/auth';
import { reportTarget } from '../../lib/api';
import { readApiEnvelope, unwrapApiResponse } from '../../lib/apiEnvelope';
import { getRequestOrigin } from '../../lib/apiBase';
import { toErrorMessage } from '../../lib/errors';
import { fetchMarketItemDetail } from '../../lib/market';
import { warmImage } from '../../lib/imageWarmup';
import { SAMPLE_MARKET_ITEMS } from '../../constants/marketSamples';
import { marketPath, parseMarketId, slugifyTitle, userPath } from '../../lib/slug';
import { copyToClipboard, isLikelyMobile, tryNativeShare } from '../../lib/share';
import { SessionUser, RoleMask } from '../../types/user';
import { MarketItemDetail } from '../../types/market';
import { buildResponsiveImage, isMarketPlaceholder, ResponsiveImageResult } from '../../lib/ossImage';

interface DetailPageProps {
  user: SessionUser | null;
  item: MarketItemDetail | null;
}

const CATEGORY_LABELS: Record<string, string> = {
  BOOK: '书籍',
  DIGITAL: '数码',
  LIFE: '日用',
  SPORT: '运动',
  OTHER: '其他',
};
const HEART_ICON_FILLED = '\u2665\uFE0E';
const HEART_ICON_OUTLINE = '\u2661\uFE0E';

type MarketResponsiveImage = {
  img: ResponsiveImageResult['img'];
  webpSrcSet?: string;
  avifSrcSet?: string;
  lqip?: string;
};

export default function MarketDetailPage({ user, item }: DetailPageProps) {
  const dialog = useAppDialog();
  const router = useRouter();
  const [state, setState] = useState(item);
  const [submitting, setSubmitting] = useState(false);
  const [wanting, setWanting] = useState(false);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [error, setError] = useState('');
  const [moderationAlert, setModerationAlert] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [removing, setRemoving] = useState(false);
  const [showContact, setShowContact] = useState(false);
  const [copyNotice, setCopyNotice] = useState('');
  const [shareNotice, setShareNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [shareSheetOpen, setShareSheetOpen] = useState(false);
  const [shareSheetText, setShareSheetText] = useState('');
  const [shareSheetUrl, setShareSheetUrl] = useState('');
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const [mainImageReady, setMainImageReady] = useState(false);
  const isAdmin = Boolean(user && hasRole(user.roleMask, RoleMask.ADMIN));
  const canViewImages = Boolean(user);

  const sellerDisplay = state?.sellerName || '匿名同学';
  const galleryItems = (state?.images ?? [])
    .map((src, index) => ({
      src,
      variant: state?.imageVariants?.[index],
    }))
    .filter(({ src, variant }) => !isMarketPlaceholder(variant?.src ?? src));
  const hasImages = galleryItems.length > 0;
  const showLockedGallery = !canViewImages && hasImages;
  const loginHref = `/login?next=${encodeURIComponent(router.asPath)}`;
  const canSwitchGallery = hasImages && galleryItems.length > 1;
  const activeGalleryItem = galleryItems[activeImageIndex] || galleryItems[0];
  const categoryLabel = CATEGORY_LABELS[state?.category || ''] || '其他';
  const statusLabel =
    state?.status === 'SOLD'
      ? '已售出'
      : state?.status === 'REMOVED' || state?.status === 'HIDDEN'
      ? '已下架'
      : '在售';
  const statusTone =
    state?.status === 'SOLD' ? 'sold' : state?.status === 'REMOVED' || state?.status === 'HIDDEN' ? 'removed' : 'sale';

  const handleShowContact = async () => {
    if (!state || state.id < 0) return;
    if (!user) {
      router.push({ pathname: '/login', query: { next: router.asPath } });
      return;
    }
    if (state.canViewContact && state.contactValue) {
      setShowContact(true);
      return;
    }
    if (state.status !== 'SALE' || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const resp = await fetch(`/api/market/${state.id}/want`, { method: 'PUT' });
      const data = await unwrapApiResponse<MarketItemDetail>(resp, '操作失败');
      setState(data);
      setShowContact(true);
    } catch (err: unknown) {
      setError(toErrorMessage(err, '操作失败'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleWant = async () => {
    if (!state || state.id < 0 || wanting) return;
    if (!user) {
      router.push({ pathname: '/login', query: { next: router.asPath } });
      return;
    }
    setWanting(true);
    setError('');
    try {
      const method = state.wanted ? 'DELETE' : 'PUT';
      const resp = await fetch(`/api/market/${state.id}/want`, { method });
      const nextState = await unwrapApiResponse<MarketItemDetail>(resp, '操作失败');
      setState(nextState);
      if (!nextState.canViewContact) {
        setShowContact(false);
      }
    } catch (err: unknown) {
      setError(toErrorMessage(err, '操作失败'));
    } finally {
      setWanting(false);
    }
  };

  const handleCopyContact = async () => {
    const value = state?.contactValue?.trim();
    if (!value) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = value;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopyNotice('已复制');
      window.setTimeout(() => setCopyNotice(''), 1800);
    } catch {
      setCopyNotice('复制失败，请手动复制');
      window.setTimeout(() => setCopyNotice(''), 2200);
    }
  };

  const handleShare = async () => {
    if (!state) return;
    const sharePath =
      state.id < 0 ? router.asPath.split('?')[0] || `/market/${state.id}` : marketPath(state.id, state.title);
    const shareUrl = typeof window === 'undefined' ? sharePath : `${window.location.origin}${sharePath}`;
    try {
      const shareTitle = state.title || '校园好物';
      const shareText = `${shareTitle}\n${shareUrl}`;
      if (isLikelyMobile()) {
        const shared = await tryNativeShare({ title: shareTitle, text: shareText, url: shareUrl });
        if (shared) {
          setShareNotice({ type: 'success', text: '已唤起系统分享。' });
          window.setTimeout(() => setShareNotice(null), 1800);
          return;
        }
        setShareNotice(null);
        setShareSheetText(shareText);
        setShareSheetUrl(shareUrl);
        setShareSheetOpen(true);
        return;
      }
      const copied = await copyToClipboard(shareUrl);
      if (copied) {
        setShareNotice({ type: 'success', text: '商品链接已复制，可以直接分享给同学。' });
        window.setTimeout(() => setShareNotice(null), 1800);
        return;
      }
      setShareNotice({ type: 'error', text: '复制失败，请手动复制链接。' });
      window.setTimeout(() => setShareNotice(null), 2200);
    } catch (err: unknown) {
      setShareNotice({ type: 'error', text: toErrorMessage(err, '复制失败，请稍后重试。') });
      window.setTimeout(() => setShareNotice(null), 2200);
    }
  };

  const handleMarkSold = async () => {
    if (!state || !user) {
      router.push({ pathname: '/login', query: { next: router.asPath } });
      return;
    }
    setStatusUpdating(true);
    setError('');
    try {
      const nextStatus = state.status === 'SOLD' ? 'SALE' : 'SOLD';
      const resp = await fetch(`/api/market/${state.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: nextStatus }),
      });
      const data = await unwrapApiResponse<MarketItemDetail>(resp, '操作失败');
      setState(data);
    } catch (err: unknown) {
      setError(toErrorMessage(err, '操作失败'));
    } finally {
      setStatusUpdating(false);
    }
  };

  const handleDelete = async () => {
    if (!state || state.id < 0 || removing) return;
    const confirmed = await dialog.confirm({
      title: '删除商品',
      message: '确定要删除该商品吗？此操作不可撤销。',
      confirmText: '删除商品',
      danger: true,
    });
    if (!confirmed) {
      return;
    }
    setRemoving(true);
    setModerationAlert(null);
    try {
      const url = state.isOwner ? `/api/market/${state.id}` : `/api/admin/market/${state.id}`;
      const resp = await fetch(url, { method: 'DELETE' });
      const json = await readApiEnvelope(resp);
      if (!resp.ok || !json.ok) {
        const msg = json?.msg || `删除失败（状态码 ${resp.status}）`;
        throw new Error(msg);
      }
      setModerationAlert({ type: 'success', text: '商品已删除，正在返回集市…' });
      await router.replace('/market');
    } catch (err: unknown) {
      setModerationAlert({ type: 'error', text: toErrorMessage(err, '删除失败，请稍后重试。') });
    } finally {
      setRemoving(false);
    }
  };

  const handleReport = async () => {
    if (!state || state.id < 0) return;
    if (!user) {
      router.push({ pathname: '/login', query: { next: router.asPath } });
      return;
    }
    const reason = (
      await dialog.prompt({
        title: '举报商品',
        message: '请输入举报理由。',
        placeholder: '示例：违规售卖、虚假信息等',
        multiline: true,
        confirmText: '提交举报',
      })
    )?.trim();
    if (!reason) return;
    setError('');
    try {
      await reportTarget('MARKET_ITEM', state.id, reason);
      setModerationAlert({ type: 'success', text: '已收到举报，我们会尽快处理。' });
    } catch (err: unknown) {
      setModerationAlert({ type: 'error', text: toErrorMessage(err, '举报失败，请稍后再试。') });
    }
  };

  useEffect(() => {
    setActiveImageIndex(0);
  }, [state?.id, galleryItems.length]);

  useEffect(() => {
    if (!galleryItems.length) {
      setMainImageReady(false);
      return;
    }
    setMainImageReady(false);
    const next = galleryItems[(activeImageIndex + 1) % galleryItems.length];
    if (!next || galleryItems.length < 2) {
      return;
    }
    const { src, variant } = next;
    void warmImage(variant?.src || src, {
      srcSet: variant?.srcSet || variant?.webpSrcSet || variant?.avifSrcSet || undefined,
      sizes: '(max-width: 768px) 90vw, (max-width: 1200px) 70vw, 60vw',
    });
  }, [activeImageIndex, galleryItems]);

  const handlePrevImage = () => {
    if (!canSwitchGallery) return;
    setActiveImageIndex((prev) => (prev - 1 + galleryItems.length) % galleryItems.length);
  };

  const handleNextImage = () => {
    if (!canSwitchGallery) return;
    setActiveImageIndex((prev) => (prev + 1) % galleryItems.length);
  };

  if (!state) {
    return (
      <>
        <NavBar user={user} />
        <main className="container">
          <section className="card">
            <h2>未找到商品</h2>
            <p>该商品可能已下架或不存在。</p>
            <Link className="button primary" href="/market">
              返回校园集市
            </Link>
          </section>
        </main>
      </>
    );
  }

  return (
    <>
      <NavBar user={user} />
      <main className="container market-detail-page">
        <section className="card market-detail">
          <div className="market-detail__gallery">
            {showLockedGallery ? (
              <div className="market-detail__locked">
                <div className="market-media-locked">
                  <span className="market-media-locked__badge">
                    <Link className="login-link" href={loginHref} onClick={(e) => e.stopPropagation()}>
                      登录
                    </Link>
                    后查看图片
                  </span>
                  <p className="market-media-locked__text">未登录用户不可查看图片</p>
                  <Link
                    className="button primary small"
                    href={`/login?next=${encodeURIComponent(router.asPath)}`}
                    onClick={(e) => e.stopPropagation()}
                  >
                    立即登录
                  </Link>
                </div>
              </div>
            ) : hasImages ? (
              <div className="market-gallery">
                {(() => {
                  const sizes = '(max-width: 768px) 90vw, (max-width: 1200px) 70vw, 60vw';
                  const fallback = '/placeholders/market-item.svg';
                  const variant = activeGalleryItem?.variant;
                  const src = activeGalleryItem?.src;
                  const responsive: MarketResponsiveImage = variant?.src
                    ? {
                        img: {
                          src: variant.src || src || fallback,
                          srcSet: variant.srcSet || undefined,
                          sizes,
                          alt: state.title,
                          loading: 'eager',
                          fetchPriority: 'high' as const,
                        },
                        webpSrcSet: variant.webpSrcSet || undefined,
                        avifSrcSet: variant.avifSrcSet || undefined,
                        lqip: variant.lqip || undefined,
                      }
                    : (() => {
                        const fallbackImage = buildResponsiveImage(src, {
                          alt: state.title,
                          widths: [800, 1200, 1600],
                          sizes,
                          fallback,
                          loading: 'eager',
                          fetchPriority: 'high',
                        });
                        return {
                          img: fallbackImage.img,
                          webpSrcSet: fallbackImage.webp?.srcSet,
                          avifSrcSet: undefined,
                          lqip: undefined,
                        };
                      })();
                  const lqipStyle = responsive.lqip
                    ? ({ '--lqip': `url(${responsive.lqip})` } as CSSProperties)
                    : undefined;
                  return (
                    <div
                      className={`market-gallery__main${lqipStyle ? ' has-lqip' : ''}${mainImageReady ? ' is-ready' : ' is-loading'}`}
                      style={lqipStyle}
                    >
                      {!mainImageReady && <div className="market-gallery__loading">图片加载中...</div>}
                      <picture>
                        {responsive.avifSrcSet && (
                          <source type="image/avif" srcSet={responsive.avifSrcSet} sizes={sizes} />
                        )}
                        {responsive.webpSrcSet && (
                          <source type="image/webp" srcSet={responsive.webpSrcSet} sizes={sizes} />
                        )}
                        <img
                          {...responsive.img}
                          alt={responsive.img.alt}
                          decoding="async"
                          onLoad={() => setMainImageReady(true)}
                          onError={(e) => {
                            const target = e.currentTarget;
                            target.onerror = null;
                            target.src = fallback;
                            target.removeAttribute('srcset');
                            setMainImageReady(true);
                          }}
                        />
                      </picture>
                      {canSwitchGallery && (
                        <>
                          <button type="button" className="market-gallery__arrow left" onClick={handlePrevImage}>
                            ‹
                          </button>
                          <button type="button" className="market-gallery__arrow right" onClick={handleNextImage}>
                            ›
                          </button>
                        </>
                      )}
                      <span className="market-gallery__count">
                        {activeImageIndex + 1}/{galleryItems.length}
                      </span>
                    </div>
                  );
                })()}
                {canSwitchGallery && (
                  <div className="market-gallery__thumbs">
                    {galleryItems.map(({ src, variant }, index) => (
                      <button
                        type="button"
                        key={`${variant?.src || src}-${index}`}
                        className={`market-gallery__thumb${index === activeImageIndex ? ' is-active' : ''}`}
                        onClick={() => setActiveImageIndex(index)}
                        aria-label={`查看第 ${index + 1} 张图片`}
                        aria-pressed={index === activeImageIndex}
                      >
                        <AppImage src={variant?.src || src} alt={`商品图片 ${index + 1}`} loading="lazy" decoding="async" />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="market-detail__cover">
                <div className="market-title-cover market-title-cover--detail">
                  <span className="market-title-cover__tag">{categoryLabel}</span>
                  <strong className="market-title-cover__title">{state.title}</strong>
                  <span className="market-title-cover__meta">{state.school || '不限学校'}</span>
                </div>
              </div>
            )}
          </div>
          <div className="market-detail__info-head">
            <div className="market-detail__header">
              <span className="market-detail__category">{categoryLabel}</span>
              <h1 className="market-detail__title">{state.title}</h1>
              <div className="market-detail__price-row">
                <span className="market-detail__price">{`¥${(state.price ?? 0).toFixed(2)}`}</span>
                <span className={`market-status-chip status-${statusTone}`}>{statusLabel}</span>
              </div>
              <div className="market-meta-line market-meta-line--detail">
                <span className="market-meta-chip">
                  <span className="market-meta-label">发布者</span>
                  {state.sellerId ? (
                    <Link
                      className="text-button market-meta-link"
                      href={userPath(state.sellerId, state.sellerNickname || state.sellerUsername || '')}
                    >
                      {sellerDisplay}
                    </Link>
                  ) : (
                    <span className="market-meta-value">{sellerDisplay}</span>
                  )}
                </span>
                <span className="market-meta-chip ghost">
                  <span className="market-meta-label">学校</span>
                  <span className="market-meta-value">{state.school || '不限学校'}</span>
                </span>
                <span className="market-meta-chip market-meta-chip--stat">{state.wantCount ?? 0} 人想要</span>
              </div>
            </div>
          </div>
          <div className="market-detail__info-body">
            <p className="market-detail__desc">{state.description || '卖家暂无补充描述。'}</p>
            {moderationAlert && (
              <div className={`alert ${moderationAlert.type === 'error' ? 'error' : 'success'}`}>
                {moderationAlert.text}
              </div>
            )}
            {state.status === 'SOLD' && !state.isOwner ? (
              <p className="help-text">该商品已标记为已售出，如需更多好物可返回集市看看。</p>
            ) : state.status === 'REMOVED' || state.status === 'HIDDEN' ? (
              <p className="help-text">该商品已被管理员下架。</p>
            ) : (
              <>
                {!state.isOwner && state.status === 'SALE' && (
                  <button className="button primary" type="button" onClick={handleShowContact} disabled={submitting}>
                    {submitting ? '处理中...' : '查看卖家联系方式'}
                  </button>
                )}
                {!state.isOwner && (
                  <button className="button ghost" type="button" onClick={handleReport}>
                    举报
                  </button>
                )}
                {!state.isOwner && (
                  <button
                    className={`market-want-toggle ${state.wanted ? 'active' : ''}`}
                    type="button"
                    onClick={handleToggleWant}
                    disabled={wanting || state.status !== 'SALE'}
                    aria-pressed={!!state.wanted}
                    aria-label={state.wanted ? '取消想要' : '标记想要'}
                  >
                    {state.wanted ? HEART_ICON_FILLED : HEART_ICON_OUTLINE}
                  </button>
                )}
                {showContact && state.canViewContact && (
                  <div className="contact-panel">
                    <h3>联系卖家</h3>
                    <div className="contact-row">
                      <p className="contact-value">
                        {state.contactType === 'QQ' && '📮 QQ：'}
                        {state.contactType === 'WECHAT' && '📱 微信：'}
                        {state.contactType === 'PHONE' && '📞 手机号：'}
                        {state.contactValue}
                      </p>
                      {state.contactValue && (
                        <button className="button ghost small contact-copy" type="button" onClick={handleCopyContact}>
                          复制
                        </button>
                      )}
                    </div>
                    {copyNotice && <p className="help-text">{copyNotice}</p>}
                  </div>
                )}
              </>
            )}
            <button className="button ghost" type="button" onClick={handleShare}>
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
            {shareNotice && (
              <p className={shareNotice.type === 'error' ? 'error-text' : 'success-text'}>{shareNotice.text}</p>
            )}
            {state.isOwner && (
              <button className="button ghost" type="button" onClick={handleMarkSold} disabled={statusUpdating}>
                {state.status === 'SOLD' ? '重新上架' : '标记已售'}
              </button>
            )}
            {isAdmin && state.id >= 0 && (
              <button className="button danger" type="button" onClick={handleDelete} disabled={removing}>
                {removing ? '删除中...' : state.isOwner ? '删除商品' : '管理员删除商品'}
              </button>
            )}
            {error && <p className="error-text">{error}</p>}
            <Link className="button ghost" href="/market">
              返回集市
            </Link>
          </div>
        </section>
      </main>
      <ShareSheet
        open={shareSheetOpen}
        title="分享校园好物"
        text={shareSheetText}
        linkUrl={shareSheetUrl}
        onClose={() => setShareSheetOpen(false)}
      />
    </>
  );
}

export const getServerSideProps: GetServerSideProps<DetailPageProps> = async (ctx) => {
  const { id } = ctx.query;
  const session = readSession(ctx.req);
  if (typeof id !== 'string') {
    return {
      props: {
        user: session.user,
        item: null,
      },
    };
  }
  const sample = SAMPLE_MARKET_ITEMS.find((entry) => entry.slug === id);
  let item: MarketItemDetail | null = null;
  if (sample) {
    item = {
      id: -1,
      sellerId: 0,
      sellerName: '示例卖家',
      title: sample.title,
      description: sample.description,
      price: sample.price,
      category: sample.category,
      images: sample.images,
      wantCount: sample.wantCount,
      school: sample.school,
      status: 'SALE',
      canViewContact: true,
      contactType: sample.contactType,
      contactValue: sample.contactValue,
      wanted: false,
      isOwner: false,
      createdAt: new Date().toISOString(),
    };
  } else {
    const marketId = parseMarketId(id);
    if (!marketId) {
      return {
        props: {
          user: session.user,
          item: null,
        },
      };
    }
    try {
      const origin = getRequestOrigin(ctx.req);
      item = await fetchMarketItemDetail(marketId, session.token || undefined, origin);
    } catch {
      item = null;
    }
  }
  if (item && item.id >= 0) {
    const slug = slugifyTitle(item.title);
    const canonicalId = slug ? `${item.id}-${slug}` : String(item.id);
    if (id !== canonicalId) {
      const resolvedUrl = ctx.resolvedUrl || '';
      const queryString = resolvedUrl.includes('?') ? resolvedUrl.split('?')[1] : '';
      const encodedCanonicalId = encodeURIComponent(canonicalId);
      const destination = queryString ? `/market/${encodedCanonicalId}?${queryString}` : `/market/${encodedCanonicalId}`;
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
      user: session.user,
      item,
    },
  };
};
