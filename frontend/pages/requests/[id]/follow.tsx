import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useEffect, useMemo, useRef, useState } from 'react';
import NavBar from '../../../components/NavBar';
import { readSession } from '../../../lib/auth';
import { fetchBackend, getRequestOrigin } from '../../../lib/apiBase';
import { toErrorMessage } from '../../../lib/errors';
import { submitTrustedPaymentForm } from '../../../lib/safePaymentForm';
import { formatDate } from '../../../lib/format';
import { REQUEST_TIERS, RequestTierValue, getTierLabel } from '../../../constants/request';
import { MaterialRequestItem } from '../../../types/request';
import { SessionUser } from '../../../types/user';

interface RequestFollowProps {
  user: SessionUser;
  request: MaterialRequestItem | null;
}

export default function RequestFollowPage({ user, request }: RequestFollowProps) {
  const [requestState] = useState(request);
  const initialTier = (requestState?.urgencyTier as RequestTierValue) || 'FLEX';
  const [followTier, setFollowTier] = useState<RequestTierValue>(initialTier);
  const [followAmount, setFollowAmount] = useState(() => {
    const tierConfig = REQUEST_TIERS.find((item) => item.value === initialTier) || REQUEST_TIERS[REQUEST_TIERS.length - 1];
    const creatorFloor = requestState?.creatorFloor ?? 0;
    const minFollow = Math.max(tierConfig.followerMin, creatorFloor || 0, 5);
    return String(minFollow);
  });
  const [followLoading, setFollowLoading] = useState(false);
  const [followNotice, setFollowNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [followFormHtml, setFollowFormHtml] = useState('');
  const followFormRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!followFormHtml || !followFormRef.current) return;
    try {
      submitTrustedPaymentForm(followFormRef.current, followFormHtml);
    } catch (error: unknown) {
      setFollowNotice({ type: 'error', text: toErrorMessage(error, '支付表单校验失败') });
    }
  }, [followFormHtml]);

  const followTierConfig = useMemo(
    () => REQUEST_TIERS.find((item) => item.value === followTier) || REQUEST_TIERS[REQUEST_TIERS.length - 1],
    [followTier]
  );

  const minFollowAmount = useMemo(() => {
    const creatorFloor = requestState?.creatorFloor ?? 0;
    return Math.max(followTierConfig.followerMin, creatorFloor || 0, 5);
  }, [followTierConfig, requestState]);

  useEffect(() => {
    const current = Number(followAmount);
    if (!Number.isFinite(current) || current < minFollowAmount) {
      setFollowAmount(String(minFollowAmount));
    }
  }, [minFollowAmount, followAmount]);

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

  const canFollow = Boolean(!requestState.owner && requestState.status === 'OPEN');
  const ownerLabel = requestState.requesterName || '匿名同学';
  const title = requestState.course || '求购需求';

  const handleFollow = async () => {
    if (!canFollow) {
      setFollowNotice({ type: 'error', text: '该求购暂不可跟购。' });
      return;
    }
    const amountValue = Number(followAmount);
    if (!Number.isFinite(amountValue) || amountValue < minFollowAmount) {
      setFollowNotice({ type: 'error', text: `跟购金额需不低于 ${minFollowAmount} 元。` });
      return;
    }
    setFollowNotice(null);
    setFollowLoading(true);
    try {
      const resp = await fetchBackend(`/requests/${requestState.id}/contributions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: Math.round(amountValue * 100), deadlineTier: followTier }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '跟购失败');
      }
      const data = json.data || {};
      if (!data.form) {
        throw new Error('支付表单获取失败');
      }
      setFollowFormHtml(data.form as string);
    } catch (error: unknown) {
      setFollowNotice({ type: 'error', text: toErrorMessage(error, '跟购失败') });
    } finally {
      setFollowLoading(false);
    }
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container">
        <section className="card request-card request-detail-card">
          <div className="materials-header">
            <div>
              <h2 className="card-title">跟购支持</h2>
              <p className="help-text">选择期限与金额后完成支付，系统将自动记录。</p>
            </div>
            <div className="request-header-actions">
              <Link className="button ghost" href={`/requests/${requestState.id}`}>
                返回求购详情
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
                  {requestState.budget != null ? (
                    <span className="request-footer__tag request-footer__budget">预算 {requestState.budget} 元</span>
                  ) : (
                    <span className="request-footer__tag request-footer__budget">预算不限</span>
                  )}
                  {requestState.urgencyTier && (
                    <span className="request-footer__tag">期限 {getTierLabel(requestState.urgencyTier)}</span>
                  )}
                  {requestState.creatorFloor != null && (
                    <span className="request-footer__tag">跟购底价 ¥{requestState.creatorFloor}</span>
                  )}
                  {requestState.createdAt && (
                    <span className="request-footer__tag">{formatDate(requestState.createdAt)}</span>
                  )}
                </div>
              </li>
            </ul>
            <div className="request-form">
              <div>
                <label htmlFor="follow-tier">期限档位</label>
                <select
                  id="follow-tier"
                  className="select"
                  value={followTier}
                  onChange={(e) => setFollowTier(e.target.value as RequestTierValue)}
                  disabled={!canFollow || followLoading}
                >
                  {REQUEST_TIERS.map((tier) => (
                    <option key={tier.value} value={tier.value}>
                      {tier.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="follow-amount">跟购金额（元）</label>
                <input
                  id="follow-amount"
                  className="input"
                  type="number"
                  min={minFollowAmount}
                  step="1"
                  value={followAmount}
                  onChange={(e) => setFollowAmount(e.target.value)}
                  disabled={!canFollow || followLoading}
                />
              </div>
              <div className="request-actions">
                <span className="help-text">最低 {minFollowAmount} 元</span>
                <button className="button primary" type="button" onClick={handleFollow} disabled={!canFollow || followLoading}>
                  {followLoading ? '处理中...' : '确认跟购并支付'}
                </button>
              </div>
            </div>
            {followNotice && (
              <p className={followNotice.type === 'error' ? 'error-text' : 'success-text'}>{followNotice.text}</p>
            )}
          </div>
        </section>
        <div ref={followFormRef} style={{ display: 'none' }} />
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<RequestFollowProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const requestId = typeof ctx.params?.id === 'string' ? ctx.params.id : '';
  if (!session.user || !session.token) {
    return {
      redirect: {
        destination: `/login?next=${encodeURIComponent(`/requests/${requestId}/follow`)}`,
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
    return {
      props: {
        user: session.user,
        request: detailJson.data as MaterialRequestItem,
      },
    };
  } catch {
    return {
      props: {
        user: session.user,
        request: null,
      },
    };
  }
};
