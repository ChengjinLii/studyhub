import type { AppProps } from 'next/app';
import dynamic from 'next/dynamic';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { ReactNode, useEffect, useRef, useState } from 'react';
import { fetchBackend } from '../lib/apiBase';
import { copyToClipboard } from '../lib/share';
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
import FooterAgentLogo from '../components/FooterAgentLogo';
import OpeningSplash from '../components/OpeningSplash';
import footerStyles from '../styles/SiteFooter.module.css';
import { brandFont, wordmarkFont } from '../lib/brandFont';
import { AppDialogProvider } from '../components/AppDialogProvider';
import { AppToastProvider } from '../components/AppToastProvider';
import { SessionProvider } from '../components/SessionProvider';
import { MotionProvider } from '../lib/motion';
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
    <MotionProvider>
      <SessionProvider initialUser={initialUser}>
        <AppToastProvider>
          <AppDialogProvider>
            <MobileBottomBarProvider>{children}</MobileBottomBarProvider>
          </AppDialogProvider>
        </AppToastProvider>
      </SessionProvider>
    </MotionProvider>
  );
}

export default function MyApp({ Component, pageProps }: AppProps) {
  const router = useRouter();
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [globalChromeReady, setGlobalChromeReady] = useState(false);
  const [wechatModalOpen, setWechatModalOpen] = useState(false);
  const [qqCopied, setQqCopied] = useState(false);
  const qqCopyTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (qqCopyTimerRef.current !== null) {
        window.clearTimeout(qqCopyTimerRef.current);
      }
    };
  }, []);

  const handleCopyFooterQQ = () => {
    void copyToClipboard('245934740');
    setQqCopied(true);
    if (qqCopyTimerRef.current !== null) {
      window.clearTimeout(qqCopyTimerRef.current);
    }
    qqCopyTimerRef.current = window.setTimeout(() => {
      setQqCopied(false);
      qqCopyTimerRef.current = null;
    }, 2000);
  };

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
      <div
        className={`page-with-footer ${brandFont.variable} ${wordmarkFont.variable}`}
        data-home-route={router.pathname === '/' ? 'true' : undefined}
      >
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
                  <h3 className={footerStyles.colHeading}>特别鸣谢</h3>
                  <ul className={footerStyles.colList}>
                    <li>
                      <span className={footerStyles.colItem}>季文君</span>
                    </li>
                    <li>
                      <span className={footerStyles.colItem}>林俊宇</span>
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

                <div className={footerStyles.linkCol}>
                  <h3 className={footerStyles.colHeading}>硅基工友</h3>
                  <ul className={footerStyles.colList}>
                    <li>
                      <span className={`${footerStyles.colItem} ${footerStyles.agentItem}`}>
                        <FooterAgentLogo kind="claude" className={footerStyles.agentLogo} />
                        <span>Claude Code</span>
                      </span>
                    </li>
                    <li>
                      <span className={`${footerStyles.colItem} ${footerStyles.agentItem}`}>
                        <FooterAgentLogo kind="codex" className={footerStyles.agentLogo} />
                        <span>Codex</span>
                      </span>
                    </li>
                    <li>
                      <span className={`${footerStyles.colItem} ${footerStyles.agentItem}`}>
                        <FooterAgentLogo kind="antigravity" className={footerStyles.agentLogo} />
                        <span>Antigravity</span>
                      </span>
                    </li>
                  </ul>
                </div>

                <div className={`${footerStyles.linkCol} ${footerStyles.contactCol}`}>
                  <h3 className={footerStyles.colHeading}>联系方式</h3>
                  <div className={footerStyles.socialRow} role="group" aria-label="联系方式图标">
                    <button
                      className={`${footerStyles.socialBtn}${qqCopied ? ` ${footerStyles.socialBtnActive}` : ''}`}
                      type="button"
                      onClick={handleCopyFooterQQ}
                      aria-label="复制官方QQ群号 245934740"
                      data-tooltip={qqCopied ? '已复制 QQ 群：245934740' : '官方 QQ 群：245934740（点击复制）'}
                    >
                      <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M12 2.2c-3.65 0-6.15 2.55-6.15 6.05 0 .78.12 1.48.27 2.02-1.52 1.78-2.32 3.74-2.32 5.26 0 1.1.54 1.66 1.24 1.66.44 0 .93-.28 1.42-.91.38.94 1.07 1.74 1.96 2.33-.95.29-1.58.75-1.58 1.29 0 .82 1.38 1.38 3.24 1.38 1.08 0 1.6-.22 1.92-.52.32.3.84.52 1.92.52 1.86 0 3.24-.56 3.24-1.38 0-.54-.63-1-1.58-1.29.89-.59 1.58-1.39 1.96-2.33.49.63.98.91 1.42.91.7 0 1.24-.56 1.24-1.66 0-1.52-.8-3.48-2.32-5.26.15-.54.27-1.24.27-2.02C18.15 4.75 15.65 2.2 12 2.2Z" />
                      </svg>
                    </button>
                    <button
                      className={footerStyles.socialBtn}
                      type="button"
                      onClick={() => setWechatModalOpen(true)}
                      aria-label="官方微信公众号"
                      data-tooltip="微信公众号 · 扫码关注"
                    >
                      <svg
                        width="17"
                        height="17"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        fillRule="evenodd"
                        clipRule="evenodd"
                        aria-hidden="true"
                      >
                        <path d="M9.2 3.8C5.1 3.8 1.8 6.5 1.8 9.9c0 1.9 1.05 3.6 2.7 4.7l-.65 2.05 2.35-1.15c.88.24 1.82.37 2.8.37.24 0 .47-.01.7-.03a5.8 5.8 0 0 1-.25-1.64c0-3.35 3.15-6.05 7.05-6.05.24 0 .48.01.71.03C16.55 5.65 13.2 3.8 9.2 3.8ZM6.9 7.9a.85.85 0 1 1 0 1.7.85.85 0 0 1 0-1.7Zm4.6 0a.85.85 0 1 1 0 1.7.85.85 0 0 1 0-1.7Z" />
                        <path d="M16.2 9.5c-3.35 0-6.05 2.25-6.05 5.05s2.7 5.05 6.05 5.05c.72 0 1.41-.11 2.05-.3l1.9.95-.5-1.65c1.5-.95 2.4-2.42 2.4-4.05 0-2.8-2.7-5.05-5.85-5.05Zm-2 3.25a.75.75 0 1 1 0 1.5.75.75 0 0 1 0-1.5Zm4 0a.75.75 0 1 1 0 1.5.75.75 0 0 1 0-1.5Z" />
                      </svg>
                    </button>
                    <a
                      className={footerStyles.socialBtn}
                      href="mailto:chengjinli@std.uestc.edu.cn"
                      aria-label="联系邮箱 chengjinli@std.uestc.edu.cn"
                      data-tooltip="邮箱 · chengjinli@std.uestc.edu.cn"
                    >
                      <svg
                        width="17"
                        height="17"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.9"
                        aria-hidden="true"
                      >
                        <rect x="3" y="5" width="18" height="14" rx="2.5" />
                        <path
                          d="m3.6 7 7.6 5.2a1.4 1.4 0 0 0 1.6 0L20.4 7"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </a>
                  </div>
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
                  src="/wechat/wechat-qr.png"
                  alt="StudyHub 官方微信公众号二维码"
                  width={180}
                  height={180}
                  decoding="async"
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
