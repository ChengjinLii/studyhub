import Link from 'next/link';
import type { ReactNode, UIEvent } from 'react';
import { useCallback, useState } from 'react';
import { MaterialListItem } from '../../types/material';
import { MaterialRequestItem } from '../../types/request';
import { HomeDiscoveryView, resolveInitialHomeDiscoveryView } from '../../lib/homeDiscovery';
import { formatMajorDisplay } from '../../lib/major';
import { materialPath } from '../../lib/slug';

interface HomeRequestPanelsProps {
  requestItems: MaterialRequestItem[];
  requestLoading: boolean;
  requestError: string;
  requestNotice: { type: 'success' | 'error'; text: string } | null;
  leaderboardItems: MaterialRequestItem[];
  popularItems: MaterialListItem[];
  recommendedItems: MaterialListItem[];
  recommendationHint: string;
  recommendationEmpty: ReactNode;
  buildUploadLink: (item: MaterialRequestItem) => string;
  onFollowRequest: (item: MaterialRequestItem) => void;
}

export default function HomeRequestPanels({
  requestItems,
  requestLoading,
  requestError,
  requestNotice,
  leaderboardItems,
  popularItems,
  recommendedItems,
  recommendationHint,
  recommendationEmpty,
  buildUploadLink,
  onFollowRequest,
}: HomeRequestPanelsProps) {
  const [activeDiscoveryView, setActiveDiscoveryView] = useState<HomeDiscoveryView>(() =>
    resolveInitialHomeDiscoveryView(requestItems.length)
  );
  const [recommendListAtEnd, setRecommendListAtEnd] = useState(false);
  const handleRecommendationScroll = useCallback((event: UIEvent<HTMLUListElement>) => {
    const target = event.currentTarget;
    const atEnd = target.scrollTop + target.clientHeight >= target.scrollHeight - 8;
    setRecommendListAtEnd(atEnd);
  }, []);
  const handleViewAllMaterials = useCallback(() => {
    document.getElementById('materials-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  return (
    <div className="home-dual-panel" id="home-requests">
      <section className="card request-card">
        <div className="materials-header home-discovery-header">
          <div className="home-discovery-heading">
            <h2 className="card-title">
              {activeDiscoveryView === 'requests' ? '求购列表' : '近期热门'}
            </h2>
            <div className="home-discovery-tabs" role="tablist" aria-label="首页发现内容">
              <button
                type="button"
                role="tab"
                aria-selected={activeDiscoveryView === 'requests'}
                aria-controls="home-discovery-panel"
                className={activeDiscoveryView === 'requests' ? 'active' : ''}
                onClick={() => setActiveDiscoveryView('requests')}
              >
                求购列表
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeDiscoveryView === 'popular'}
                aria-controls="home-discovery-panel"
                className={activeDiscoveryView === 'popular' ? 'active' : ''}
                onClick={() => setActiveDiscoveryView('popular')}
              >
                近期热门
              </button>
            </div>
          </div>
          <div className="request-header-actions">
            {activeDiscoveryView === 'requests' ? (
              <Link className="button primary small" href="/requests/new">
                我要购买
              </Link>
            ) : (
              <button className="button primary small" type="button" onClick={handleViewAllMaterials}>
                全部资料
              </button>
            )}
          </div>
        </div>
        <div className="request-list-wrapper" id="home-discovery-panel" role="tabpanel">
          {activeDiscoveryView === 'requests' ? (
            <>
              {requestLoading && <p className="help-text">加载中...</p>}
              {requestError && <p className="error-text">{requestError}</p>}
              {requestNotice && (
                <p className={requestNotice.type === 'error' ? 'error-text' : 'success-text'}>
                  {requestNotice.text}
                </p>
              )}
              {!requestLoading && requestItems.length === 0 ? (
                <div className="empty-state">暂无求购需求，可以切换查看近期热门资料。</div>
              ) : (
                <ul className="request-list">
                  {requestItems.map((item) => {
                    const title = item.course || '求购需求';
                    const detailLink = `/requests/${item.id}`;
                    const budgetLabel = item.budget != null ? `预算 ¥${item.budget}` : '预算 待议';
                    const fundedLabel =
                      item.fundedAmount != null && item.fundedAmount > 0 ? `已筹 ¥${item.fundedAmount}` : '已筹 待议';
                    const canRespond = (item.responseCount ?? 0) === 0 || Boolean(item.responded);
                    return (
                      <li key={item.id} className="request-item">
                        <div className="request-title-row">
                          <div className="request-title">
                            <Link href={detailLink}>{title}</Link>
                          </div>
                          <div className="request-action-row">
                            {item.owner ? (
                              <Link className="button ghost small" href={detailLink}>
                                查看
                              </Link>
                            ) : (
                              <>
                                <button className="button primary small" type="button" onClick={() => onFollowRequest(item)}>
                                  跟购
                                </button>
                                {canRespond ? (
                                  <Link className="button ghost small" href={buildUploadLink(item)}>
                                    应答
                                  </Link>
                                ) : (
                                  <span className="help-text">已有应答</span>
                                )}
                                <Link className="button ghost small" href={detailLink}>
                                  查看
                                </Link>
                              </>
                            )}
                          </div>
                        </div>
                        <div className="request-footer">
                          <span className="request-footer__tag request-footer__budget">{budgetLabel}</span>
                          {item.creatorFloor != null && <span className="request-footer__tag">跟购底价 ¥{item.creatorFloor}</span>}
                          <span className="request-footer__tag request-footer__funded">{fundedLabel}</span>
                          <span className="request-footer__tag request-footer__responses">应答 {item.responseCount ?? 0}</span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
              {leaderboardItems.length > 0 && (
                <div className="request-leaderboard">
                  <div className="request-leaderboard__title">
                    求购榜 <span className="request-leaderboard__hint">按已筹金额</span>
                  </div>
                  <ul className="request-leaderboard__list">
                    {leaderboardItems.map((item, index) => {
                      const title = item.course || '求购需求';
                      const fundedLabel =
                        item.fundedAmount != null && item.fundedAmount > 0 ? `已筹 ¥${item.fundedAmount}` : '待议';
                      return (
                        <li key={item.id} className="request-leaderboard__item">
                          <span className="request-leaderboard__rank">{index + 1}</span>
                          <Link href={`/requests/${item.id}`}>{title}</Link>
                          <span className="request-leaderboard__amount">{fundedLabel}</span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </>
          ) : (
            popularItems.length === 0 ? (
              <div className="empty-state">暂无热门资料。</div>
            ) : (
              <ol className="home-popular-list">
                {popularItems.map((item, index) => {
                  const majorLabel = formatMajorDisplay(item.major);
                  const context = [item.school, item.college, majorLabel].filter(Boolean).join(' · ');
                  return (
                    <li key={item.id} className="home-popular-item">
                      <span className={`home-popular-rank ${index < 3 ? 'is-top' : ''}`}>{index + 1}</span>
                      <div className="home-popular-copy">
                        <Link href={materialPath(item.id, item.title)}>{item.title}</Link>
                        <span>{context || '资料信息待完善'}</span>
                      </div>
                      <span className="home-popular-downloads">下载 {item.downloadCount ?? 0}</span>
                    </li>
                  );
                })}
              </ol>
            )
          )}
        </div>
      </section>

      <section className="card recommend-card">
        <div className="materials-header">
          <div>
            <h2 className="card-title">为你推荐</h2>
            {recommendationHint ? <p className="help-text">{recommendationHint}</p> : null}
          </div>
          <div className="request-header-actions">
            <Link className="button primary small" href="/me#profile">
              完善主页
            </Link>
          </div>
        </div>
        {recommendedItems.length === 0 ? (
          <div className="empty-state">{recommendationEmpty}</div>
        ) : (
          <>
            <ul className="recommend-list" onScroll={handleRecommendationScroll}>
              {recommendedItems.map((item) => {
                const majorLabel = formatMajorDisplay(item.major);
                return (
                  <li key={item.id} className="recommend-item">
                    <Link href={materialPath(item.id, item.title)}>{item.title}</Link>
                    <div className="recommend-meta">
                      <span className="recommend-meta__school">
                        {(item.school || '未知学校') + (item.college ? ` · ${item.college}` : '') + (majorLabel ? ` · ${majorLabel}` : '')}
                      </span>
                      <span className="recommend-meta__downloads">下载 {item.downloadCount ?? 0}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
            {recommendListAtEnd ? (
              <div className="recommend-expand">
                <Link className="button ghost small" href="#materials-list">
                  查看更多资料
                </Link>
              </div>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
