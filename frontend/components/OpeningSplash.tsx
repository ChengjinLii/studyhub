import { useRouter } from 'next/router';
import { useCallback, useEffect, useRef, useState } from 'react';
import BrandLogo from './BrandLogo';
import styles from '../styles/OpeningSplash.module.css';

export const REPLAY_SPLASH_EVENT = 'studyhub:replay-splash';

const TOP_CHEVRON_PATH = 'M434 278 L808 278 L678 400 L456 400 L322 502 L566 616 L238 540 L238 438 Z';
const BOTTOM_CHEVRON_PATH = 'M430 466 L786 558 L786 660 L620 796 L236 796 L368 676 L590 676 L700 596 Z';

const WORDMARK_LETTERS = 'StudyHub'.split('');
// Each letter comes in two steps. First its outline appears; then the letter fills from its
// foot to its top, and the outline goes.
const OUTLINE_BASE_DELAY_MS = 520;
const OUTLINE_STEP_MS = 40;
const FILL_BASE_DELAY_MS = 880;
const FILL_STEP_MS = 44;
// The outline of a letter goes when the letter is about half full.
const OUTLINE_OUT_AFTER_FILL_MS = 230;

// The last letter is full at about 1610ms (880 + 7 * 44 + 420); dock after a short hold. The
// whole splash takes about 2.55s (1780 + 720 + 50), the same as the splash before it.
const DOCK_DELAY_MS = 1780;
// A click, or a late start of the script, still leaves this much time before the dock.
const MIN_DOCK_DELAY_MS = 120;
// The lockup travels to its place on the page in this time, and the white surface opens over the
// black screen in the same time (--splash-travel in the stylesheet has the same value).
const DOCK_TRAVEL_MS = 720;
// The splash leaves one beat after the lockup has landed.
const DOCK_SETTLE_MS = 50;
// Where the lockup does not land on the page, the white surface fades out in this time. The fade
// ends when the other path ends, so the two paths take the same time.
const LEAVE_FADE_MS = 220;
const NAVBAR_HEIGHT = 64;
const REST_TRANSFORM = 'translate3d(0, 0, 0) scale(1)';
const FALLBACK_DOCK_TRANSFORM = 'translate3d(0, -18px, 0) scale(0.92)';

interface OpeningSplashProps {
  onComplete?: () => void;
}

type SplashPhase = 'hidden' | 'intro' | 'docking' | 'leaving';

interface SplashDock {
  transform: string;
  /** True when the lockup lands on the lockup of the home page, at the same size. */
  onHero: boolean;
}

const REST_DOCK: SplashDock = { transform: REST_TRANSFORM, onHero: false };

const blockScroll = (event: Event) => event.preventDefault();

/** Time since the browser first painted the page: the splash of the server markup runs from then. */
const timeSinceFirstPaint = () => {
  const paint = performance.getEntriesByName('first-contentful-paint')[0];
  return paint ? Math.max(0, performance.now() - paint.startTime) : 0;
};

