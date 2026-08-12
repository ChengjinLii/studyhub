import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useState } from 'react';
import NavBar from '../../components/NavBar';
import { fetchMaterialRequests, fetchRequestLeaderboard } from '../../lib/api';
import { getRequestOrigin } from '../../lib/apiBase';
import { readSession } from '../../lib/auth';
import { MaterialRequestItem } from '../../types/request';
import { SessionUser } from '../../types/user';

interface RequestsPageProps {
  user: SessionUser | null;
  requests: MaterialRequestItem[];
  leaderboard: MaterialRequestItem[];
}

const REQUEST_LIST_LIMIT = 24;

const buildUploadLink = (item: MaterialRequestItem) => {
  const params = new URLSearchParams();
  params.set('requestId', String(item.id));
  if (item.course) params.set('course', item.course);
  if (item.keyword) params.set('keyword', item.keyword);
  if (item.budget != null) params.set('budget', String(item.budget));
  if (item.previewRequirement) params.set('previewRequirement', item.previewRequirement);
  return `/upload?${params.toString()}`;
};

const getRequestTitle = (item: MaterialRequestItem) => item.course || item.keyword || '求购需求';

export default function RequestsPage({ user, requests, leaderboard }: RequestsPageProps) {
  const router = useRouter();
  const [visibleRequests, setVisibleRequests] = useState(requests);
  const [requestOffset, setRequestOffset] = useState(requests.length);
  const [hasMoreRequests, setHasMoreRequests] = useState(requests.length === REQUEST_LIST_LIMIT);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState('');
  const handleFollowRequest = (item: MaterialRequestItem) => {
    if (!user) {
      void router.push(`/login?next=${encodeURIComponent(`/requests/${item.id}/follow`)}`);
      return;
    }
    void router.push(`/requests/${item.id}/follow`);
  };

  const handleLoadMore = async () => {
    if (loadingMore || !hasMoreRequests) return;
    setLoadingMore(true);
    setLoadMoreError('');
    try {
      const nextItems = await fetchMaterialRequests({
        sort: 'hot',
        limit: REQUEST_LIST_LIMIT,
        offset: requestOffset,
      });
      setVisibleRequests((current) => {
        const ids = new Set(current.map((item) => item.id));
        return [...current, ...nextItems.filter((item) => !ids.has(item.id))];
      });
      setRequestOffset((current) => current + nextItems.length);
      setHasMoreRequests(nextItems.length === REQUEST_LIST_LIMIT);
    } catch (error) {
      setLoadMoreError(error instanceof Error ? error.message : '求购加载失败，请稍后重试。');
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container requests-page">
        <section className="card requests-hero">
          <span className="requests-hero__eyebrow">Requests</span>
          <h1>求购中心</h1>
          <p>找不到资料时，可以在这里查看同学的求购需求、跟购需求，或直接发布新的求购。</p>
          <div className="requests-hero__actions">
            <Link className="button primary" href="/requests/new" prefetch={false}>
              发布求购
            </Link>
            <Link className="button ghost" href="/materials" prefetch={false}>
              先找资料
            </Link>
          </div>
        </section>

        {leaderboard.length > 0 && (
          <section className="card requests-leaderboard-card">
            <div className="materials-header">
              <div>
                <h2 className="card-title">求购榜</h2>
                <p className="help-text">按已筹金额排序，适合优先响应。</p>
              </div>
            </div>
            <ul className="request-leaderboard__list">
              {leaderboard.map((item, index) => (
                <li key={item.id} className="request-leaderboard__item">
                  <span className="request-leaderboard__rank">{index + 1}</span>
                  <Link href={`/requests/${item.id}`} prefetch={false}>
                    {getRequestTitle(item)}
                  </Link>
                  <span className="request-leaderboard__amount">
                    {item.fundedAmount != null && item.fundedAmount > 0 ? `已筹 ¥${item.fundedAmount}` : '待议'}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="card request-card requests-list-card">
          <div className="materials-header">
            <div>
              <h2 className="card-title">求购列表</h2>
              <p className="help-text">当前展示 {visibleRequests.length} 条求购需求。</p>
            </div>
            {visibleRequests.length > 0 && (
              <div className="request-header-actions">
                <Link className="button primary small" href="/requests/new" prefetch={false}>
                  发布求购
                </Link>
              </div>
            )}
          </div>
          {visibleRequests.length === 0 ? (
            <div className="empty-state requests-empty-state">
              <strong>暂时没有公开的求购需求</strong>
              <span>可以先搜索已有资料；仍未找到时，再发布新的求购。</span>
              <div className="requests-empty-state__actions">
                <Link className="button ghost small" href="/materials" prefetch={false}>
                  搜索资料
                </Link>
                <Link className="button primary small" href="/requests/new" prefetch={false}>
                  发布求购
                </Link>
              </div>
            </div>
          ) : (
            <ul className="request-list">
              {visibleRequests.map((item) => {
                const title = getRequestTitle(item);
                const detailLink = `/requests/${item.id}`;
                const budgetLabel = item.budget != null ? `预算 ¥${item.budget}` : '预算 待议';
                const fundedLabel =
                  item.fundedAmount != null && item.fundedAmount > 0 ? `已筹 ¥${item.fundedAmount}` : '已筹 待议';
                const canRespond = (item.responseCount ?? 0) === 0 || Boolean(item.responded);
                return (
                  <li key={item.id} className="request-item">
                    <div className="request-title-row">
                      <div className="request-title">
                        <Link href={detailLink} prefetch={false}>
                          {title}
                        </Link>
                      </div>
                      <div className="request-action-row">
                        {item.owner ? (
                          <Link className="button ghost small" href={detailLink} prefetch={false}>
                            查看
                          </Link>
                        ) : (
                          <>
                            <button className="button primary small" type="button" onClick={() => handleFollowRequest(item)}>
                              跟购
                            </button>
                            {canRespond ? (
                              <Link className="button ghost small" href={buildUploadLink(item)} prefetch={false}>
                                应答
                              </Link>
                            ) : (
                              <span className="help-text">已有应答</span>
                            )}
                            <Link className="button ghost small" href={detailLink} prefetch={false}>
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
          {loadMoreError ? <p className="error-text requests-load-more__notice">{loadMoreError}</p> : null}
          {visibleRequests.length > 0 ? (
            <div className="requests-load-more">
              {hasMoreRequests ? (
                <button className="button ghost" type="button" onClick={handleLoadMore} disabled={loadingMore}>
                  {loadingMore ? '加载中...' : '加载更多求购'}
                </button>
              ) : (
                <span className="help-text">已显示全部公开求购</span>
              )}
            </div>
          ) : null}
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<RequestsPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const origin = getRequestOrigin(ctx.req);
  const [requests, leaderboard] = await Promise.all([
    fetchMaterialRequests({ sort: 'hot', limit: REQUEST_LIST_LIMIT }, session.token || undefined, origin).catch(() => []),
    fetchRequestLeaderboard(6, session.token || undefined, origin).catch(() => []),
  ]);

  return {
    props: {
      user: session.user,
      requests,
      leaderboard,
    },
  };
};
