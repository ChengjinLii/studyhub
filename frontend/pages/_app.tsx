import type { AppProps } from 'next/app';
import Head from 'next/head';
import { useEffect, useState } from 'react';
import { fetchBackend } from '../lib/apiBase';
import '../styles/globals.css';
import FloatingSidebar from '../components/FloatingSidebar';

interface RuntimeInfo {
  environment: string;
  localDev: {
    enabled: boolean;
    developerUsername?: string | null;
  } | null;
}

export default function MyApp({ Component, pageProps }: AppProps) {
  const [wechatModalOpen, setWechatModalOpen] = useState(false);
  const [stableVersionModalOpen, setStableVersionModalOpen] = useState(false);
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);

  useEffect(() => {
    if (!('serviceWorker' in navigator)) {
      return;
    }
    const handleLoad = () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    };
    window.addEventListener('load', handleLoad);
    return () => window.removeEventListener('load', handleLoad);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const hostname = window.location.hostname.toLowerCase();
    if (hostname === 'study-hub.store' || hostname.endsWith('.study-hub.store')) {
      setStableVersionModalOpen(true);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const fetchRuntimeInfo = async () => {
      try {
        const resp = await fetchBackend('/healthz');
        const json = await resp.json();
        if (!active || !resp.ok || !json.ok || !json.data) {
          return;
        }
        setRuntimeInfo({
          environment: typeof json.data.environment === 'string' ? json.data.environment : '',
          localDev:
            json.data.localDev && typeof json.data.localDev === 'object'
              ? {
                  enabled: json.data.localDev.enabled === true,
                  developerUsername:
                    typeof json.data.localDev.developerUsername === 'string'
                      ? json.data.localDev.developerUsername
                      : null,
                }
              : null,
        });
      } catch {
        if (active) {
          setRuntimeInfo(null);
        }
      }
    };
    void fetchRuntimeInfo();
    return () => {
      active = false;
    };
  }, []);

  const showLocalDevBadge = runtimeInfo?.environment === 'local-dev' && runtimeInfo.localDev?.enabled;
  const localDevLabel = runtimeInfo?.localDev?.developerUsername
    ? `Local Dev · ${runtimeInfo.localDev.developerUsername}`
    : 'Local Dev';

  return (
    <>
      <Head>
        <title>StudyHub·学汇</title>
        <link rel="icon" href="/favicon.png" />
        <meta name="viewport" content="width=1100" />
        <link rel="manifest" href="/manifest.json" />
        <meta name="theme-color" content="#2563eb" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="StudyHub·学汇" />
        <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
      </Head>
      <div className="page-with-footer">
        <FloatingSidebar />
        {showLocalDevBadge && <div className="runtime-environment-badge">{localDevLabel}</div>}
        {stableVersionModalOpen && (
          <div className="modal-mask stable-version-mask" onClick={() => setStableVersionModalOpen(false)}>
            <div
              className="modal-card stable-version-modal"
              role="dialog"
              aria-modal="true"
              aria-label="StudyHub 稳定版提示"
              onClick={(event) => event.stopPropagation()}
            >
              <button
                className="modal-close stable-version-modal__close"
                type="button"
                aria-label="关闭"
                onClick={() => setStableVersionModalOpen(false)}
              >
                ×
              </button>
              <div className="stable-version-modal__media">
                <img
                  src="/local/stable-version-poster.png"
                  alt="StudyHub 稳定版海报"
                  loading="eager"
                  decoding="async"
                />
              </div>
              <div className="stable-version-modal__content">
                <span className="stable-version-modal__eyebrow">Stable Version 提示</span>
                <h2 className="stable-version-modal__title">建议使用正式稳定入口</h2>
                <p className="stable-version-modal__text">
                  你当前访问的是 StudyHub 的更新预览站 <strong>https://study-hub.store</strong>。新功能和界面调整通常会先在这里上线，因此在版本更新期间，个别页面或交互可能出现短暂波动。
                </p>
                <p className="stable-version-modal__text">
                  如果你更看重稳定体验，建议使用正式稳定入口{' '}
                  <a className="stable-version-modal__inline-link" href="https://study-hub.cn">
                    https://study-hub.cn
                  </a>
                  。两个网址的数据完全互通，你可以按自己的习惯自由切换。
                </p>
                <div className="stable-version-modal__actions">
                  <a className="button primary stable-version-modal__cta" href="https://study-hub.cn">
                    前往 Stable Version
                  </a>
                  <button
                    className="button secondary stable-version-modal__stay"
                    type="button"
                    onClick={() => setStableVersionModalOpen(false)}
                  >
                    留在当前版本
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
        <Component {...pageProps} />
        <footer className="global-footer">
          <div className="global-footer__wrap">
            <div className="footer-info">
              <div className="footer-info__row">
                <div className="footer-info__item">
                  <span className="footer-info__label">ICP备案号</span>
                  <a
                    className="footer-info__value"
                    href="https://beian.miit.gov.cn/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    浙ICP备2025212695号
                  </a>
                </div>
                <span className="footer-divider">|</span>
                <div className="footer-info__item">
                  <span className="footer-info__label">审核通过日期</span>
                  <span className="footer-info__value">2025-11-26</span>
                </div>
                <span className="footer-divider">|</span>
                <div className="footer-info__item">
                  <span className="footer-info__label">官方QQ群</span>
                  <span className="footer-info__value">245934740</span>
                </div>
              </div>
              <div className="footer-info__row">
                <div className="footer-info__item">
                  <span className="footer-info__label">联系邮箱</span>
                  <span className="footer-info__value">chengjinli@std.uestc.edu.cn</span>
                </div>
                <span className="footer-divider">|</span>
                <button
                  className="footer-action"
                  type="button"
                  onClick={() => setWechatModalOpen(true)}
                >
                  官方微信公众号
                </button>
                <span className="footer-divider">|</span>
                <div className="footer-info__item">
                  <span className="footer-info__label">核心贡献者</span>
                  <span className="footer-info__value">李承锦、曾逸帆</span>
                </div>
              </div>
            </div>
            <div className="footer-hairline" />
            <div className="footer-links">
              <a href="/join#engineering">工程日志</a>
              <span className="footer-divider">|</span>
              <a href="/join">关于我们</a>
              <span className="footer-divider">|</span>
              <a href="/identity-info">身份信息说明</a>
              <span className="footer-divider">|</span>
              <a href="/identity-info">用户协议 / 隐私政策</a>
              <span className="footer-divider">|</span>
              <span>内容版权归作者</span>
            </div>
          </div>
        </footer>
        {wechatModalOpen && (
          <div className="modal-mask" onClick={() => setWechatModalOpen(false)}>
            <div
              className="modal-card support-modal wechat-modal"
              role="dialog"
              aria-modal="true"
              aria-label="官方微信公众号"
              onClick={(event) => event.stopPropagation()}
            >
              <button
                className="modal-close"
                type="button"
                aria-label="关闭"
                onClick={() => setWechatModalOpen(false)}
              >
                ×
              </button>
              <div className="wechat-modal__title">官方微信公众号</div>
              <div className="wechat-modal__hint">扫码关注获取公告与更新</div>
              <div className="lazy-image-box qr-medium">
                <img
                  className="lazy-blur"
                  src="/wechat/wechat-qr.jpeg"
                  alt="StudyHub 官方微信公众号二维码"
                  loading="lazy"
                  decoding="async"
                  onLoad={(event) => event.currentTarget.classList.add('is-loaded')}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
