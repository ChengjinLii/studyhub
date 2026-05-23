import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useCallback, useEffect, useRef, useState } from 'react';
import NavBar from '../../components/NavBar';
import { readSession, hasRole } from '../../lib/auth';
import { fetchBackend, getRequestOrigin, resolveApiBase } from '../../lib/apiBase';
import { toErrorMessage } from '../../lib/errors';
import { materialPath, userPath } from '../../lib/slug';
import { SessionUser, RoleMask } from '../../types/user';
import { MaterialDetail } from '../../types/material';

interface PayPageProps {
  user: SessionUser;
  material: MaterialDetail;
}

export default function PayPage({ user, material }: PayPageProps) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [formHtml, setFormHtml] = useState('');
  const startedRef = useRef(false);
  const formContainerRef = useRef<HTMLDivElement | null>(null);

  const startPayment = useCallback(async () => {
    if (!material) return;
    setLoading(true);
    setError('');
    try {
      const resp = await fetchBackend('/alipay-payments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ materialId: material.id }),
      });
      if (resp.status === 401) {
        router.push({ pathname: '/login', query: { next: router.asPath } });
        return;
      }
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '发起支付失败');
      }
      const data = json.data || {};
      if (data.status === 'PAID') {
        await router.push(`${materialPath(material.id, material.title)}?autoDownload=1`);
        return;
      }
      if (!data.form) {
        throw new Error('支付表单获取失败');
      }
      setFormHtml(data.form as string);
    } catch (err: unknown) {
      setError(toErrorMessage(err, '发起支付失败'));
    } finally {
      setLoading(false);
    }
  }, [material, router]);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void startPayment();
  }, [startPayment]);

  useEffect(() => {
    if (!formHtml || !formContainerRef.current) return;
    formContainerRef.current.innerHTML = formHtml;
    const form = formContainerRef.current.querySelector('form') as HTMLFormElement | null;
    if (form) {
      form.submit();
    }
  }, [formHtml]);

  return (
    <>
      <NavBar user={user} />
      <main className="container payment-page">
        <section className="card payment-card">
          <h1>跳转支付宝支付</h1>
          <p className="help-text">支付完成后会自动跳回，并继续处理下载。</p>
          <div className="payment-material-info">
            <div>
              <strong>{material.title}</strong>
              <p>
                价格：¥{(material.price ?? 0).toFixed(0)} · 发布者：
                {material.uploaderId ? (
                  <Link
                    className="text-button"
                    href={userPath(material.uploaderId, material.uploaderNickname || material.uploaderUsername || '')}
                  >
                    {material.uploaderNickname || material.uploaderUsername || '匿名同学'}
                  </Link>
                ) : (
                  material.uploaderNickname || material.uploaderUsername || '匿名同学'
                )}
              </p>
            </div>
            <Link href={materialPath(material.id, material.title)} className="button ghost small">
              返回资料页
            </Link>
          </div>
          <div style={{ marginTop: 12 }}>
            {loading ? (
              <p className="help-text">正在拉起支付宝，请稍候…</p>
            ) : error ? (
              <p className="error-text">{error}</p>
            ) : (
              <p className="help-text">如未自动跳转，可点击按钮重新拉起支付。</p>
            )}
          </div>
          <div className="payment-actions">
            <button className="button primary" type="button" onClick={startPayment} disabled={loading}>
              {loading ? '正在拉起…' : '重新拉起支付'}
            </button>
          </div>
          <div ref={formContainerRef} style={{ display: 'none' }} />
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<PayPageProps> = async (ctx) => {
  const { id } = ctx.query;
  if (typeof id !== 'string') {
    return { notFound: true };
  }
  const session = readSession(ctx.req);
  if (!session.user || !session.token) {
    return {
      redirect: {
        destination: `/login?next=/pay/${id}`,
        permanent: false,
      },
    };
  }
  const isSuperAdmin = hasRole(session.user.roleMask, RoleMask.DEVELOPER);
  const base = resolveApiBase(getRequestOrigin(ctx.req));
  const detailResp = await fetch(`${base}/materials/${id}`, {
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${session.token}`,
    },
  });
  const detailJson = await detailResp.json().catch(() => null);
  if (!detailResp.ok || !detailJson?.ok || !detailJson.data) {
    return { notFound: true };
  }
  const material: MaterialDetail = detailJson.data;
  if (material.free || isSuperAdmin) {
    return {
      redirect: {
        destination: materialPath(material.id, material.title),
        permanent: false,
      },
    };
  }
  return {
    props: {
      user: session.user,
      material,
    },
  };
};
