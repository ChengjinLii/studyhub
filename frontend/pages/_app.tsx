import type { AppProps } from 'next/app';
import dynamic from 'next/dynamic';
import Head from 'next/head';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { fetchBackend } from '../lib/apiBase';
import { hasRole } from '../lib/auth';
import { fetchOptionalSessionUser } from '../lib/sessionApi';
import '../styles/globals.css';
import AppImage from '../components/AppImage';
import { AppDialogProvider } from '../components/AppDialogProvider';
import BottomTabBar from '../components/mobile/BottomTabBar';
import { RoleMask, SessionUser } from '../types/user';

const FloatingSidebar = dynamic(() => import('../components/FloatingSidebar'), { ssr: false });
const HermesAgentWidget = dynamic(() => import('../components/HermesAgentWidget'), { ssr: false });
const Snowfall = dynamic(() => import('react-snowfall'), { ssr: false });

const PUBLIC_API_ORIGIN = process.env.NEXT_PUBLIC_API_ORIGIN || '';
const scheduleAfterFirstPaint = (task: () => void) => {
  if (typeof window === 'undefined') return () => {};
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let idleId: number | null = null;
  const requestIdle =
    typeof window.requestIdleCallback === 'function' ? window.requestIdleCallback.bind(window) : null;
  const cancelIdle =
    typeof window.cancelIdleCallback === 'function' ? window.cancelIdleCallback.bind(window) : null;
  const run = () => {
    if (requestIdle) {
      idleId = requestIdle(task, { timeout: 2500 });
      return;
    }
    timeoutId = setTimeout(task, 1200);
  };
  if (document.readyState === 'complete') {
    run();
  } else {
    window.addEventListener('load', run, { once: true });
  }
  return () => {
    window.removeEventListener('load', run);
    if (timeoutId !== null) clearTimeout(timeoutId);
    if (idleId !== null && cancelIdle) cancelIdle(idleId);
  };
};

interface RuntimeInfo {
  environment: string;
  localDev: {
    enabled: boolean;
    developerUsername?: string | null;
  } | null;
}

type EntryModalVariant = 'stable' | 'welcome' | null;

function StudyHubEntryPoster() {
  const snowfallCanvasStyle = {
    position: 'absolute' as const,
    inset: 0,
    width: '100%',
    height: '100%',
  };

  return (
    <div className="studyhub-popup-poster" aria-label="StudyHub 入口海报">
      <span className="studyhub-popup-poster__vignette" aria-hidden="true" />
      <div className="xmas-snowfall studyhub-popup-poster__snow" aria-hidden="true">
        <Snowfall
          snowflakeCount={14}
          color="rgba(243, 248, 255, 0.55)"
          radius={[0.6, 2.2]}
          speed={[0.6, 1.6]}
          wind={[-0.2, 1.2]}
          style={snowfallCanvasStyle}
        />
        <Snowfall
          snowflakeCount={7}
          color="rgba(255, 255, 255, 0.45)"
          radius={[1.6, 3.4]}
          speed={[1.2, 2.4]}
          wind={[-0.4, 1.6]}
          style={snowfallCanvasStyle}
        />
      </div>
      <div className="hero-meteors studyhub-popup-poster__meteors" aria-hidden="true">
        <span className="hero-meteor" style={{ top: '31%', left: '21%', animationDelay: '0.15s' }} />
        <span className="hero-meteor" style={{ top: '24%', left: '54%', animationDelay: '1.1s' }} />
        <span className="hero-meteor" style={{ top: '48%', left: '8%', animationDelay: '2.2s' }} />
      </div>
      <svg className="studyhub-popup-poster__svg" viewBox="0 0 2048 1152" role="img" aria-labelledby="studyhub-popup-poster-title" xmlns="http://www.w3.org/2000/svg">
        <title id="studyhub-popup-poster-title">StudyHub 学汇入口海报</title>
        <rect width="2048" height="1152" fill="#ffffff" />
        <polygon points="0,535 2048,137 2048,660 0,1056" fill="#000000" />
        <rect x="266" y="136" width="1445" height="144" rx="40" ry="40" fill="#4b494b" />
        <circle cx="347" cy="208" r="21" fill="#ff6a60" />
        <circle cx="423" cy="208" r="21" fill="#f5c64f" />
        <circle cx="498" cy="208" r="21" fill="#62cd68" />
        <text className="studyhub-popup-poster__url" x="1023" y="232" textAnchor="middle">https://study-hub.cn</text>
        <text className="studyhub-popup-poster__brand" x="1250" y="122">STUDYHUB ·</text>
        <text className="studyhub-popup-poster__brand-cn" x="1576" y="122">学汇</text>
        <g fill="none" stroke="#ffffff" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="1530" cy="264" r="63" strokeWidth="10" />
          <path d="M1501 238 C1520 223 1554 223 1578 243" strokeWidth="9" />
          <path d="M1576 310 L1618 352" strokeWidth="10" />
        </g>
        <rect x="509" y="477" width="224" height="7" fill="#78cbc8" />
        <rect x="750" y="477" width="388" height="7" fill="#252b33" />
        <circle cx="290" cy="651" r="112" fill="#020612" stroke="#f5f6f8" strokeWidth="9" />
        <rect x="272" y="613" width="26" height="76" rx="13" fill="#f7f7f8" />
        <rect x="336" y="613" width="26" height="76" rx="13" fill="#f7f7f8" />
        <text className="studyhub-popup-poster__title" x="503" y="734">StudyHub</text>
        <g stroke="#111111" strokeWidth="4" strokeLinecap="round" strokeDasharray="1 9" fill="#ffffff">
          <rect x="582" y="970" width="224" height="68" rx="3" />
          <rect x="835" y="970" width="224" height="68" rx="3" />
          <rect x="1090" y="970" width="224" height="68" rx="3" />
          <rect x="1345" y="970" width="224" height="68" rx="3" />
        </g>
        <text className="studyhub-popup-poster__chip" x="694" y="1016" textAnchor="middle">贡献资料</text>
        <text className="studyhub-popup-poster__chip" x="947" y="1016" textAnchor="middle">获取所需</text>
        <text className="studyhub-popup-poster__chip" x="1202" y="1016" textAnchor="middle">经验分享</text>
        <text className="studyhub-popup-poster__chip" x="1457" y="1016" textAnchor="middle">校园集市</text>
        <text className="studyhub-popup-poster__contact" x="310" y="1112">联系邮箱</text>
        <text className="studyhub-popup-poster__contact" x="515" y="1112">chengjinli@std.uestc.edu.cn</text>
        <text className="studyhub-popup-poster__contact" x="1098" y="1112">|</text>
        <text className="studyhub-popup-poster__contact" x="1148" y="1112">核心贡献者</text>
        <text className="studyhub-popup-poster__contact" x="1390" y="1112">李承锦、曾逸帆</text>
      </svg>
    </div>
  );
}

