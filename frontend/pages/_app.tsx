import type { AppProps } from 'next/app';
import dynamic from 'next/dynamic';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { FormEvent, ReactNode, useEffect, useState } from 'react';
import { fetchBackend } from '../lib/apiBase';
import '../styles/globals.css';
import '../styles/responsive.css';
import AppImage from '../components/AppImage';
import BrandLogo from '../components/BrandLogo';
import OpeningSplash from '../components/OpeningSplash';
import footerStyles from '../styles/SiteFooter.module.css';
import { brandFont, wordmarkFont } from '../lib/brandFont';
import { AppDialogProvider } from '../components/AppDialogProvider';
import { AppToastProvider } from '../components/AppToastProvider';
import { SessionProvider } from '../components/SessionProvider';
import BottomTabBar from '../components/mobile/BottomTabBar';
import PwaInstall from '../components/pwa/PwaInstall';
import { MobileBottomBarProvider } from '../components/mobile/MobileBottomBarProvider';
import { SessionUser } from '../types/user';

const FloatingSidebar = dynamic(() => import('../components/FloatingSidebar'), { ssr: false });

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

function GlobalInteractiveChrome({ ready }: { ready: boolean }) {
  if (!ready) return null;
  return <FloatingSidebar />;
}

function AppProviders({
  children,
  initialUser,
}: {
  children: ReactNode;
  initialUser?: SessionUser | null;
}) {
  return (
    <SessionProvider initialUser={initialUser}>
      <AppToastProvider>
        <AppDialogProvider>
          <MobileBottomBarProvider>{children}</MobileBottomBarProvider>
        </AppDialogProvider>
      </AppToastProvider>
    </SessionProvider>
  );
}

export default function MyApp({ Component, pageProps }: AppProps) {
  const router = useRouter();
  const [wechatModalOpen, setWechatModalOpen] = useState(false);
  const [footerSearch, setFooterSearch] = useState('');
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [globalChromeReady, setGlobalChromeReady] = useState(false);

  const handleFooterSearchSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const keyword = footerSearch.trim();
    void router.push(keyword ? `/materials?keyword=${encodeURIComponent(keyword)}` : '/materials');
  };

  useEffect(() => {
    if (!window.isSecureContext || !('serviceWorker' in navigator) || process.env.NODE_ENV !== 'production') {
      return;
    }
    const handleLoad = () => {
      void navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' }).catch(() => {});
    };
    if (document.readyState === 'complete') handleLoad();
    else window.addEventListener('load', handleLoad, { once: true });
    return () => window.removeEventListener('load', handleLoad);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    return scheduleAfterFirstPaint(() => setGlobalChromeReady(true));
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
    const cancelScheduledFetch = scheduleAfterFirstPaint(() => {
      void fetchRuntimeInfo();
    });
    return () => {
      active = false;
      cancelScheduledFetch();
    };
  }, []);

  const showLocalDevBadge = runtimeInfo?.environment === 'local-dev' && runtimeInfo.localDev?.enabled;
  const localDevLabel = runtimeInfo?.localDev?.developerUsername
    ? `Local Dev · ${runtimeInfo.localDev.developerUsername}`
    : 'Local Dev';
  const initialSessionUser = Object.prototype.hasOwnProperty.call(pageProps, 'user')
    ? ((pageProps as { user?: SessionUser | null }).user ?? null)
    : undefined;

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
        <link rel="apple-touch-icon" href="/icons/bot-apple-touch-icon-v3.png" />
      </Head>
      <AppProviders initialUser={initialSessionUser}>
      <div className={`page-with-footer ${brandFont.variable} ${wordmarkFont.variable}`}>
        <OpeningSplash />
        <GlobalInteractiveChrome ready={globalChromeReady} />
        {showLocalDevBadge && <div className="runtime-environment-badge">{localDevLabel}</div>}
        <Component {...pageProps} />
        <footer className={footerStyles.footer} data-site-footer="">
          <div className={footerStyles.wrap}>
            <div className={footerStyles.topGrid}>
              <div className={footerStyles.brandCol}>
                <div className={footerStyles.brandRow}>
                  <BrandLogo theme="dark" size={30} />
                  <span className={footerStyles.brandEn}>StudyHub</span>
                </div>
                <p className={footerStyles.brandDesc}>
                  校园学习资料共享与互助平台，让每一份真题、笔记与经验沉淀为可复用的学习资源。
                </p>
                <form
                  className={footerStyles.searchForm}
                  onSubmit={handleFooterSearchSubmit}
                  role="search"
                  aria-label="快速搜课"
                >
                  <div className={footerStyles.searchBox}>
                    <input
                      className={footerStyles.searchInput}
                      type="text"
                      value={footerSearch}
                      onChange={(event) => setFooterSearch(event.target.value)}
                      placeholder="想找哪门课的资料？"
                      aria-label="输入课程名搜索资料"
                    />
                    <button className={footerStyles.searchBtn} type="submit" aria-label="搜索课程资料">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
                        <path d="M5 12h14" strokeLinecap="round" />
                        <path d="m12 5 7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </button>
                  </div>
                </form>
              </div>

              <div className={footerStyles.linkCol}>
                <h3 className={footerStyles.colHeading}>联系与社区</h3>
                <ul className={footerStyles.colList}>
                  <li>
                    <button
                      className={footerStyles.colLink}
                      type="button"
                      onClick={() => setWechatModalOpen(true)}
                    >
                      官方微信公众号
                    </button>
                  </li>
                  <li>
                    <span className={footerStyles.colText}>官方QQ群：245934740</span>
                  </li>
                  <li>
                    <a className={footerStyles.colLink} href="mailto:chengjinli@std.uestc.edu.cn">
                      联系邮箱：chengjinli@std.uestc.edu.cn
                    </a>
                  </li>
                  <li>
                    <a
                      className={footerStyles.colLink}
                      href="https://github.com/ChengjinLii/studyhub"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      代码仓库：ChengjinLii/studyhub
                    </a>
                  </li>
                </ul>
              </div>

              <div className={footerStyles.linkCol}>
                <h3 className={footerStyles.colHeading}>关于与说明</h3>
                <ul className={footerStyles.colList}>
                  <li>
                    <Link className={footerStyles.colLink} href="/join" prefetch={false}>
                      关于我们
                    </Link>
                  </li>
                  <li>
                    <Link className={footerStyles.colLink} href="/join#engineering" prefetch={false}>
                      工程日志
                    </Link>
                  </li>
                  <li>
                    <Link className={footerStyles.colLink} href="/identity-info" prefetch={false}>
                      用户协议 / 隐私政策
                    </Link>
                  </li>
                  <li>
                    <span className={footerStyles.colText}>核心贡献者：李承锦、曾逸帆</span>
                  </li>
                </ul>
              </div>
            </div>

            <div className={footerStyles.bottomBar}>
              <span>© 2026 StudyHub 学汇 · 内容版权归作者</span>
              <span className={footerStyles.icpGroup}>
                <a
                  href="https://beian.miit.gov.cn/"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  浙ICP备2025212695号
                </a>
                <span>·</span>
                <span>审核通过日期 2025-11-26</span>
              </span>
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
        <PwaInstall />
      </div>
      </AppProviders>
    </>
  );
}
