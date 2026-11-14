import { useCallback, useEffect, useRef, useState } from 'react';
import BrandLogo, { BrandLogoTheme } from './BrandLogo';
import styles from '../styles/OpeningSplash.module.css';

export const SPLASH_SEEN_STORAGE_KEY = 'studyhub:splash-seen';
export const REPLAY_SPLASH_EVENT = 'studyhub:replay-splash';

const TOP_CHEVRON_PATH = 'M434 278 L808 278 L678 400 L456 400 L322 502 L566 616 L238 540 L238 438 Z';
const BOTTOM_CHEVRON_PATH = 'M430 466 L786 558 L786 660 L620 796 L236 796 L368 676 L590 676 L700 596 Z';

const DOCK_DELAY_MS = 1480;
const FADE_DELAY_MS = 1660;
const COMPLETE_DELAY_MS = 2320;

interface OpeningSplashProps {
  onComplete?: () => void;
}

type SplashPhase = 'hidden' | 'intro' | 'docking' | 'fading';

function detectTheme(): BrandLogoTheme {
  if (typeof window === 'undefined') return 'light';
  const params = new URLSearchParams(window.location.search);
  const queryTheme = params.get('splash');
  if (queryTheme === 'dark' || queryTheme === 'light') {
    return queryTheme;
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export default function OpeningSplash({ onComplete }: OpeningSplashProps) {
  const [phase, setPhase] = useState<SplashPhase>('hidden');
  const [theme, setTheme] = useState<BrandLogoTheme>('light');
  const [playKey, setPlayKey] = useState(0);
  const [dockTransform, setDockTransform] = useState('translate3d(0, 0, 0) scale(1)');
  const stageRef = useRef<HTMLDivElement>(null);
  const timersRef = useRef<number[]>([]);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const clearTimers = useCallback(() => {
    timersRef.current.forEach((id) => window.clearTimeout(id));
    timersRef.current = [];
  }, []);

  const finishSplash = useCallback(() => {
    clearTimers();
    try {
      window.sessionStorage.setItem(SPLASH_SEEN_STORAGE_KEY, '1');
    } catch {
      // Ignore storage access failures in private/restricted browsers.
    }
    document.documentElement.dataset.splashState = 'done';
    setPhase('hidden');
    setDockTransform('translate3d(0, 0, 0) scale(1)');
    onCompleteRef.current?.();
  }, [clearTimers]);

  const computeDockTransform = useCallback(() => {
    const stageEl = stageRef.current;
    const targetEl = document.querySelector<HTMLElement>('[data-navbar-brand]');
    if (!stageEl || !targetEl) {
      return 'translate3d(0, -18px, 0) scale(0.92)';
    }
    const stageRect = stageEl.getBoundingClientRect();
    const targetRect = targetEl.getBoundingClientRect();
    if (!stageRect.width || !targetRect.width) {
      return 'translate3d(0, -18px, 0) scale(0.92)';
    }
    const stageCenterX = stageRect.left + stageRect.width / 2;
    const stageCenterY = stageRect.top + stageRect.height / 2;
    const targetCenterX = targetRect.left + targetRect.width / 2;
    const targetCenterY = targetRect.top + targetRect.height / 2;
    const dx = targetCenterX - stageCenterX;
    const dy = targetCenterY - stageCenterY;
    const ratio = Math.min(0.68, Math.max(0.46, targetRect.height / stageRect.height));
    return `translate3d(${dx.toFixed(1)}px, ${dy.toFixed(1)}px, 0) scale(${ratio.toFixed(3)})`;
  }, []);

  const startPlayback = useCallback(
    (forcedTheme?: BrandLogoTheme) => {
      clearTimers();
      if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
        finishSplash();
        return;
      }
      setTheme(forcedTheme ?? detectTheme());
      setDockTransform('translate3d(0, 0, 0) scale(1)');
      setPlayKey((prev) => prev + 1);
      setPhase('intro');
      document.documentElement.dataset.splashState = 'playing';

      const dockTimer = window.setTimeout(() => {
        document.documentElement.dataset.splashState = 'docking';
        setDockTransform(computeDockTransform());
        setPhase('docking');
      }, DOCK_DELAY_MS);

      const fadeTimer = window.setTimeout(() => {
        setPhase('fading');
      }, FADE_DELAY_MS);

      const doneTimer = window.setTimeout(() => {
        finishSplash();
      }, COMPLETE_DELAY_MS);

      timersRef.current = [dockTimer, fadeTimer, doneTimer];
    },
    [clearTimers, computeDockTransform, finishSplash]
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const forcedQueryTheme = params.get('splash');
    let seen = false;
    try {
      seen = window.sessionStorage.getItem(SPLASH_SEEN_STORAGE_KEY) === '1';
    } catch {
      seen = false;
    }

    if (forcedQueryTheme === 'light' || forcedQueryTheme === 'dark') {
      startPlayback(forcedQueryTheme);
    } else if (!seen) {
      startPlayback();
    } else {
      document.documentElement.dataset.splashState = 'done';
      onCompleteRef.current?.();
    }

    const handleReplay = (event: Event) => {
      const detail = (event as CustomEvent<{ theme?: BrandLogoTheme }>).detail;
      startPlayback(detail?.theme);
    };
    window.addEventListener(REPLAY_SPLASH_EVENT, handleReplay);
    return () => {
      window.removeEventListener(REPLAY_SPLASH_EVENT, handleReplay);
      clearTimers();
    };
  }, [clearTimers, startPlayback]);

  if (phase === 'hidden') return null;

  const isDark = theme === 'dark';
  const isFading = phase === 'fading';
  const isDocking = phase === 'docking' || isFading;
  const logoSize = typeof window !== 'undefined' && window.innerWidth <= 640 ? 54 : 68;

  return (
    <div
      key={playKey}
      data-splash-overlay=""
      className={[
        styles.overlay,
        isDark ? styles.overlayDark : styles.overlayLight,
        isDocking ? styles.overlayDocking : '',
        isFading ? styles.overlayFading : '',
      ]
        .filter(Boolean)
        .join(' ')}
      role="presentation"
      aria-hidden="true"
      onClick={finishSplash}
    >
      <div className={styles.gridGlow} />
      <div
        ref={stageRef}
        className={styles.stage}
        style={isDocking ? { transform: dockTransform, opacity: isFading ? 0.08 : 1 } : undefined}
      >
        <div className={styles.markWrap}>
          <svg
            className={styles.traceSvg}
            viewBox="0 0 1024 1024"
            aria-hidden="true"
            focusable="false"
          >
            <path className={styles.tracePath} pathLength={1} d={TOP_CHEVRON_PATH} />
            <path
              className={`${styles.tracePath} ${styles.tracePathBottom}`}
              pathLength={1}
              d={BOTTOM_CHEVRON_PATH}
            />
          </svg>
          <BrandLogo theme={theme} size={logoSize} className={styles.logoImg} />
        </div>
        <div className={styles.wordmark}>
          <span className={styles.titleEn}>StudyHub</span>
          <span className={styles.titleCn}>· 学汇</span>
        </div>
      </div>
    </div>
  );
}
