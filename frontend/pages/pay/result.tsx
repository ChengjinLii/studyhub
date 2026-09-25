import { GetServerSideProps } from 'next';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import NavBar from '../../components/NavBar';
import { readSession } from '../../lib/auth';
import { fetchOrderStatus } from '../../lib/paymentApi';
import { toErrorMessage } from '../../lib/errors';
import {
  PayStatusCheckOutcome,
  isPendingPayStatus,
  resolvePayResultOrderNo,
  resolvePayResultView,
  startPayStatusPolling,
} from '../../lib/payResultStatus';
import { materialPath } from '../../lib/slug';
import { SessionUser } from '../../types/user';

interface PayResultProps {
  user: SessionUser;
  orderNo: string;
}

export default function PayResult({ user, orderNo }: PayResultProps) {
  const router = useRouter();
  const [status, setStatus] = useState('CREATED');
  const [materialId, setMaterialId] = useState<number | null>(null);
  const [requestId, setRequestId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [pollingExhausted, setPollingExhausted] = useState(false);
  const inFlightRef = useRef(false);
  const routerRef = useRef(router);

  useEffect(() => {
    routerRef.current = router;
  }, [router]);

  const canRedirect = useMemo(() => status === 'PAID' && (materialId || requestId), [status, materialId, requestId]);
  const view = resolvePayResultView(status, pollingExhausted);

  const loadStatus = useCallback(
    async (forceCheck = false): Promise<PayStatusCheckOutcome> => {
      if (!orderNo || inFlightRef.current) return 'pending';
      inFlightRef.current = true;
      setLoading(true);
      setError('');
      try {
        const result = await fetchOrderStatus(orderNo, forceCheck);
        if (result.unauthorized) {
          void routerRef.current.push({ pathname: '/login', query: { next: routerRef.current.asPath } });
          return 'settled';
        }
        const data = result.data || {};
        const nextStatus = data.status || 'CREATED';
        setStatus(nextStatus);
        if (data.materialId) {
          setMaterialId(data.materialId as number);
        }
        if (data.requestId) {
          setRequestId(data.requestId as number);
        }
        return isPendingPayStatus(nextStatus) ? 'pending' : 'settled';
      } catch (err: unknown) {
        setError(toErrorMessage(err, '查询订单状态失败'));
        return 'pending';
      } finally {
        inFlightRef.current = false;
        setLoading(false);
      }
    },
    [orderNo]
  );

  useEffect(() => {
    setPollingExhausted(false);
    return startPayStatusPolling({ check: loadStatus, onExhausted: () => setPollingExhausted(true) });
  }, [loadStatus]);

  useEffect(() => {
    if (!canRedirect) return;
    if (materialId) {
      void router.push(`${materialPath(materialId)}?autoDownload=1`);
    } else if (requestId) {
      void router.push(`/requests/${requestId}`);
    }
  }, [canRedirect, materialId, requestId, router]);

  const backHref = materialId ? materialPath(materialId) : requestId ? `/requests/${requestId}` : '/';
  const backLabel = materialId ? '返回资料页' : requestId ? '返回求购详情' : '返回首页';

  return (
    <>
      <NavBar user={user} />
      <main className="container payment-page">
        <section className="card payment-card">
          <h1>{view.title}</h1>
          <p className="help-text">{view.description}</p>
          <div style={{ marginTop: 12 }}>
            <p className="help-text">订单号：{orderNo}</p>
            {loading ? <p className="help-text">正在确认支付状态…</p> : null}
            {error ? <p className="error-text">{error}</p> : null}
          </div>
          <div className="payment-actions">
            {view.tone === 'failure' ? (
              <Link className="button primary" href={backHref}>
                {backLabel}
              </Link>
            ) : null}
            {view.tone === 'pending' || view.tone === 'timeout' ? (
              <button className="button primary" type="button" onClick={() => void loadStatus(true)} disabled={loading}>
                {loading ? '刷新中…' : '刷新状态'}
              </button>
            ) : null}
            {view.tone === 'timeout' || (view.tone === 'success' && !materialId && !requestId) ? (
              <Link className="button ghost" href="/me">
                查看我的订单
              </Link>
            ) : null}
          </div>
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<PayResultProps> = async (ctx) => {
  const orderNo = resolvePayResultOrderNo(ctx.query);
  if (!orderNo) {
    return { notFound: true };
  }
  const session = readSession(ctx.req);
  if (!session.user || !session.token) {
    return {
      redirect: {
        destination: `/login?next=${encodeURIComponent(`/pay/result?orderNo=${encodeURIComponent(orderNo)}`)}`,
        permanent: false,
      },
    };
  }
  return {
    props: {
      user: session.user,
      orderNo,
    },
  };
};