export default function OpeningSplash({ onComplete }: OpeningSplashProps) {
  // The home page has the splash in its server markup, so the splash runs from the first paint
  // and the white page never shows before it. The script then only times the dock.
  const loadsOnHome = useRouter().pathname === '/';
  const [phase, setPhase] = useState<SplashPhase>(loadsOnHome ? 'intro' : 'hidden');
  const [playKey, setPlayKey] = useState(0);
  const [dock, setDock] = useState<SplashDock>(REST_DOCK);
  const phaseRef = useRef<SplashPhase>(loadsOnHome ? 'intro' : 'hidden');
  const overlayRef = useRef<HTMLDivElement>(null);
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
    document.documentElement.dataset.splashState = 'done';
    phaseRef.current = 'hidden';
    setPhase('hidden');
    setDock(REST_DOCK);
    onCompleteRef.current?.();
  }, [clearTimers]);

  const computeDock = useCallback((): SplashDock => {
    const stageEl = stageRef.current;
    if (!stageEl) return { transform: FALLBACK_DOCK_TRANSFORM, onHero: false };
    const stageRect = stageEl.getBoundingClientRect();
    if (!stageRect.width) return { transform: FALLBACK_DOCK_TRANSFORM, onHero: false };

    // On the home page the lockup lands on the lockup over the search box. The two have the same
    // box, so the splash lockup moves there at scale 1 and the page lockup takes its place with
    // no visible change. This needs the target in clear view under the navbar: it is not there
    // on a phone (the portal is hidden) or when the page loads at a scroll position.
    const heroRect = document.querySelector<HTMLElement>('[data-splash-target]')?.getBoundingClientRect();
    if (
      heroRect &&
      heroRect.width > 0 &&
      heroRect.top >= NAVBAR_HEIGHT &&
      heroRect.bottom <= window.innerHeight
    ) {
      const dx = heroRect.left + heroRect.width / 2 - (stageRect.left + stageRect.width / 2);
      const dy = heroRect.top + heroRect.height / 2 - (stageRect.top + stageRect.height / 2);
      return { transform: `translate3d(${dx.toFixed(2)}px, ${dy.toFixed(2)}px, 0) scale(1)`, onHero: true };
    }

    // Elsewhere the lockup shrinks towards the navbar brand and fades out.
    const brandRect = document.querySelector<HTMLElement>('[data-navbar-brand]')?.getBoundingClientRect();
    if (!brandRect || !brandRect.width) return { transform: FALLBACK_DOCK_TRANSFORM, onHero: false };
    const dx = brandRect.left + brandRect.width / 2 - (stageRect.left + stageRect.width / 2);
    const dy = brandRect.top + brandRect.height / 2 - (stageRect.top + stageRect.height / 2);
    const ratio = Math.min(0.68, Math.max(0.46, brandRect.height / stageRect.height));
    return {
      transform: `translate3d(${dx.toFixed(1)}px, ${dy.toFixed(1)}px, 0) scale(${ratio.toFixed(3)})`,
      onHero: false,
    };
  }, []);

  // The black screen opens to the white page while the lockup travels to its place.
  const beginDock = useCallback(() => {
    clearTimers();
    const nextDock = computeDock();
    document.documentElement.dataset.splashState = 'docking';
    setDock(nextDock);
    phaseRef.current = 'docking';
    setPhase('docking');
    if (nextDock.onHero) {
      // The lockup of the page takes the place of the splash lockup: no fade is necessary.
      timersRef.current = [window.setTimeout(finishSplash, DOCK_TRAVEL_MS + DOCK_SETTLE_MS)];
      return;
    }
    // The lockup has gone and the white surface covers the screen by now; it fades to show the
    // page.
    const leaveEnd = DOCK_TRAVEL_MS + DOCK_SETTLE_MS;
    timersRef.current = [
      window.setTimeout(() => {
        document.documentElement.dataset.splashState = 'done';
        phaseRef.current = 'leaving';
        setPhase('leaving');
      }, leaveEnd - LEAVE_FADE_MS),
      window.setTimeout(finishSplash, leaveEnd),
    ];
  }, [clearTimers, computeDock, finishSplash]);

  // A click does not cut the splash off: it starts the travel at once.
  const skipToDock = useCallback(() => {
    if (phaseRef.current === 'intro') beginDock();
  }, [beginDock]);

  const startPlayback = useCallback(
    (fromServerMarkup = false) => {
      clearTimers();
      const overlayEl = overlayRef.current;
      if (
        window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ||
        // The stylesheet removes a splash that no script came to end. Do not bring it back.
        (fromServerMarkup && overlayEl && getComputedStyle(overlayEl).visibility === 'hidden')
      ) {
        finishSplash();
        return;
      }
      let dockDelay = DOCK_DELAY_MS;
      if (fromServerMarkup) {
        // The animation of the server markup started at the first paint, before this script.
        dockDelay = Math.max(MIN_DOCK_DELAY_MS, DOCK_DELAY_MS - timeSinceFirstPaint());
      } else {
        setDock(REST_DOCK);
        setPlayKey((prev) => prev + 1);
      }
      phaseRef.current = 'intro';
      setPhase('intro');
      document.documentElement.dataset.splashState = 'playing';
      timersRef.current = [window.setTimeout(beginDock, dockDelay)];
    },
    [beginDock, clearTimers, finishSplash],
  );

  // The page under the splash does not scroll while the splash plays: the lockup lands on a
  // place that is measured on the page.
  const playing = phase !== 'hidden';
  useEffect(() => {
    if (!playing) return undefined;
    window.addEventListener('wheel', blockScroll, { passive: false });
    window.addEventListener('touchmove', blockScroll, { passive: false });
    return () => {
      window.removeEventListener('wheel', blockScroll);
      window.removeEventListener('touchmove', blockScroll);
    };
  }, [playing]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    // "?splash=dark" (or "light", kept for old links) plays the splash on any page.
    const forcedByQuery = params.get('splash') === 'dark' || params.get('splash') === 'light';
    // This effect runs once per full page load: the splash plays on each load or refresh of the
    // home page, and not on a client-side navigation to it from another page.
    const loadedOnHome = window.location.pathname === '/';

    if (phaseRef.current === 'intro') {
      startPlayback(true);
    } else if (forcedByQuery || loadedOnHome) {
      startPlayback();
    } else {
      document.documentElement.dataset.splashState = 'done';
      onCompleteRef.current?.();
    }

    const handleReplay = () => startPlayback();
    window.addEventListener(REPLAY_SPLASH_EVENT, handleReplay);
    return () => {
      window.removeEventListener(REPLAY_SPLASH_EVENT, handleReplay);
      clearTimers();
    };
  }, [clearTimers, startPlayback]);

  if (phase === 'hidden') return null;

  const isDocking = phase === 'docking' || phase === 'leaving';
  const overlayClass = [
    styles.overlay,
    isDocking ? styles.overlayDocking : '',
    phase === 'leaving' ? styles.overlayLeaving : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div
      key={playKey}
      ref={overlayRef}
      data-splash-overlay=""
      className={overlayClass}
      role="presentation"
      aria-hidden="true"
      onClick={skipToDock}
    >
      {/* A black screen with a white lockup. At the dock a white surface opens over the black
          from the centre; the lockup is blended by difference, so it turns from white to ink
          exactly where the white surface has passed. */}
      <div className={styles.backdrop}>
        <div className={styles.gridGlow} />
      </div>
      <div className={styles.wipe} />
      <div
        ref={stageRef}
        className={`${styles.stage}${isDocking && !dock.onHero ? ` ${styles.stageLeaves}` : ''}`}
        style={isDocking ? { transform: dock.transform } : undefined}
      >
        <div className={styles.lockup}>
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
            {/* The ink logo of the page, inverted to white by the stylesheet: one shape in both
                states. */}
            <BrandLogo
              theme="light"
              size={72}
              className={styles.logoImg}
              style={{ width: '100%', height: '100%' }}
            />
          </div>
          <div className={styles.wordmark}>
            {WORDMARK_LETTERS.map((letter, index) => (
              <span key={`${letter}-${index}`} className={styles.letter}>
                <span
                  className={styles.letterOutline}
                  style={{
                    // In, then out when the letter is nearly full.
                    animationDelay: `${OUTLINE_BASE_DELAY_MS + index * OUTLINE_STEP_MS}ms, ${
                      FILL_BASE_DELAY_MS + index * FILL_STEP_MS + OUTLINE_OUT_AFTER_FILL_MS
                    }ms`,
                  }}
                >
                  {letter}
                </span>
                <span
                  className={styles.letterFill}
                  style={{ animationDelay: `${FILL_BASE_DELAY_MS + index * FILL_STEP_MS}ms` }}
                >
                  {letter}
                </span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
