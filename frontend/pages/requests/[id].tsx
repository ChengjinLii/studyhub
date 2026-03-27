import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import NavBar from '../../components/NavBar';
import { readSession } from '../../lib/auth';
import { fetchMaterialPreview } from '../../lib/api';
import { fetchBackend, getRequestOrigin } from '../../lib/apiBase';
import { formatDate } from '../../lib/format';
import { materialPath } from '../../lib/slug';
import { MaterialPreview } from '../../types/material';
import { MaterialRequestContributionItem, MaterialRequestItem, MaterialRequestResponse } from '../../types/request';
import { SessionUser } from '../../types/user';
import { getTierLabel } from '../../constants/request';

interface RequestDetailProps {
  user: SessionUser;
  request: MaterialRequestItem | null;
  responses: MaterialRequestResponse[];
  contributions: MaterialRequestContributionItem[];
}

const parseApiResponse = async (resp: Response) => {
  const text = await resp.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as { ok?: boolean; msg?: string; data?: unknown };
  } catch {
    return null;
  }
};

export default function RequestDetailPage({ user, request, responses, contributions }: RequestDetailProps) {
  const [requestState, setRequestState] = useState(request);
  const [acceptLoadingId, setAcceptLoadingId] = useState<number | null>(null);
  const [acceptNotice, setAcceptNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [disputeLoadingId, setDisputeLoadingId] = useState<number | null>(null);
  const [disputeNotice, setDisputeNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [contributionState, setContributionState] = useState<MaterialRequestContributionItem[]>(contributions);
  const [contributionNotice, setContributionNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [contributionActionLoading, setContributionActionLoading] = useState<Record<number, boolean>>({});
  const [previewMap, setPreviewMap] = useState<Record<number, MaterialPreview | null>>({});
  const [previewLoading, setPreviewLoading] = useState<Record<number, boolean>>({});
  const [previewError, setPreviewError] = useState<Record<number, string>>({});
  const [previewLoaded, setPreviewLoaded] = useState<Record<number, number[]>>({});
  const [previewReady, setPreviewReady] = useState<Record<number, boolean>>({});

  useEffect(() => {
    setRequestState(request);
    setContributionState(contributions);
  }, [request]);

  const formatBudget = (budget?: number | null) => {
    if (budget == null) return '预算不限';
    return `${budget} 元`;
  };

  const formatContributionDeadline = (item: MaterialRequestContributionItem) => {
    if (item.deadlineAt) {
      return `截止 ${formatDate(item.deadlineAt)}`;
    }
    return `期限 ${getTierLabel(item.deadlineTier)}`;
  };


  const scopeLabels = useMemo(
    () =>
      [
        requestState?.school ? `学校：${requestState.school}` : null,
        requestState?.college ? `学院：${requestState.college}` : null,
        requestState?.major ? `专业：${requestState.major}` : null,
      ]
        .filter(Boolean) as string[],
    [requestState]
  );

  const buildUploadLink = (item: MaterialRequestItem) => {
    const params = new URLSearchParams();
    params.set('requestId', String(item.id));
    if (item.course) params.set('course', item.course);
    if (item.keyword) params.set('keyword', item.keyword);
    if (item.budget != null) params.set('budget', String(item.budget));
    if (item.previewRequirement) params.set('previewRequirement', item.previewRequirement);
    return `/upload?${params.toString()}`;
  };

  const handleAccept = async (responseId: number) => {
    if (!requestState?.id) return;
    if (acceptLoadingId) return;
    if (typeof window !== 'undefined') {
      const confirmed = window.confirm('确认采纳该应答并进入结算吗？');
      if (!confirmed) return;
    }
    setAcceptNotice(null);
    setAcceptLoadingId(responseId);
    try {
      const resp = await fetchBackend(`/requests/${requestState.id}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ responseId }),
      });
      const json = await parseApiResponse(resp);
      if (!resp.ok || !json?.ok) {
        throw new Error(json?.msg || `采纳失败（${resp.status}）`);
      }
      const nextRequest = json.data as MaterialRequestItem;
      setRequestState(nextRequest);
      setAcceptNotice({ type: 'success', text: '已采纳该应答，进入结算流程。' });
    } catch (error: any) {
      setAcceptNotice({ type: 'error', text: error.message || '采纳失败' });
    } finally {
      setAcceptLoadingId(null);
    }
  };

  const handleDispute = async (responseId: number) => {
    if (!requestState?.id) return;
    if (disputeLoadingId) return;
    if (typeof window !== 'undefined') {
      const reason = window.prompt('请输入不收货理由（至少 10 字）', '');
      if (!reason) return;
      const trimmedReason = reason.trim();
      if (trimmedReason.length < 10) {
        setDisputeNotice({ type: 'error', text: '不收货理由需至少 10 字。' });
        return;
      }
      setDisputeNotice(null);
      setDisputeLoadingId(responseId);
      try {
      const resp = await fetchBackend(`/requests/${requestState.id}/dispute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ responseId, reason: trimmedReason }),
      });
      const json = await parseApiResponse(resp);
      if (!resp.ok || !json?.ok) {
        throw new Error(json?.msg || `提交失败（${resp.status}）`);
      }
        const nextRequest = json.data as MaterialRequestItem;
        setRequestState(nextRequest);
        setDisputeNotice({ type: 'success', text: '已提交仲裁申请，等待管理员处理。' });
      } catch (error: any) {
        setDisputeNotice({ type: 'error', text: error.message || '提交失败' });
      } finally {
        setDisputeLoadingId(null);
      }
    }
  };

  const handlePreviewLoad = async (responseId: number) => {
    const response = responses.find((item) => item.id === responseId);
    if (!response?.materialId) return;
    setPreviewLoading((prev) => ({ ...prev, [responseId]: true }));
    setPreviewError((prev) => ({ ...prev, [responseId]: '' }));
    setPreviewLoaded((prev) => ({ ...prev, [responseId]: [] }));
    try {
      const data = await fetchMaterialPreview(response.materialId);
      setPreviewMap((prev) => ({ ...prev, [responseId]: data }));
    } catch (error: any) {
      setPreviewError((prev) => ({ ...prev, [responseId]: error.message || '预览加载失败' }));
    } finally {
      setPreviewLoading((prev) => ({ ...prev, [responseId]: false }));
    }
  };

  const markPreviewViewed = async (responseId: number, loadedCount: number) => {
    if (!requestState?.id) return;
    if (previewReady[responseId]) return;
    try {
      const resp = await fetchBackend(`/requests/${requestState.id}/preview-view`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ responseId, loadedCount }),
      });
      const json = await parseApiResponse(resp);
      if (!resp.ok || !json?.ok) {
        throw new Error(json?.msg || `预览记录失败（${resp.status}）`);
      }
      setPreviewReady((prev) => ({ ...prev, [responseId]: true }));
    } catch (error: any) {
      setPreviewError((prev) => ({ ...prev, [responseId]: error.message || '预览记录失败' }));
    }
  };

  const handlePreviewImageLoaded = (responseId: number, index: number) => {
    setPreviewLoaded((prev) => {
      const loaded = prev[responseId] ? [...prev[responseId]] : [];
      if (!loaded.includes(index)) {
        loaded.push(index);
      }
      if (loaded.length >= 2 && !previewReady[responseId]) {
        void markPreviewViewed(responseId, loaded.length);
      }
      return { ...prev, [responseId]: loaded };
    });
  };

  const handleUpdateDeadline = async (item: MaterialRequestContributionItem) => {
    if (!item.id) return;
    if (typeof window !== 'undefined') {
      const choice = window.prompt('选择新的期限档位（24H/WEEK/MONTH/FLEX）', item.deadlineTier || 'FLEX');
      if (!choice) return;
      const normalized = choice.trim().toUpperCase();
      if (!normalized) return;
      setContributionNotice(null);
      setContributionActionLoading((prev) => ({ ...prev, [item.id]: true }));
      try {
        const resp = await fetchBackend(`/requests/contributions/${item.id}/deadline`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ deadlineTier: normalized }),
        });
        const json = await parseApiResponse(resp);
        if (!resp.ok || !json?.ok) {
          throw new Error(json?.msg || `修改失败（${resp.status}）`);
        }
        const next = json.data as MaterialRequestContributionItem;
        setContributionState((prev) => prev.map((entry) => (entry.id === next.id ? next : entry)));
        setContributionNotice({ type: 'success', text: '已更新期限。' });
      } catch (error: any) {
        setContributionNotice({ type: 'error', text: error.message || '修改失败' });
      } finally {
        setContributionActionLoading((prev) => ({ ...prev, [item.id]: false }));
      }
    }
  };

  const handleCancelContribution = async (item: MaterialRequestContributionItem) => {
    if (!item.id) return;
    if (typeof window !== 'undefined') {
      const confirmed = window.confirm('确定要提前结束该贡献吗？将收取 3% 手续费。');
      if (!confirmed) return;
    }
    setContributionNotice(null);
    setContributionActionLoading((prev) => ({ ...prev, [item.id]: true }));
    try {
      const resp = await fetchBackend(`/requests/contributions/${item.id}/cancel`, { method: 'POST' });
      const json = await parseApiResponse(resp);
      if (!resp.ok || !json?.ok) {
        throw new Error(json?.msg || `结束失败（${resp.status}）`);
      }
      const next = json.data as MaterialRequestContributionItem;
      setContributionState((prev) => prev.map((entry) => (entry.id === next.id ? next : entry)));
      if (requestState && item.amount != null) {
        setRequestState((prev) => {
          if (!prev) return prev;
          const funded = prev.fundedAmount ?? 0;
          const nextFunded = Math.max(0, funded - item.amount);
          const count = prev.contributionCount ?? 0;
          return {
            ...prev,
            fundedAmount: nextFunded,
            contributionCount: Math.max(0, count - 1),
          };
        });
      }
      setContributionNotice({ type: 'success', text: '已提交结束申请。' });
    } catch (error: any) {
      setContributionNotice({ type: 'error', text: error.message || '结束失败' });
    } finally {
      setContributionActionLoading((prev) => ({ ...prev, [item.id]: false }));
    }
  };

  if (!requestState) {
    return (
      <>
        <NavBar user={user} />
        <main className="container">
          <section className="card request-detail-card">
            <h2>未找到求购</h2>
            <p className="help-text">该求购可能已关闭或不存在。</p>
            <Link className="button primary" href="/">
              返回首页
            </Link>
          </section>
        </main>
      </>
    );
  }

  const title = requestState.course || '求购需求';
  const ownerLabel = requestState.requesterName || '匿名同学';
  const acceptedResponseId = requestState.acceptedResponseId ?? null;
  const canAccept = Boolean(requestState.owner && requestState.status === 'OPEN' && !acceptedResponseId);
  const canDispute = Boolean(requestState.owner && requestState.status === 'OPEN' && !acceptedResponseId);
  const canFollow = Boolean(!requestState.owner && requestState.status === 'OPEN');
  const canRespond = Boolean(requestState.responded || (requestState.responseCount ?? 0) === 0);

  return (
    <>
      <NavBar user={user} />
      <main className="container">
        <section className="card request-card request-detail-card">
          <div className="materials-header">
            <div>
              <h2 className="card-title">求购详情</h2>
            </div>
            <div className="request-header-actions">
              {canFollow && (
                <>
                  <Link className="button primary" href={`/requests/${requestState.id}/follow`}>
                    去跟购
                  </Link>
                  {canRespond ? (
                    <Link className="button ghost" href={buildUploadLink(requestState)}>
                      应答
                    </Link>
                  ) : (
                    <span className="help-text">已有应答</span>
                  )}
                </>
              )}
              <Link className="button ghost" href="/">
                返回首页
              </Link>
            </div>
          </div>
          <div className="request-list-wrapper">
            <ul className="request-list">
              <li className="request-item">
                <div className="request-title-row">
                  <div className="request-title">
                    <strong>{title}</strong>
                  </div>
                </div>
                <div className="request-footer">
                  <span className="request-footer__tag request-footer__user">{ownerLabel}</span>
                  <span className="request-footer__tag request-footer__budget">{formatBudget(requestState.budget)}</span>
                  {requestState.urgencyTier && (
                    <span className="request-footer__tag">期限 {getTierLabel(requestState.urgencyTier)}</span>
                  )}
                  {requestState.creatorFloor != null && (
                    <span className="request-footer__tag">跟购底价 ¥{requestState.creatorFloor}</span>
                  )}
                  <span className="request-footer__tag request-footer__funded">
                    {requestState.fundedAmount != null && requestState.fundedAmount > 0
                      ? `已筹 ¥${requestState.fundedAmount}`
                      : '已筹 待议'}
                  </span>
                  <span className="request-footer__tag request-footer__responses">应答 {requestState.responseCount ?? 0}</span>
                  {requestState.status && requestState.status !== 'OPEN' && (
                    <span className="request-footer__tag request-footer__status">状态：{requestState.status}</span>
                  )}
                  {requestState.createdAt && (
                    <span className="request-footer__tag">{formatDate(requestState.createdAt)}</span>
                  )}
                </div>
              </li>
            </ul>
            {acceptNotice && (
              <p className={acceptNotice.type === 'error' ? 'error-text' : 'success-text'}>
                {acceptNotice.text}
              </p>
            )}
            {disputeNotice && (
              <p className={disputeNotice.type === 'error' ? 'error-text' : 'success-text'}>
                {disputeNotice.text}
              </p>
            )}
            {contributionNotice && (
              <p className={contributionNotice.type === 'error' ? 'error-text' : 'success-text'}>
                {contributionNotice.text}
              </p>
            )}
            {scopeLabels.length > 0 && (
              <div className="request-detail-tags">
                {scopeLabels.map((label) => (
                  <span key={label}>{label}</span>
                ))}
              </div>
            )}
            {requestState.previewRequirement && (
              <div className="request-preview-rule">
                <strong>预览要求：</strong>
                <span>{requestState.previewRequirement}</span>
              </div>
            )}
            {requestState.keyword && <p className="request-detail-body">{requestState.keyword}</p>}
            <div className="request-detail-responses">
              <h3>当前应答</h3>
              {responses.length === 0 ? (
                <p className="help-text">暂无应答。</p>
              ) : (
                <ul className="request-response-list">
                  {responses.map((response) => (
                    <li key={response.id}>
                      <div className="request-response-header">
                        <span>{response.responderName || '匿名投稿者'}</span>
                        <div className="request-response-actions">
                          {response.materialId && (
                            <button
                              className="button ghost small"
                              type="button"
                              onClick={() => handlePreviewLoad(response.id)}
                              disabled={Boolean(previewLoading[response.id])}
                            >
                              {previewLoading[response.id] ? '加载中...' : '预览资料'}
                            </button>
                          )}
                          {response.materialId && (
                            <Link href={materialPath(response.materialId)}>查看资料</Link>
                          )}
                        </div>
                      </div>
                      <p>{response.message || '已应答'}</p>
                      {response.revisionCount != null && response.revisionCount > 0 && (
                        <p className="help-text">已修订 {response.revisionCount}/2</p>
                      )}
                      {previewError[response.id] && <p className="error-text">{previewError[response.id]}</p>}
                      {previewMap[response.id] && (
                        <div className="request-preview">
                          {previewMap[response.id]?.images?.slice(0, 2).map((image) => (
                            <img
                              key={image.index}
                              src={image.img.src}
                              srcSet={image.img.srcSet || undefined}
                              sizes={image.img.sizes || undefined}
                              alt={`预览第 ${image.index + 1} 页`}
                              loading="lazy"
                              onLoad={() => handlePreviewImageLoaded(response.id, image.index)}
                            />
                          ))}
                          {previewMap[response.id]?.status !== 'done' && (
                            <p className="help-text">
                              {previewMap[response.id]?.message || '预览生成中，请稍候再试'}
                            </p>
                          )}
                        </div>
                      )}
                      {acceptedResponseId === response.id ? (
                        <div className="request-response-footer">
                          <span className="badge badge-success">已采纳</span>
                        </div>
                      ) : canAccept && response.materialId ? (
                        <div className="request-response-footer">
                          <button
                            className="button primary small"
                            type="button"
                            onClick={() => handleAccept(response.id)}
                            disabled={Boolean(acceptLoadingId) || !previewReady[response.id]}
                          >
                            {acceptLoadingId === response.id ? '处理中...' : '采纳并结算'}
                          </button>
                          {canDispute && (
                            <button
                              className="button ghost small"
                              type="button"
                              onClick={() => handleDispute(response.id)}
                              disabled={Boolean(disputeLoadingId) || !previewReady[response.id]}
                            >
                              {disputeLoadingId === response.id ? '处理中...' : '不收货'}
                            </button>
                          )}
                          {!previewReady[response.id] && (
                            <span className="help-text">需先查看前两张预览图</span>
                          )}
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="request-detail-responses">
              <h3>跟购记录</h3>
              {contributionState.length === 0 ? (
                <p className="help-text">暂无跟购记录。</p>
              ) : (
                <ul className="request-response-list">
                  {contributionState.map((item) => (
                    <li key={item.id}>
                      <div className="request-response-header">
                        <span>{item.contributorName || '匿名同学'}</span>
                        <span>{item.type === 'OWNER' ? '发起' : '跟购'}</span>
                      </div>
                      <p>{item.amount != null ? `¥${item.amount}` : '金额待确认'}</p>
                      <p className="help-text">{formatContributionDeadline(item)}</p>
                      {item.contributorId === user.id && requestState.status === 'OPEN' && item.status === 'PAID' && (
                        <div className="request-response-footer">
                          <button
                            className="button ghost small"
                            type="button"
                            onClick={() => handleUpdateDeadline(item)}
                            disabled={Boolean(contributionActionLoading[item.id])}
                          >
                            延长期限
                          </button>
                          <button
                            className="button ghost danger small"
                            type="button"
                            onClick={() => handleCancelContribution(item)}
                            disabled={Boolean(contributionActionLoading[item.id])}
                          >
                            提前结束
                          </button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<RequestDetailProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const requestId = typeof ctx.params?.id === 'string' ? ctx.params.id : '';
  if (!session.user || !session.token) {
    return {
      redirect: {
        destination: `/login?next=${encodeURIComponent(`/requests/${requestId}`)}`,
        permanent: false,
      },
    };
  }
  if (!requestId) {
    return { notFound: true };
  }
  const origin = getRequestOrigin(ctx.req);
  try {
    const detailResp = await fetchBackend(
      `/requests/${requestId}`,
      {
        headers: {
          Authorization: `Bearer ${session.token}`,
        },
      },
      origin
    );
    const detailJson = await detailResp.json();
    if (!detailResp.ok || !detailJson.ok || !detailJson.data) {
      if (detailResp.status === 404) {
        return { notFound: true };
      }
      throw new Error(detailJson.msg || '加载失败');
    }
    const request = detailJson.data as MaterialRequestItem;
    let responses: MaterialRequestResponse[] = [];
    let contributions: RequestDetailProps['contributions'] = [];
    const responseResp = await fetchBackend(
      `/requests/${requestId}/responses`,
      {
        headers: {
          Authorization: `Bearer ${session.token}`,
        },
      },
      origin
    );
    const responseJson = await responseResp.json();
    if (responseResp.ok && responseJson.ok && Array.isArray(responseJson.data)) {
      responses = responseJson.data as MaterialRequestResponse[];
    }
    const contributionsResp = await fetchBackend(
      `/requests/${requestId}/contributions`,
      {
        headers: {
          Authorization: `Bearer ${session.token}`,
        },
      },
      origin
    );
    const contributionsJson = await contributionsResp.json();
    if (contributionsResp.ok && contributionsJson.ok && Array.isArray(contributionsJson.data)) {
      contributions = contributionsJson.data as RequestDetailProps['contributions'];
    }
    return {
      props: {
        user: session.user,
        request,
        responses,
        contributions,
      },
    };
  } catch {
    return {
      props: {
        user: session.user,
        request: null,
        responses: [],
        contributions: [],
      },
    };
  }
};
