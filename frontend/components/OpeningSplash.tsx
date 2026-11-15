import { useRouter } from 'next/router';
import { CSSProperties, useCallback, useEffect, useRef, useState } from 'react';
import {
  PORTAL_CANOPY_CENTER_Y,
  PORTAL_CANOPY_FILL_PATH,
  PORTAL_CANOPY_LEFT_Y,
  PORTAL_CANOPY_RIGHT_Y,
  PORTAL_CANOPY_RIM_PATH,
  PORTAL_CANOPY_VIEWBOX_HEIGHT,
  PORTAL_CANOPY_VIEWBOX_WIDTH,
} from '../lib/portalCanopy';
import { STUDYHUB_WORDMARK_GLYPHS, STUDYHUB_WORDMARK_VIEWBOX } from '../lib/studyhubWordmark';
import styles from '../styles/OpeningSplash.module.css';

export const REPLAY_SPLASH_EVENT = 'studyhub:replay-splash';

// Staggered vector trace -> liquid energy-crest bottom-up fill -> specular glint within 1.78s.
const TRACE_BASE_DELAY_MS = 60;
const TRACE_STEP_MS = 54;
const FILL_BASE_DELAY_MS = 480;
const FILL_STEP_MS = 54;

// The last glyph finishes filling around 1318ms and the specular glint completes by 1680ms; dock after
// a brief poise so the whole splash remains ~2.55s (1780 + 720 + 50), matching the classic budget.
const DOCK_DELAY_MS = 1780;
// A click, or a late start of the script, still leaves this much time before the dock.
const MIN_DOCK_DELAY_MS = 120;
// The lockup travels to its place on the page in this time, and the surface opens in the same time.
const DOCK_TRAVEL_MS = 720;
// The splash leaves one beat after the lockup has landed.
const DOCK_SETTLE_MS = 50;
// Where the lockup does not land on the page, the white surface fades out in this time.
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
  canopyVars?: Record<string, string>;
}

const REST_DOCK: SplashDock = { transform: REST_TRANSFORM, onHero: false };

const blockScroll = (event: Event) => event.preventDefault();

/** Time since the browser first painted the page: the splash of the server markup runs from then. */
const timeSinceFirstPaint = () => {
  const paint = performance.getEntriesByName('first-contentful-paint')[0];
  return paint ? Math.max(0, performance.now() - paint.startTime) : 0;
};

