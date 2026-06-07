import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { CSSProperties, useMemo, useState } from 'react';
import useSWR from 'swr';
import NavBar from '../../components/NavBar';
import PaginationBar from '../../components/PaginationBar';
import { readSession, hasRole } from '../../lib/auth';
import { formatNumber } from '../../lib/format';
import { SessionUser, RoleMask } from '../../types/user';
import { MarketItem, MarketListResponse } from '../../types/market';
import { SAMPLE_MARKET_ITEMS } from '../../constants/marketSamples';
import { buildResponsiveImage, isMarketPlaceholder, ResponsiveImageResult } from '../../lib/ossImage';
import { getRequestOrigin } from '../../lib/apiBase';
import { marketPath, userPath } from '../../lib/slug';
import { toErrorMessage } from '../../lib/errors';
import { ensureApiSuccess, readApiEnvelope, unwrapApiResponse } from '../../lib/apiEnvelope';
import { fetchMarketItems } from '../../lib/market';

const CATEGORY_OPTIONS = [
  { value: '', label: '全部分类' },
  { value: 'BOOK', label: '书籍' },
  { value: 'DIGITAL', label: '数码' },
  { value: 'LIFE', label: '日用品' },
  { value: 'SPORT', label: '运动' },
  { value: 'OTHER', label: '其他' },
];
const CATEGORY_LABELS: Record<string, string> = {
  BOOK: '书籍',
  DIGITAL: '数码',
  LIFE: '日用品',
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

interface MarketPageProps {
  user: SessionUser | null;
  items: MarketItem[];
  meta: MarketListResponse['meta'];
  filters: { keyword?: string; category?: string; page?: string };
  stats: MarketListResponse['stats'];
}

const readSampleSlug = (item: MarketItem) => {
  const maybe = item as unknown as { sampleSlug?: unknown };
  return typeof maybe.sampleSlug === 'string' ? maybe.sampleSlug : undefined;
};

const swrFetcher = async (url: string) => {
  const resp = await fetch(url);
  const json = await readApiEnvelope(resp);
  if (!resp.ok || !json?.ok) {
    const message = json?.msg || resp.statusText || '请求失败';
    throw new Error(message);
  }
  return json;
};

export default function MarketPage({ user, items, meta, filters, stats }: MarketPageProps) {
  const router = useRouter();
  const isAdmin = Boolean(user && hasRole(user.roleMask, RoleMask.ADMIN));
  const canViewImages = Boolean(user);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [paginationLoading, setPaginationLoading] = useState(false);
  const categoryLabel = useMemo(
    () => CATEGORY_OPTIONS.find((option) => option.value === filters.category)?.label || '全部分类',
    [filters.category]
  );

  const displayItems = useMemo(() => {
    if (items.length > 0) return items.map((item) => ({ ...item }));
    return SAMPLE_MARKET_ITEMS.map((sample, idx) => ({
      id: -(idx + 1),
      title: sample.title,
      price: sample.price,
      category: sample.category,
      thumbnail: sample.thumbnail,
      wantCount: sample.wantCount,
      school: sample.school,
      sellerName: sample.sellerName || '示例卖家',
      createdAt: new Date().toISOString(),
      sampleSlug: sample.slug,
    })) as Array<MarketItem & { sampleSlug: string }>;
  }, [items]);

  const [itemStates, setItemStates] = useState<Record<number, { wanted?: boolean; wantCount: number }>>(() => {
    const initial: Record<number, { wanted?: boolean; wantCount: number }> = {};
    items.forEach((item) => {
      initial[item.id] = {
        wantCount: item.wantCount ?? 0,
        wanted: typeof item.wanted === 'boolean' ? item.wanted : undefined,
      };
    });
    return initial;
  });
  const [pendingMap, setPendingMap] = useState<Record<number, boolean>>({});
  const [actionError, setActionError] = useState('');
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [moderationAlert, setModerationAlert] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const {
    data: wantedResponse,
    mutate: mutateWanted,
  } = useSWR(user ? '/api/market/wanted' : null, swrFetcher, {
    revalidateOnFocus: true,
  });

  const wantedIdSet = useMemo(() => {
    if (!wantedResponse || !wantedResponse.ok || !Array.isArray(wantedResponse.data)) {
      return new Set<number>();
    }
    return new Set<number>((wantedResponse.data as number[]) || []);
  }, [wantedResponse]);

  const resolveWantedState = (itemId: number) => {
    const stored = itemStates[itemId];
    if (typeof stored?.wanted === 'boolean') {
      return stored.wanted;
    }
    return wantedIdSet.has(itemId);
  };

  const pageSize = meta.size || 20;
  const currentPage = meta.page || 1;
  const totalItems = meta.total || 0;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  const handleToggleWant = async (itemId: number, currentlyWanted: boolean) => {
    const target = displayItems.find((entry) => entry.id === itemId);
    if (!target || itemId < 0) {
      return;
    }
    if (!user) {
      const nextPath = marketPath(itemId, target.title);
      router.push({
        pathname: '/login',
        query: { next: nextPath },
      });
      return;
    }
    if (pendingMap[itemId]) {
      return;
    }

    const storedState = itemStates[itemId];
    const baseWantCount =
      typeof storedState?.wantCount === 'number' ? storedState.wantCount : typeof target.wantCount === 'number' ? target.wantCount : 0;
    const previous = storedState || { wanted: currentlyWanted, wantCount: baseWantCount };

    setActionError('');
    setPendingMap((prev) => ({ ...prev, [itemId]: true }));

    try {
      const method = currentlyWanted ? 'DELETE' : 'PUT';
      const resp = await fetch(`/api/market/${itemId}/want`, { method });
      const data = await unwrapApiResponse<{ wanted?: boolean; wantCount?: number }>(resp, '操作失败');
      const fallbackCount =
        method === 'PUT'
          ? baseWantCount + 1
          : Math.max(0, baseWantCount - 1);
      setItemStates((prev) => ({
        ...prev,
        [itemId]: {
          wanted: !!data.wanted,
          wantCount:
            typeof data.wantCount === 'number'
              ? data.wantCount
              : fallbackCount,
        },
      }));
      if (mutateWanted) {
        mutateWanted();
      }
    } catch (err: unknown) {
      setActionError(toErrorMessage(err, '操作失败'));
      setItemStates((prev) => ({
        ...prev,
        [itemId]: prev[itemId] || previous,
      }));
    } finally {
      setPendingMap((prev) => {
        const { [itemId]: _omit, ...rest } = prev;
        return rest;
      });
    }
  };

  const handleCardClick = (href: string) => {
    router.push(href);
  };

  const handlePageChange = async (nextPage: number) => {
    if (nextPage === currentPage || nextPage < 1 || nextPage > totalPages) {
      return;
    }
    setPaginationLoading(true);
    try {
      await router.push(
        {
          pathname: '/market',
          query: { ...filters, page: String(nextPage) },
        },
        undefined,
        { scroll: false }
      );
    } finally {
      setPaginationLoading(false);
    }
  };

  const handleAdminDelete = async (itemId: number) => {
    if (!isAdmin || itemId < 0) return;
    if (!window.confirm('确定要删除该商品吗？此操作不可撤销。')) {
      return;
    }
    setDeletingId(itemId);
    setModerationAlert(null);
    try {
      const resp = await fetch(`/api/admin/market/${itemId}`, { method: 'DELETE' });
      await ensureApiSuccess(resp, '删除失败');
      setModerationAlert({ type: 'success', text: '商品已删除。' });
      await router.replace(router.asPath, undefined, { scroll: false });
    } catch (error: unknown) {
      setModerationAlert({ type: 'error', text: toErrorMessage(error, '删除失败，请稍后重试。') });
    } finally {
      setDeletingId((prev) => (prev === itemId ? null : prev));
    }
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container market-page">
        <section className="hero card hero-magazine market-hero">
          <div className="market-cta hero-copy">
            <h1>校园集市</h1>
            <div className="market-cta__actions hero-actions">
              <div className="hero-action-buttons">
                <Link className="button primary" href="#market-buy">
                  我要购买
                </Link>
                <Link className="button ghost" href="/market/sell">
                  我要出售
                </Link>
              </div>
            </div>
          </div>
          <div className="hero-panel market-hero-panel">
            <div className="hero-stats market-hero-stats">
              <div className="hero-stat">
                <span>在售商品</span>
                <strong>{formatNumber(stats?.active ?? 0)}</strong>
              </div>
              <div className="hero-stat">
                <span>用户个数</span>
                <strong>{formatNumber(stats?.userCount ?? 0)}</strong>
              </div>
            </div>
          </div>
        </section>
        {moderationAlert && (
          <div className={`alert ${moderationAlert.type === 'error' ? 'error' : 'success'}`}>
            {moderationAlert.text}
          </div>
        )}

        <section className="card market-notice">
          <h3>温馨提示</h3>
          <p>
            校园集市仅提供信息撮合服务，不在平台内完成支付或售后。请买卖双方线下沟通、当面验货，注意资金与人身安全，如遇问题可携证据向学校/警方报备。
          </p>
        </section>

        <section id="market-buy" className="card market-buy-card">
          <div className="market-buy-header">
            <div className="market-buy-heading">
              <h2>我要购买</h2>
              <div className="market-buy-summary">
                <span className="market-buy-pill">分类：{categoryLabel}</span>
                <span className="market-buy-pill">共 {meta.total} 件好物</span>
              </div>
            </div>
            <Link className="button ghost" href="/market/sell">
              去出售
            </Link>
          </div>
          <div className="market-buy-toolbar">
            <form className="market-filters" method="get">
              <input
                type="text"
                name="keyword"
                placeholder="搜索商品名称 / 关键词"
                defaultValue={filters.keyword || ''}
              />
              <select name="category" defaultValue={filters.category || ''}>
                {CATEGORY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <button className="button primary" type="submit">
                筛选
              </button>
            </form>

            <div className="market-actions">
              <div className="view-toggle" role="group" aria-label="集市视图切换">
                <button
                  type="button"
                  className={viewMode === 'grid' ? 'active' : ''}
                  onClick={() => setViewMode('grid')}
                >
                  卡片
                </button>
                <button
                  type="button"
                  className={viewMode === 'list' ? 'active' : ''}
                  onClick={() => setViewMode('list')}
                >
                  列表
                </button>
              </div>
            </div>
          </div>

          <ul className={viewMode === 'grid' ? 'market-grid' : 'market-list'}>
            {displayItems.map((item, idx) => {
              const priceText = `¥${(item.price ?? 0).toFixed(2)}`;
              const sampleSlug = readSampleSlug(item);
              const isSample = typeof sampleSlug === 'string' || item.id < 0;
              const stored = itemStates[item.id];
              const wantCount = stored ? stored.wantCount : item.wantCount ?? 0;
              const wanted = resolveWantedState(item.id);
              const pending = !!pendingMap[item.id];
              const targetHref = sampleSlug ? `/market/${sampleSlug}` : marketPath(item.id, item.title);
              const sellerLabel = isSample ? '示例卖家' : item.sellerName || '匿名同学';
              const sellerId = isSample ? null : item.sellerId ?? null;
              if (viewMode === 'list') {
                return (
                  <li
                    key={`${item.id}-${item.title}`}
                    className="market-list-row market-card-clickable"
                    onClick={() => handleCardClick(targetHref)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && handleCardClick(targetHref)}
                  >
                    <div className="market-list-info">
                      <h3>{item.title}</h3>
                      <div className="market-meta-line market-meta-line--list">
                        <span className="market-meta-chip market-meta-chip--stat">{wantCount} 人想要</span>
                        <span className="market-meta-chip">
                          <span className="market-meta-label">发布者</span>
                          {sellerId ? (
                            <button
                              type="button"
                              className="text-button market-meta-link"
                              onClick={(e) => {
                                e.stopPropagation();
                                router.push(userPath(sellerId, sellerLabel));
                              }}
                            >
                              {sellerLabel}
                            </button>
                          ) : (
                            <span className="market-meta-value">{sellerLabel}</span>
                          )}
                        </span>
                        <span className="market-meta-chip ghost">
                          <span className="market-meta-label">学校</span>
                          <span className="market-meta-value">{item.school || '不限学校'}</span>
                        </span>
                      </div>
                    </div>
                    <div className="market-list-meta">
                      <span className="market-list-price">{priceText}</span>
                      <div className="market-list-actions">
                        {!isSample && (
                          <button
                            className={`market-want-toggle ${wanted ? 'active' : ''}`}
                            type="button"
                            disabled={pending}
                            aria-pressed={wanted}
                            aria-label={wanted ? '取消想要' : '标记想要'}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleToggleWant(item.id, wanted);
                            }}
                          >
                            {wanted ? HEART_ICON_FILLED : HEART_ICON_OUTLINE}
                          </button>
                        )}
                        <button
                          className="button ghost small"
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCardClick(targetHref);
                          }}
                        >
                          查看
                        </button>
                      </div>
                      {isAdmin && !isSample && (
                        <button
                          className="text-button danger"
                          type="button"
                          disabled={deletingId === item.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleAdminDelete(item.id);
                          }}
                        >
                          {deletingId === item.id ? '删除中...' : '删除商品'}
                        </button>
                      )}
                    </div>
                  </li>
                );
              }
              const isPriority = idx < 2;
              const sizes = '(max-width: 720px) 100vw, (max-width: 1100px) 48vw, 33vw';
              const fallback = '/placeholders/market-item.svg';
              const rawThumbnail = item.thumbnailVariant?.src || item.thumbnail || null;
              const hasImage = Boolean(rawThumbnail) && !isMarketPlaceholder(rawThumbnail);
              const showLocked = !canViewImages && hasImage;
              const showImage = canViewImages && hasImage;
              const categoryText = CATEGORY_LABELS[item.category] || '其他';
              const cardImage: MarketResponsiveImage | null = showImage
                ? item.thumbnailVariant?.src
                  ? {
                      img: {
                        src: item.thumbnailVariant.src || item.thumbnail || fallback,
                        srcSet: item.thumbnailVariant.srcSet || undefined,
                        sizes,
                        alt: item.title,
                        loading: isPriority ? 'eager' : 'lazy',
                        fetchPriority: isPriority ? 'high' : undefined,
                      },
                      webpSrcSet: item.thumbnailVariant.webpSrcSet || undefined,
                      avifSrcSet: item.thumbnailVariant.avifSrcSet || undefined,
                      lqip: item.thumbnailVariant.lqip || undefined,
                    }
                  : item.thumbnail
                  ? (() => {
                      const responsive = buildResponsiveImage(item.thumbnail, {
                        alt: item.title,
                        widths: [400, 800, 1200],
                        sizes,
                        fallback,
                        loading: isPriority ? 'eager' : 'lazy',
                        fetchPriority: isPriority ? 'high' : undefined,
                      });
                      return {
                        img: responsive.img,
                        webpSrcSet: responsive.webp?.srcSet,
                        avifSrcSet: undefined,
                        lqip: undefined,
                      };
                    })()
                  : null
                : null;
              const lqipStyle =
                cardImage?.lqip ? ({ '--lqip': `url(${cardImage.lqip})` } as CSSProperties) : undefined;
              const loginHref = `/login?next=${encodeURIComponent(targetHref)}`;
              return (
                <li
                  key={`${item.id}-${item.title}`}
                  className="market-item-card market-card-clickable"
                  onClick={() => handleCardClick(targetHref)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && handleCardClick(targetHref)}
                >
                  <div className={`market-card-media${lqipStyle ? ' has-lqip' : ''}`} style={lqipStyle}>
                    {showImage && cardImage ? (
                      <picture>
                        {cardImage.avifSrcSet && <source type="image/avif" srcSet={cardImage.avifSrcSet} sizes={sizes} />}
                        {cardImage.webpSrcSet && <source type="image/webp" srcSet={cardImage.webpSrcSet} sizes={sizes} />}
                        <img
                          {...cardImage.img}
                          alt={cardImage.img.alt}
                          onError={(e) => {
                            const target = e.currentTarget;
                            target.onerror = null;
                            target.src = fallback;
                            target.removeAttribute('srcset');
                          }}
                        />
                      </picture>
                    ) : showLocked ? (
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
                          href={loginHref}
                          onClick={(e) => e.stopPropagation()}
                        >
                          立即登录
                        </Link>
                      </div>
                    ) : (
                      <div className="market-title-cover">
                        <span className="market-title-cover__tag">{categoryText}</span>
                        <strong className="market-title-cover__title">{item.title}</strong>
                        <span className="market-title-cover__meta">{item.school || '不限学校'}</span>
                      </div>
                    )}
                  </div>
                  <div className="market-item__body">
                    <div className="market-item__top">
                      <h3 className="market-item__title">{item.title}</h3>
                    </div>
                    <div className="market-meta-line">
                      <span className="market-meta-chip">
                        <span className="market-meta-label">发布者</span>
                        {sellerId ? (
                          <button
                            type="button"
                            className="text-button market-meta-link"
                            onClick={(e) => {
                              e.stopPropagation();
                              router.push(userPath(sellerId, sellerLabel));
                            }}
                          >
                            {sellerLabel}
                          </button>
                        ) : (
                          <span className="market-meta-value">{sellerLabel}</span>
                        )}
                      </span>
                      <span className="market-meta-chip ghost">
                        <span className="market-meta-label">学校</span>
                        <span className="market-meta-value">{item.school || '不限学校'}</span>
                      </span>
                    </div>
                    <div className="market-item__footer">
                      <div className="market-item__price-line">
                        <span className="market-item__price">{priceText}</span>
                        <span className="market-item__want">{wantCount} 人想要</span>
                        {sampleSlug && <span className="badge badge-ghost">示例展示</span>}
                      </div>
                      <div className="market-item__actions">
                        {!isSample && (
                          <button
                            className={`market-want-toggle ${wanted ? 'active' : ''}`}
                            type="button"
                            disabled={pending}
                            aria-pressed={wanted}
                            aria-label={wanted ? '取消想要' : '标记想要'}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleToggleWant(item.id, wanted);
                            }}
                          >
                            {wanted ? HEART_ICON_FILLED : HEART_ICON_OUTLINE}
                          </button>
                        )}
                        <button
                          className="button ghost small"
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCardClick(targetHref);
                          }}
                        >
                          查看
                        </button>
                      </div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
          {actionError && (
            <p className="error-text" style={{ marginTop: 12 }}>
              {actionError}
            </p>
          )}
          <PaginationBar
            currentPage={currentPage}
            totalItems={totalItems}
            pageSize={pageSize}
            loading={paginationLoading}
            onPageChange={handlePageChange}
          />
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<MarketPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const rawKeyword = typeof ctx.query.keyword === 'string' ? ctx.query.keyword : '';
  const rawCategory = typeof ctx.query.category === 'string' ? ctx.query.category : '';
  const page = typeof ctx.query.page === 'string' ? ctx.query.page : '1';
  const filters = {
    keyword: rawKeyword,
    category: rawCategory,
    page,
  };
  const origin = getRequestOrigin(ctx.req);
  let items: MarketItem[] = [];
  let meta: MarketListResponse['meta'] = { page: Number(page) || 1, size: 20, total: 0 };
  let stats: MarketListResponse['stats'] = { active: 0, sold: 0, userCount: 0 };
  try {
    const data = await fetchMarketItems(
      { keyword: rawKeyword, category: rawCategory, page },
      origin,
      session.token || undefined
    );
    items = data.items || [];
    meta = data.meta || meta;
    stats = data.stats || stats;
  } catch (error) {
    // eslint-disable-next-line no-console
    console.warn('Failed to load market items', error);
  }
  if (items.length === 0 && stats.active === 0 && stats.sold === 0) {
    stats = { active: SAMPLE_MARKET_ITEMS.length, sold: 0, userCount: stats.userCount ?? 0 };
  }
  return {
    props: {
      user: session.user,
      items,
      meta,
      filters,
      stats,
    },
  };
};
