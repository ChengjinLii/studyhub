import type { AppProps } from 'next/app';
import dynamic from 'next/dynamic';
import Head from 'next/head';
import Link from 'next/link';
import { ReactNode, useEffect, useState } from 'react';
import { fetchBackend } from '../lib/apiBase';
import '../styles/globals.css';
import '../styles/responsive.css';
import AppImage from '../components/AppImage';
import {
  STUDYHUB_RIBBON_MARK_PATHS,
  STUDYHUB_RIBBON_MARK_VIEWBOX,
  STUDYHUB_WORDMARK_GLYPHS,
  STUDYHUB_WORDMARK_VIEWBOX,
  STUDYHUB_ZH_LOGOTYPE_PATHS,
  STUDYHUB_ZH_LOGOTYPE_VIEWBOX,
} from '../lib/studyhubWordmark';
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
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [globalChromeReady, setGlobalChromeReady] = useState(false);

  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') {
      if ('caches' in window) {
        void caches
          .open('studyhub-static-v4')
          .then((cache) =>
            cache.keys().then((requests) =>
              Promise.all(
                requests
                  .filter((request) => {
                    const { pathname } = new URL(request.url);
                    return (
                      /^\/_next\/static\/(development|webpack)\//.test(pathname) ||
                      (pathname.startsWith('/_next/static/chunks/') && !/[.-][0-9a-f]{8,}\.js$/i.test(pathname)) ||
                      (pathname.startsWith('/_next/static/css/') && !/[./-][0-9a-f]{8,}\.css$/i.test(pathname))
                    );
                  })
                  .map((request) => cache.delete(request))
              )
            )
          )
          .catch(() => {});
      }
      if ('serviceWorker' in navigator) {
        void navigator.serviceWorker
          .getRegistrations()
          .then((registrations) =>
            Promise.all(registrations.map((registration) => registration.update().catch(() => {})))
          )
          .catch(() => {});
      }
      return;
    }
    if (!window.isSecureContext || !('serviceWorker' in navigator)) {
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
        <link rel="icon" type="image/svg+xml" href="/favicon.svg?v=3" />
        <link rel="icon" type="image/png" sizes="180x180" href="/favicon.png?v=3" />
        <link rel="shortcut icon" href="/favicon.ico?v=3" />
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
                  <Link className={footerStyles.brandLink} href="/" prefetch={false} aria-label="学汇 StudyHub">
                    <svg
                      className={footerStyles.brandMarkSvg}
                      viewBox={STUDYHUB_RIBBON_MARK_VIEWBOX}
                      aria-hidden="true"
                      focusable="false"
                    >
                      {STUDYHUB_RIBBON_MARK_PATHS.map((d, index) => (
                        <path key={`footer-mark-${index}`} d={d} fill="#ffffff" />
                      ))}
                    </svg>
                    <svg
                      className={footerStyles.brandZhSvg}
                      viewBox={STUDYHUB_ZH_LOGOTYPE_VIEWBOX}
                      aria-hidden="true"
                      focusable="false"
                    >
                      {STUDYHUB_ZH_LOGOTYPE_PATHS.map((d, index) => (
                        <path key={`footer-zh-${index}`} d={d} fill="#ffffff" />
                      ))}
                    </svg>
                    <span className={footerStyles.srOnly}>学汇</span>
                    <span className={footerStyles.brandDivider} aria-hidden="true" />
                    <svg
                      className={footerStyles.brandWordmarkSvg}
                      viewBox={STUDYHUB_WORDMARK_VIEWBOX}
                      aria-hidden="true"
                      focusable="false"
                    >
                      {STUDYHUB_WORDMARK_GLYPHS.map((glyph) => (
                        <path
                          key={`footer-wordmark-${glyph.id}`}
                          d={glyph.d}
                          fill={glyph.tone === 'silver' ? '#b8b8ba' : '#ffffff'}
                        />
                      ))}
                    </svg>
                    <span className={footerStyles.srOnly}>StudyHub</span>
                  </Link>
                </div>
              </div>

              <div className={footerStyles.navGrid}>
                <div className={footerStyles.linkCol}>
                  <h3 className={footerStyles.colHeading}>核心贡献者</h3>
                  <ul className={footerStyles.colList}>
                    <li>
                      <span className={footerStyles.colItem}>李承锦</span>
                    </li>
                    <li>
                      <span className={footerStyles.colItem}>曾逸帆</span>
                    </li>
                  </ul>
                </div>

                <div className={footerStyles.linkCol}>
                  <h3 className={footerStyles.colHeading}>浏览</h3>
                  <ul className={footerStyles.colList}>
                    <li>
                      <Link className={footerStyles.colLink} href="/materials" prefetch={false}>
                        课程资料
                      </Link>
                    </li>
                    <li>
                      <Link className={footerStyles.colLink} href="/requests" prefetch={false}>
                        求资料区
                      </Link>
                    </li>
                    <li>
                      <Link className={footerStyles.colLink} href="/upload" prefetch={false}>
                        我要投稿
                      </Link>
                    </li>
                  </ul>
                </div>

                <div className={footerStyles.linkCol}>
                  <h3 className={footerStyles.colHeading}>社区</h3>
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
                      <a
                        className={footerStyles.colLink}
                        href="https://github.com/ChengjinLii/studyhub"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        开源仓库
                      </a>
                    </li>
                  </ul>
                </div>

                <div className={footerStyles.linkCol}>
                  <h3 className={footerStyles.colHeading}>支持</h3>
                  <ul className={footerStyles.colList}>
                    <li>
                      <Link className={footerStyles.colLink} href="/more" prefetch={false}>
                        更多服务
                      </Link>
                    </li>
                    <li>
                      <Link className={footerStyles.colLink} href="/identity-info" prefetch={false}>
                        隐私与协议
                      </Link>
                    </li>
                  </ul>
                </div>

                <div className={`${footerStyles.linkCol} ${footerStyles.contactCol}`}>
                  <h3 className={footerStyles.colHeading}>联系方式</h3>
                  <p className={footerStyles.contactItem}>
                    <span>联系邮箱：</span>
                    <a className={footerStyles.contactLink} href="mailto:chengjinli@std.uestc.edu.cn">
                      chengjinli@std.uestc.edu.cn
                    </a>
                  </p>
                  <div className={footerStyles.qrGroup}>
                    <div className={footerStyles.qrCard}>
                      <div className={footerStyles.qrBox}>
                        <AppImage
                          className={footerStyles.qrImg}
                          src="/wechat/qq-group-qr.webp"
                          alt="StudyHub 官方 QQ 群二维码"
                          width={88}
                          height={88}
                          loading="lazy"
                          decoding="async"
                        />
                      </div>
                      <span className={footerStyles.qrLabel}>官方 QQ 群</span>
                    </div>
                    <div className={footerStyles.qrCard}>
                      <div className={footerStyles.qrBox}>
                        <AppImage
                          className={footerStyles.qrImg}
                          src="/wechat/wechat-qr.png"
                          alt="StudyHub 公众号二维码"
                          width={88}
                          height={88}
                          loading="lazy"
                          decoding="async"
                        />
                      </div>
                      <span className={footerStyles.qrLabel}>StudyHub 公众号</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className={footerStyles.bottomBar}>
              <a
                className={footerStyles.icpLink}
                href="https://beian.miit.gov.cn/"
                target="_blank"
                rel="noopener noreferrer"
              >
                浙ICP备2025212695号
              </a>
              <span className={footerStyles.copyright}>Copyright © 2026 StudyHub开发团队</span>
            </div>
          </div>
        </footer>
        <BottomTabBar />
        <PwaInstall />
      </div>
      </AppProviders>
    </>
  );
}