const measureCanopyVars = (): Record<string, string> | undefined => {
  const heroRect = document.querySelector<HTMLElement>('[data-splash-target]')?.getBoundingClientRect();
  const waveRect = document.querySelector<SVGElement>('[data-portal-canopy-wave]')?.getBoundingClientRect();
  if (!heroRect && !waveRect) return undefined;
  const waveLeft = waveRect ? waveRect.left : 0;
  const waveTop = waveRect
    ? waveRect.top
    : heroRect
      ? heroRect.bottom - (PORTAL_CANOPY_VIEWBOX_HEIGHT - 156)
      : -200;
  const waveWidth = waveRect && waveRect.width > 0 ? waveRect.width : window.innerWidth;
  const curveCenterY = waveTop + PORTAL_CANOPY_CENTER_Y;
  const taijiStartY = curveCenterY - window.innerHeight / 2;
  return {
    '--canopy-left': `${waveLeft.toFixed(2)}px`,
    '--canopy-top': `${waveTop.toFixed(2)}px`,
    '--canopy-width': `${waveWidth.toFixed(2)}px`,
    '--canopy-left-end-y': `${(waveTop + PORTAL_CANOPY_LEFT_Y).toFixed(2)}px`,
    '--canopy-right-end-y': `${(waveTop + PORTAL_CANOPY_RIGHT_Y).toFixed(2)}px`,
    '--taiji-start-y': `${taijiStartY.toFixed(2)}px`,
  };
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
    onCompleteRef.current?.();
  }, [clearTimers]);

  const computeDock = useCallback((): SplashDock => {
    const stageEl = stageRef.current;
    if (!stageEl) return { transform: FALLBACK_DOCK_TRANSFORM, onHero: false };
    const stageRect = stageEl.getBoundingClientRect();
    if (!stageRect.width) return { transform: FALLBACK_DOCK_TRANSFORM, onHero: false };

    // On the home page the lockup lands on the lockup over the search box. The two share exact
    // dimensions, so the splash lockup moves there at scale 1 and hands off seamlessly.
    const heroRect = document.querySelector<HTMLElement>('[data-splash-target]')?.getBoundingClientRect();
    if (
      heroRect &&
      heroRect.width > 0 &&
      heroRect.top >= NAVBAR_HEIGHT &&
      heroRect.bottom <= window.innerHeight
    ) {
      const dx = heroRect.left + heroRect.width / 2 - (stageRect.left + stageRect.width / 2);
      const dy = heroRect.top + heroRect.height / 2 - (stageRect.top + stageRect.height / 2);
      const canopyVars = measureCanopyVars();
      return { transform: `translate3d(${dx.toFixed(2)}px, ${dy.toFixed(2)}px, 0) scale(1)`, onHero: true, canopyVars };
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
    if (nextDock.canopyVars && overlayRef.current) {
      for (const [prop, val] of Object.entries(nextDock.canopyVars)) {
        overlayRef.current.style.setProperty(prop, val);
      }
      void overlayRef.current.offsetHeight;
    }
    document.documentElement.dataset.splashState = 'docking';
    setDock(nextDock);
    phaseRef.current = 'docking';
    setPhase('docking');
    if (nextDock.onHero) {
      timersRef.current = [window.setTimeout(finishSplash, DOCK_TRAVEL_MS + DOCK_SETTLE_MS)];
      return;
    }
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
        (fromServerMarkup && overlayEl && getComputedStyle(overlayEl).visibility === 'hidden')
      ) {
        finishSplash();
        return;
      }
      let dockDelay = DOCK_DELAY_MS;
      const initialCanopyVars = measureCanopyVars();
      if (fromServerMarkup) {
        dockDelay = Math.max(MIN_DOCK_DELAY_MS, DOCK_DELAY_MS - timeSinceFirstPaint());
        if (initialCanopyVars) {
          setDock({ transform: REST_TRANSFORM, onHero: false, canopyVars: initialCanopyVars });
        }
      } else {
        setDock({ transform: REST_TRANSFORM, onHero: false, canopyVars: initialCanopyVars });
        setPlayKey((prev) => prev + 1);
      }
      phaseRef.current = 'intro';
      setPhase('intro');
      document.documentElement.dataset.splashState = 'playing';
      timersRef.current = [window.setTimeout(beginDock, dockDelay)];
    },
    [beginDock, clearTimers, finishSplash],
  );

  // The page under the splash does not scroll while the splash plays.
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
    const forcedByQuery = params.get('splash') === 'dark' || params.get('splash') === 'light';
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
  const showTaijiWipe = loadsOnHome ? (!isDocking || dock.onHero) : dock.onHero;
  const overlayClass = [
    styles.overlay,
    isDocking ? styles.overlayDocking : '',
    isDocking && dock.onHero ? styles.overlayHeroDocking : '',
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
      style={dock.canopyVars as CSSProperties | undefined}
      role="presentation"
      aria-hidden="true"
      onClick={skipToDock}
    >
      {/* A dark screen with the vectorized StudyHub wordmark: horizon laser pulse, SVG path trace,
          bottom-up liquid energy crest fill, metallic glint, and swirling Yin-Yang canopy dock. */}
      <div className={styles.backdrop}>
        <div className={styles.gridGlow} />
      </div>
      <div className={styles.wipe}>
        {showTaijiWipe ? (
          <div className={styles.taijiRotor} data-splash-taiji="">
            <div className={styles.taijiYinSky} />
            <div className={styles.taijiYinLeftWing} />
            <div className={styles.taijiYinRightWing} />
            <svg
              className={styles.taijiWave}
              viewBox={`0 0 ${PORTAL_CANOPY_VIEWBOX_WIDTH} ${PORTAL_CANOPY_VIEWBOX_HEIGHT}`}
              preserveAspectRatio="none"
              focusable="false"
            >
              <defs>
                <clipPath id="splash-taiji-clip">
                  <path d={PORTAL_CANOPY_FILL_PATH} />
                </clipPath>
                <pattern id="splash-taiji-grid" width="44" height="44" patternUnits="userSpaceOnUse">
                  <path d="M 44 0 L 0 0 0 44" fill="none" stroke="rgba(255,255,255,0.022)" strokeWidth="1" />
                </pattern>
                <linearGradient id="splash-taiji-rim" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#60a5fa" stopOpacity="0" />
                  <stop offset="18%" stopColor="#60a5fa" stopOpacity="0.68" />
                  <stop offset="44%" stopColor="#818cf8" stopOpacity="0.88" />
                  <stop offset="64%" stopColor="#fcd34d" stopOpacity="0.66" />
                  <stop offset="82%" stopColor="#38bdf8" stopOpacity="0.74" />
                  <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
                </linearGradient>
                <radialGradient id="splash-aurora-left" cx="28%" cy="89%" r="26%">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.11" />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
                </radialGradient>
                <radialGradient id="splash-aurora-mid" cx="54%" cy="84%" r="24%">
                  <stop offset="0%" stopColor="#818cf8" stopOpacity="0.1" />
                  <stop offset="100%" stopColor="#818cf8" stopOpacity="0" />
                </radialGradient>
                <radialGradient id="splash-aurora-right" cx="76%" cy="87%" r="22%">
                  <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.08" />
                  <stop offset="65%" stopColor="#f59e0b" stopOpacity="0.03" />
                  <stop offset="100%" stopColor="#2dd4bf" stopOpacity="0" />
                </radialGradient>
              </defs>
              <g clipPath="url(#splash-taiji-clip)">
                <rect width={PORTAL_CANOPY_VIEWBOX_WIDTH} height={PORTAL_CANOPY_VIEWBOX_HEIGHT} fill="#1a1c20" />
                <rect
                  width={PORTAL_CANOPY_VIEWBOX_WIDTH}
                  height={PORTAL_CANOPY_VIEWBOX_HEIGHT}
                  fill="url(#splash-taiji-grid)"
                />
                <rect
                  width={PORTAL_CANOPY_VIEWBOX_WIDTH}
                  height={PORTAL_CANOPY_VIEWBOX_HEIGHT}
                  fill="url(#splash-aurora-left)"
                />
                <rect
                  width={PORTAL_CANOPY_VIEWBOX_WIDTH}
                  height={PORTAL_CANOPY_VIEWBOX_HEIGHT}
                  fill="url(#splash-aurora-mid)"
                />
                <rect
                  width={PORTAL_CANOPY_VIEWBOX_WIDTH}
                  height={PORTAL_CANOPY_VIEWBOX_HEIGHT}
                  fill="url(#splash-aurora-right)"
                />
              </g>
              <path
                className={styles.taijiRimGlow}
                d={PORTAL_CANOPY_RIM_PATH}
                fill="none"
                stroke="url(#splash-taiji-rim)"
                strokeWidth="5"
                vectorEffect="non-scaling-stroke"
              />
              <path
                d={PORTAL_CANOPY_RIM_PATH}
                fill="none"
                stroke="url(#splash-taiji-rim)"
                strokeWidth="1.6"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
          </div>
        ) : null}
      </div>
      <div
        ref={stageRef}
        className={`${styles.stage}${isDocking && !dock.onHero ? ` ${styles.stageLeaves}` : ''}`}
        style={isDocking ? { transform: dock.transform } : undefined}
      >
        <div className={styles.lockup}>
          <span className={styles.horizonBeam} aria-hidden="true" />
          <svg
            className={styles.wordmarkSvg}
            viewBox={STUDYHUB_WORDMARK_VIEWBOX}
            aria-hidden="true"
            focusable="false"
          >
            <defs>
              {STUDYHUB_WORDMARK_GLYPHS.map((glyph, index) => (
                <clipPath key={`clip-${glyph.id}`} id={`splash-glyph-clip-${index}`}>
                  <path d={glyph.d} />
                </clipPath>
              ))}
              <clipPath id="splash-wordmark-all-clip">
                {STUDYHUB_WORDMARK_GLYPHS.map((glyph) => (
                  <path key={`all-${glyph.id}`} d={glyph.d} />
                ))}
              </clipPath>
              <linearGradient id="splash-crest-grad" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stopColor="#c7d2fe" stopOpacity="0.95" />
                <stop offset="55%" stopColor="#ffffff" stopOpacity="0.98" />
                <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
              </linearGradient>
              <linearGradient id="splash-sheen-grad" x1="0%" y1="0%" x2="100%" y2="20%">
                <stop offset="0%" stopColor="#ffffff" stopOpacity="0" />
                <stop offset="42%" stopColor="#e0e7ff" stopOpacity="0.58" />
                <stop offset="54%" stopColor="#ffffff" stopOpacity="0.95" />
                <stop offset="68%" stopColor="#a5b4fc" stopOpacity="0.48" />
                <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
              </linearGradient>
            </defs>
            {STUDYHUB_WORDMARK_GLYPHS.map((glyph, index) => (
              <path
                key={`trace-${glyph.id}`}
                d={glyph.d}
                pathLength={1}
                className={`${styles.letterOutline}${glyph.tone === 'silver' ? ` ${styles.letterOutlineSilver}` : ''}`}
                style={{ animationDelay: `${TRACE_BASE_DELAY_MS + index * TRACE_STEP_MS}ms` }}
              />
            ))}
            {STUDYHUB_WORDMARK_GLYPHS.map((glyph, index) => (
              <g key={`fill-${glyph.id}`} clipPath={`url(#splash-glyph-clip-${index})`}>
                <g
                  className={styles.letterFill}
                  style={{ animationDelay: `${FILL_BASE_DELAY_MS + index * FILL_STEP_MS}ms` }}
                >
                  <rect
                    x={glyph.x - 4}
                    y={-8}
                    width={glyph.width + 8}
                    height={176}
                    className={glyph.tone === 'silver' ? styles.glyphFillSilver : styles.glyphFillWhite}
                  />
                  <rect
                    x={glyph.x - 4}
                    y={-8}
                    width={glyph.width + 8}
                    height={12}
                    fill="url(#splash-crest-grad)"
                    className={styles.letterCrest}
                  />
                </g>
              </g>
            ))}
            <g clipPath="url(#splash-wordmark-all-clip)">
              <rect
                x={-220}
                y={-30}
                width={190}
                height={220}
                fill="url(#splash-sheen-grad)"
                className={styles.wordmarkSheen}
              />
            </g>
          </svg>
        </div>
      </div>
      {showTaijiWipe ? (
        <div className={styles.stageCrispWrap} aria-hidden="true">
          <div
            className={styles.stageCrisp}
            style={isDocking ? { transform: dock.transform } : undefined}
          >
            <div className={styles.lockupCrisp}>
              <svg
                className={styles.wordmarkSvgCrisp}
                viewBox={STUDYHUB_WORDMARK_VIEWBOX}
                aria-hidden="true"
                focusable="false"
              >
                {STUDYHUB_WORDMARK_GLYPHS.map((glyph) => (
                  <path
                    key={`crisp-${glyph.id}`}
                    d={glyph.d}
                    className={glyph.tone === 'silver' ? styles.glyphCrispSilver : styles.glyphCrispWhite}
                  />
                ))}
              </svg>
            </div>
          </div>
        </div>
      ) : null}
      {showTaijiWipe ? (
        <svg className={styles.taijiCircleRim} viewBox="0 0 200 200" aria-hidden="true" focusable="false">
          <defs>
            <linearGradient id="splash-aperture-ring" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#93c5fd" stopOpacity="0.72" />
              <stop offset="50%" stopColor="#ffffff" stopOpacity="0.55" />
              <stop offset="100%" stopColor="#818cf8" stopOpacity="0.72" />
            </linearGradient>
          </defs>
          <circle
            cx="100"
            cy="100"
            r="99.5"
            fill="none"
            stroke="url(#splash-aperture-ring)"
            strokeWidth="1.6"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      ) : null}
    </div>
  );
}
