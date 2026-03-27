import { GetServerSideProps } from 'next';
import { useRouter } from 'next/router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import NavBar from '../../components/NavBar';
import { readSession } from '../../lib/auth';
import { fetchBackend } from '../../lib/apiBase';
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

  const canRedirect = useMemo(() => status === 'PAID' && (materialId || requestId), [status, materialId, requestId]);

  const loadStatus = useCallback(async (forceCheck = false) => {
    if (!orderNo) return;
    setLoading(true);
    setError('');
    try {
      const isRequestContribution = orderNo.startsWith('RQ');
      const forceSuffix = forceCheck ? '&force=1' : '';
      const endpoint = isRequestContribution
        ? `/requests/contributions/status?orderNo=${encodeURIComponent(orderNo)}${forceSuffix}`
        : `/pay/orders/status?orderNo=${encodeURIComponent(orderNo)}${forceSuffix}`;
      let resp = await fetchBackend(endpoint);
      if (resp.status === 401) {
        router.push({ pathname: '/login', query: { next: router.asPath } });
        return;
      }
      let json = await resp.json();
      if ((!resp.ok || !json.ok) && !isRequestContribution) {
        resp = await fetchBackend(`/requests/contributions/status?orderNo=${encodeURIComponent(orderNo)}`);
        json = await resp.json();
      }
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '查询订单状态失败');
      }
      const data = json.data || {};
      setStatus(data.status || 'CREATED');
      if (data.materialId) {
        setMaterialId(data.materialId as number);
      }
      if (data.requestId) {
        setRequestId(data.requestId as number);
      }
    } catch (err: any) {
      setError(err.message || '查询订单状态失败');
    } finally {
      setLoading(false);
    }
  }, [orderNo, router]);

  useEffect(() => {
    void loadStatus(true);
  }, [loadStatus]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadStatus(false);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadStatus]);

  useEffect(() => {
    if (!canRedirect) return;
    if (materialId) {
      void router.push(`${materialPath(materialId)}?autoDownload=1`);
    } else if (requestId) {
      void router.push(`/requests/${requestId}`);
    }
  }, [canRedirect, materialId, requestId, router]);

  return (
    <>
      <NavBar user={user} />
      <main className="container payment-page">
        <section className="card payment-card">
          <h1>支付完成，系统确认中…</h1>
          <p className="help-text">系统将自动校验支付结果并跳转资料页。</p>
          <div style={{ marginTop: 12 }}>
            <p className="help-text">订单号：{orderNo}</p>
            {loading ? <p className="help-text">正在确认支付状态…</p> : null}
            {error ? <p className="error-text">{error}</p> : null}
            {status === 'PAID' && !materialId ? (
              <p className="help-text">支付已确认，正在准备跳转…</p>
            ) : null}
          </div>
          <div className="payment-actions">
            <button className="button primary" type="button" onClick={() => loadStatus(true)} disabled={loading}>
              {loading ? '刷新中…' : '刷新状态'}
            </button>
          </div>
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<PayResultProps> = async (ctx) => {
  const orderNo = typeof ctx.query.orderNo === 'string' ? ctx.query.orderNo : '';
  if (!orderNo) {
    return { notFound: true };
  }
  const session = readSession(ctx.req);
  if (!session.user || !session.token) {
    return {
      redirect: {
        destination: `/login?next=/pay/result?orderNo=${encodeURIComponent(orderNo)}`,
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