export default function MyApp({ Component, pageProps }: AppProps) {
  const [wechatModalOpen, setWechatModalOpen] = useState(false);
  const [entryModalVariant, setEntryModalVariant] = useState<EntryModalVariant>(null);
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [globalChromeReady, setGlobalChromeReady] = useState(false);
  const [agentUser, setAgentUser] = useState<SessionUser | null>(null);

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
    return scheduleAfterFirstPaint(() => setGlobalChromeReady(true));
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    if (window.location.pathname !== '/') {
      return;
    }
    const hostname = window.location.hostname.toLowerCase();
    if (hostname === 'study-hub.store' || hostname.endsWith('.study-hub.store')) {
      setEntryModalVariant('stable');
      return;
    }
    setEntryModalVariant('welcome');
  }, []);

  useEffect(() => {
    if (!entryModalVariant || typeof window === 'undefined') {
      return undefined;
    }
    const handleEntryModalKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setEntryModalVariant(null);
      }
    };
    window.addEventListener('keydown', handleEntryModalKeyDown);
    return () => window.removeEventListener('keydown', handleEntryModalKeyDown);
  }, [entryModalVariant]);

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
    const cancelScheduledFetch = scheduleAfterFirstPaint(() => {
      void fetchRuntimeInfo();
    });
    return () => {
      active = false;
      cancelScheduledFetch();
    };
  }, []);

  useEffect(() => {
    if (!globalChromeReady || typeof window === 'undefined') {
      return undefined;
    }
    let active = true;
    const loadAgentSession = async () => {
      const nextUser = await fetchOptionalSessionUser();
      if (active) {
        setAgentUser(nextUser);
      }
    };
    void loadAgentSession();
    window.addEventListener('focus', loadAgentSession);
    return () => {
      active = false;
      window.removeEventListener('focus', loadAgentSession);
    };
  }, [globalChromeReady]);

  const showLocalDevBadge = runtimeInfo?.environment === 'local-dev' && runtimeInfo.localDev?.enabled;
  const localDevLabel = runtimeInfo?.localDev?.developerUsername
    ? `Local Dev · ${runtimeInfo.localDev.developerUsername}`
    : 'Local Dev';
  const isStableEntryModal = entryModalVariant === 'stable';
  const canShowAiAgent =
    agentUser !== null &&
    (hasRole(agentUser.roleMask, RoleMask.ADMIN) || hasRole(agentUser.roleMask, RoleMask.DEVELOPER));

  return (
    <>
      <Head>
        <title>StudyHub·学汇</title>
        <link rel="icon" href="/favicon.png" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        {PUBLIC_API_ORIGIN ? (
          <>
            <link rel="preconnect" href={PUBLIC_API_ORIGIN} crossOrigin="anonymous" />
            <link rel="dns-prefetch" href={PUBLIC_API_ORIGIN} />
          </>
        ) : null}
        <link rel="manifest" href="/manifest.json" />
        <meta name="theme-color" content="#2563eb" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="StudyHub·学汇" />
        <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
      </Head>
      <AppDialogProvider>
      <div className="page-with-footer">
        {globalChromeReady && (
          <>
            <FloatingSidebar />
            {canShowAiAgent && <HermesAgentWidget />}
          </>
        )}
        {showLocalDevBadge && <div className="runtime-environment-badge">{localDevLabel}</div>}
        {entryModalVariant && (
          <div className="modal-mask stable-version-mask" onClick={() => setEntryModalVariant(null)}>
            <div
              className={`modal-card stable-version-modal ${
                isStableEntryModal ? 'stable-version-modal--stable' : 'stable-version-modal--welcome'
              }`}
              role="dialog"
              aria-modal="true"
              aria-label={isStableEntryModal ? 'StudyHub 稳定版提示' : '欢迎来到 StudyHub'}
              onClick={(event) => event.stopPropagation()}
            >
              <button
                className="modal-close stable-version-modal__close"
                type="button"
                aria-label="关闭"
                onClick={() => setEntryModalVariant(null)}
              >
                ×
              </button>
              <div className="stable-version-modal__media">
                <StudyHubEntryPoster />
              </div>
              <div className="stable-version-modal__content">
                <span className="stable-version-modal__eyebrow">
                  {isStableEntryModal ? 'Stable Version 提示' : 'Welcome to StudyHub'}
                </span>
                {isStableEntryModal ? (
                  <>
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
                  </>
                ) : (
                  <>
                    <div className="stable-version-modal__meta">
                      <div className="stable-version-modal__meta-row">
                        <span className="stable-version-modal__meta-label">官方QQ群：</span>
                        <strong className="stable-version-modal__meta-value">245934740</strong>
                      </div>
                      <div className="stable-version-modal__meta-row">
                        <span className="stable-version-modal__meta-label">代码仓库：</span>
                        <a
                          className="stable-version-modal__meta-link"
                          href="https://github.com/ChengjinLii/studyhub"
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          github.com/ChengjinLii/studyhub
                        </a>
                      </div>
                    </div>
                  </>
                )}
                <div className="stable-version-modal__actions">
                  {isStableEntryModal ? (
                    <a className="button primary stable-version-modal__cta" href="https://study-hub.cn">
                      前往 Stable Version
                    </a>
                  ) : (
                    <a
                      className="button primary stable-version-modal__cta"
                      href="https://github.com/ChengjinLii/studyhub"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      查看代码仓库
                    </a>
                  )}
                  <button
                    className="button secondary stable-version-modal__stay"
                    type="button"
                    onClick={() => setEntryModalVariant(null)}
                  >
                    {isStableEntryModal ? '留在当前版本' : '关闭窗口'}
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
                <button
                  className="footer-action"
                  type="button"
                  onClick={() => setWechatModalOpen(true)}
                >
                  官方微信公众号
                </button>
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
                <div className="footer-info__item">
                  <span className="footer-info__label">代码仓库</span>
                  <a
                    className="footer-info__value"
                    href="https://github.com/ChengjinLii/studyhub"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    github.com/ChengjinLii/studyhub
                  </a>
                </div>
                <span className="footer-divider">|</span>
                <div className="footer-info__item">
                  <span className="footer-info__label">核心贡献者</span>
                  <span className="footer-info__value">李承锦、曾逸帆</span>
                </div>
              </div>
            </div>
            <div className="footer-hairline" />
            <div className="footer-links">
              <Link href="/join#engineering" prefetch={false}>工程日志</Link>
              <span className="footer-divider">|</span>
              <Link href="/join" prefetch={false}>关于我们</Link>
              <span className="footer-divider">|</span>
              <Link href="/identity-info" prefetch={false}>身份信息说明</Link>
              <span className="footer-divider">|</span>
              <Link href="/identity-info" prefetch={false}>用户协议 / 隐私政策</Link>
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
                <AppImage
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
        <BottomTabBar />
      </div>
      </AppDialogProvider>
    </>
  );
}
