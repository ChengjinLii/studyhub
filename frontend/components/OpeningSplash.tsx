import { useRouter } from 'next/router';
import {
  CSSProperties,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import {
  CACTUS_VARIANTS,
  clamp,
  DINO_ROWS,
  drawCactusVector,
  drawDinoEye,
  drawSmoothSprite,
  getDinoViewportLayout,
  publishSplashDinoHandoff,
  SplashDinoHandoffPayload,
  SplashHandoffObstacle,
  SPRITE_DINO_JUMP,
  SPRITE_DINO_RUN_FRAMES,
} from '../lib/dinoSprites';
import { animate } from '../lib/motion';
import {
  PORTAL_CANOPY_CENTER_Y,
  PORTAL_CANOPY_VIEWBOX_HEIGHT,
} from '../lib/portalCanopy';
import { STUDYHUB_WORDMARK_GLYPHS, STUDYHUB_WORDMARK_VIEWBOX } from '../lib/studyhubWordmark';
import styles from '../styles/OpeningSplash.module.css';

export const REPLAY_SPLASH_EVENT = 'studyhub:replay-splash';

// Staggered vector trace -> liquid energy-crest bottom-up fill -> specular glint within 1.72s.
const TRACE_BASE_DELAY_MS = 60;
const TRACE_STEP_MS = 54;
const FILL_BASE_DELAY_MS = 480;
const FILL_STEP_MS = 54;

// Intro stays on dark stage through 1720ms; then the dark curtain glides up to the portal
// horizon while the large bottom-left dino shrinks onto the horizon seam (total <= 2.7s).
const DOCK_DELAY_MS = 1720;
const MIN_DOCK_DELAY_MS = 120;
const DOCK_TRAVEL_MS = 860;
const DOCK_SETTLE_MS = 40;
const LEAVE_FADE_MS = 220;
const NAVBAR_HEIGHT = 64;
const REST_TRANSFORM = 'translate3d(0, 0, 0) scale(1)';
const FALLBACK_DOCK_TRANSFORM = 'translate3d(0, -18px, 0) scale(0.92)';

const useIsomorphicLayoutEffect = typeof window !== 'undefined' ? useLayoutEffect : useEffect;

interface OpeningSplashProps {
  onComplete?: () => void;
}

type SplashPhase = 'hidden' | 'intro' | 'docking' | 'leaving';

interface SplashDock {
  transform: string;
  /** True when the lockup lands on the lockup of the home page, at the same size. */
  onHero: boolean;
  dx?: number;
  dy?: number;
  horizonY?: number;
}

const REST_DOCK: SplashDock = { transform: REST_TRANSFORM, onHero: false };

/** Monotonic Apple exponential ease-out for silky curtain & obstacle scale handoff without reversal wobble. */
const appleSpringEase = (tRaw: number): number => {
  const t = clamp(tRaw, 0, 1);
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return 1 - Math.pow(1 - t, 4.4);
};

/** Damped spring emergence for the bottom-left dino pop-in. */
const applePopUpEase = (tRaw: number): number => {
  const t = clamp(tRaw, 0, 1);
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return 1 - Math.exp(-7.2 * t) * Math.cos(8.5 * t);
};

const measureHorizonY = (heroRect?: DOMRect): number => {
  const waveRect = document.querySelector<SVGElement>('[data-portal-canopy-wave]')?.getBoundingClientRect();
  const waveHeight = waveRect && waveRect.height > 0 ? waveRect.height : PORTAL_CANOPY_VIEWBOX_HEIGHT;
  const waveScaleY = waveHeight / PORTAL_CANOPY_VIEWBOX_HEIGHT;
  const waveTop = waveRect
    ? waveRect.top
    : heroRect
      ? heroRect.bottom - (waveHeight - 200)
      : -200;
  return waveTop + PORTAL_CANOPY_CENTER_Y * waveScaleY;
};

interface SplashBootHandle {
  active: boolean;
  startPerf: number;
  stop: () => void;
}

const getSplashBoot = (): SplashBootHandle | undefined =>
  typeof window !== 'undefined'
    ? (window as Window & { __studyhubSplashBoot?: SplashBootHandle }).__studyhubSplashBoot
    : undefined;

/** Time since the browser first painted the page: the splash of the server markup runs from then. */
const timeSinceFirstPaint = () => {
  const paint = performance.getEntriesByName('first-contentful-paint')[0];
  return paint ? Math.max(0, performance.now() - paint.startTime) : 0;
};

const blockScroll = (event: Event) => event.preventDefault();

export default function OpeningSplash({ onComplete }: OpeningSplashProps) {
  // The home page has the splash in its server markup, so the splash runs from the first paint
  // and the white page never shows before it. The script then only times the dock.
  const loadsOnHome = useRouter().pathname === '/';
  const [phase, setPhase] = useState<SplashPhase>(loadsOnHome ? 'intro' : 'hidden');
  const [playKey, setPlayKey] = useState(0);
  const [dock, setDock] = useState<SplashDock>(REST_DOCK);
  const phaseRef = useRef<SplashPhase>(loadsOnHome ? 'intro' : 'hidden');
  const overlayRef = useRef<HTMLDivElement>(null);
  const curtainRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const dinoCanvasRef = useRef<HTMLCanvasElement>(null);
  const introStartPerfRef = useRef<number>(0);
  const dockStartPerfRef = useRef<number>(0);
  const dockRef = useRef<SplashDock>(REST_DOCK);
  dockRef.current = dock;
  const liveHandoffRef = useRef<SplashDinoHandoffPayload | null>(null);
  const timersRef = useRef<number[]>([]);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const clearTimers = useCallback(() => {
    timersRef.current.forEach((id) => window.clearTimeout(id));
    timersRef.current = [];
  }, []);

  const finishSplash = useCallback(() => {
    if (phaseRef.current === 'hidden') return;
    clearTimers();
    if (liveHandoffRef.current) {
      publishSplashDinoHandoff(liveHandoffRef.current);
      liveHandoffRef.current = null;
    }
    document.documentElement.dataset.splashState = 'done';
    phaseRef.current = 'hidden';
    setPhase('hidden');
    onCompleteRef.current?.();
  }, [clearTimers]);

  const finishSplashRef = useRef(finishSplash);
  finishSplashRef.current = finishSplash;

  const computeDock = useCallback((): SplashDock => {
    const stageEl = stageRef.current;
    if (!stageEl) return { transform: FALLBACK_DOCK_TRANSFORM, onHero: false };
    const stageRect = stageEl.getBoundingClientRect();
    if (!stageRect.width) return { transform: FALLBACK_DOCK_TRANSFORM, onHero: false };

    const startCx = stageRect.left + stageRect.width / 2;
    const startCy = stageRect.top + stageRect.height / 2;

    // On the home page the lockup lands on the lockup over the search box. The two share exact
    // dimensions, so the splash lockup moves there at scale 1 and hands off seamlessly.
    const minHeroTop = window.innerWidth <= 768 ? 44 : NAVBAR_HEIGHT;
    const heroRect = document.querySelector<HTMLElement>('[data-splash-target]')?.getBoundingClientRect();
    if (
      heroRect &&
      heroRect.width > 0 &&
      heroRect.top >= minHeroTop &&
      heroRect.bottom <= window.innerHeight
    ) {
      const targetCx = heroRect.left + heroRect.width / 2;
      const targetCy = heroRect.top + heroRect.height / 2;
      const dx = targetCx - startCx;
      const dy = targetCy - startCy;
      const horizonY = measureHorizonY(heroRect);
      return {
        transform: `translate3d(${dx.toFixed(2)}px, ${dy.toFixed(2)}px, 0) scale(1)`, onHero: true,
        dx,
        dy,
        horizonY,
      };
    }

    // Elsewhere the lockup shrinks towards the navbar brand and fades out.
    const brandRect = document.querySelector<HTMLElement>('[data-navbar-brand]')?.getBoundingClientRect();
    if (!brandRect || !brandRect.width) return { transform: FALLBACK_DOCK_TRANSFORM, onHero: false };
    const dx = brandRect.left + brandRect.width / 2 - startCx;
    const dy = brandRect.top + brandRect.height / 2 - startCy;
    const ratio = Math.min(0.68, Math.max(0.46, brandRect.height / stageRect.height));
    return {
      transform: `translate3d(${dx.toFixed(1)}px, ${dy.toFixed(1)}px, 0) scale(${ratio.toFixed(3)})`,
      onHero: false,
    };
  }, []);

  // The black curtain rises to the portal horizon while the lockup springs into place.
  const beginDock = useCallback(() => {
    clearTimers();
    const nextDock = computeDock();
    dockStartPerfRef.current = performance.now();
    document.documentElement.dataset.splashState = 'docking';
    dockRef.current = nextDock;
    setDock(nextDock);
    phaseRef.current = 'docking';
    setPhase('docking');
    if (nextDock.onHero) {
      timersRef.current = [window.setTimeout(finishSplash, DOCK_TRAVEL_MS + DOCK_SETTLE_MS + 80)];
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
      const boot = fromServerMarkup ? getSplashBoot() : undefined;
      const fcpElapsed = fromServerMarkup ? timeSinceFirstPaint() : 0;
      const hasPreBoot = Boolean(boot && boot.startPerf > 0);
      const bootElapsed = hasPreBoot ? Math.max(fcpElapsed, performance.now() - boot!.startPerf) : fcpElapsed;
      introStartPerfRef.current = hasPreBoot ? boot!.startPerf : performance.now();
      const dockDelay = !fromServerMarkup
        ? DOCK_DELAY_MS
        : hasPreBoot
          ? Math.max(MIN_DOCK_DELAY_MS, DOCK_DELAY_MS - bootElapsed)
          : Math.max(900, DOCK_DELAY_MS - Math.min(fcpElapsed, 820));
      if (!fromServerMarkup) {
        setDock(REST_DOCK);
        setPlayKey((prev) => prev + 1);
      }
      phaseRef.current = 'intro';
      setPhase('intro');
      document.documentElement.dataset.splashState = 'playing';
      timersRef.current = [window.setTimeout(beginDock, dockDelay)];
    },
    [beginDock, clearTimers, finishSplash]
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

  // Spring-cushioned StudyHub wordmark travel onto hero target when docking.
  useIsomorphicLayoutEffect(() => {
    const stageEl = stageRef.current;
    if (!stageEl || phase !== 'docking' || !dock.onHero) return undefined;
    const targetX = dock.dx ?? 0;
    const targetY = dock.dy ?? 0;
    const ctrl = animate(
      stageEl,
      { x: [0, targetX], y: [0, targetY] },
      {
        type: 'spring',
        stiffness: 185,
        damping: 22,
        mass: 0.92,
      }
    );
    return () => ctrl.stop();
  }, [phase, dock.onHero, dock.dx, dock.dy]);

  // Unified 60fps driver for the bottom-left large dino + rising dark curtain edge:
  // Keeps the dinosaur physically planted on top of the rising black edge at every frame,
  // stays active across intro -> docking without restarting rAF, and hands off synchronously on rAF.
  const splashActive = phase !== 'hidden' && phase !== 'leaving';
  useIsomorphicLayoutEffect(() => {
    if (!splashActive) return undefined;

    const canvas = dinoCanvasRef.current;
    const curtainEl = curtainRef.current;
    if (!canvas) return undefined;
    const boot = getSplashBoot();
    if (boot) {
      if (!introStartPerfRef.current && boot.startPerf > 0) {
        introStartPerfRef.current = boot.startPerf;
      }
      boot.stop();
    }
    let ctx: CanvasRenderingContext2D | null = null;
    try {
      ctx = canvas.getContext('2d');
    } catch {
      ctx = null;
    }
    if (!ctx) return undefined;
    const context = ctx;

    let vw = Math.max(320, window.innerWidth);
    let vh = Math.max(320, window.innerHeight);
    let canvasLeft = 0;
    let canvasTop = 0;
    let canvasW = vw;
    let canvasH = vh;
    let startPx = 5.4;
    let startX = 96;
    let splashTrackSpeed = 118;
    let targetX = 120;
    let targetPx = 2.08;
    let targetHorizonY = vh * 0.4;

    const syncMetrics = () => {
      vw = Math.max(320, window.innerWidth);
      vh = Math.max(320, window.innerHeight);
      const canvasRect = canvas.getBoundingClientRect();
      canvasLeft = canvasRect.left;
      canvasTop = canvasRect.top;
      canvasW = Math.max(320, canvasRect.width || vw);
      canvasH = Math.max(320, canvasRect.height || vh);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const targetW = Math.round(canvasW * dpr);
      const targetH = Math.round(canvasH * dpr);
      if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
      }
      context.setTransform(dpr, 0, 0, dpr, 0, 0);

      startPx = vw <= 768 ? 3.9 : clamp(vw * 0.0044, 5.4, 6.8);
      startX = vw <= 768 ? Math.max(36, Math.round(canvasW * 0.1)) : Math.max(84, Math.round(canvasW * 0.12));
      splashTrackSpeed = vw <= 768 ? 68 : 118;

      const horizonEl = document.querySelector<HTMLElement>('[data-portal-dino-horizon]');
      const horizonRect = horizonEl?.getBoundingClientRect();
      const horizonLeftInCanvas =
        horizonRect && horizonRect.width > 0 ? horizonRect.left - canvasLeft : 0;
      const horizonWidth = horizonRect && horizonRect.width > 0 ? horizonRect.width : canvasW;
      const targetLayout = getDinoViewportLayout(horizonWidth, vw, vh);
      targetX = horizonLeftInCanvas + targetLayout.dinoX;
      targetPx = targetLayout.pixelSize;
      targetHorizonY =
        horizonRect && horizonRect.height > 0
          ? horizonRect.bottom - 14 - canvasTop
          : (dockRef.current.horizonY ?? measureHorizonY()) - canvasTop;
    };

    try {
      syncMetrics();
    } catch {
      return undefined;
    }

    const splashCacti =
      vw <= 768
        ? [
            { xRatio: 0.78, variantIndex: 0, delayMs: 90 },
            { xRatio: 1.18, variantIndex: 4, delayMs: 180 },
          ]
        : [
            { xRatio: 0.56, variantIndex: 0, delayMs: 80 },
            { xRatio: 0.75, variantIndex: 4, delayMs: 150 },
            { xRatio: 0.93, variantIndex: 1, delayMs: 220 },
            { xRatio: 1.12, variantIndex: 5, delayMs: 290 },
          ];

    if (!introStartPerfRef.current) {
      introStartPerfRef.current = performance.now();
    }

    let rafId = 0;
    let settledFrames = 0;

    const render = (now: number) => {
      try {
        const currentPhase = phaseRef.current;
        if (currentPhase === 'hidden' || currentPhase === 'leaving') {
          rafId = 0;
          return;
        }
        if (currentPhase === 'docking' && !dockRef.current.onHero) {
          context.clearRect(0, 0, canvasW, canvasH);
          rafId = 0;
          return;
        }

        context.clearRect(0, 0, canvasW, canvasH);

        const introElapsed = Math.max(0, now - introStartPerfRef.current);
        const popU = clamp(introElapsed / 560, 0, 1);
        const popEase = applePopUpEase(popU);

        let curtainY = canvasH;
        let currentX = startX;
        let currentPx = startPx;
        let jumpOffset = 0;
        let squashY = 1;
        let dockElapsed = 0;
        let dockP = 0;

        if (currentPhase === 'intro') {
          const emergeOffset = (1 - popEase) * (DINO_ROWS * startPx + 16);
          curtainY = canvasH;
          currentX = startX;
          currentPx = startPx;
          jumpOffset = emergeOffset;
          if (popU > 0.25 && popU < 0.72) {
            squashY = 1 - Math.sin(((popU - 0.25) / 0.47) * Math.PI) * 0.08;
          }
          if (curtainEl) {
            curtainEl.style.transform = 'translate3d(0, 0, 0)';
          }
        } else {
          dockElapsed = Math.max(0, now - dockStartPerfRef.current);
          dockP = clamp(dockElapsed / DOCK_TRAVEL_MS, 0, 1);
          const curtainEase = appleSpringEase(dockP);

          curtainY = canvasH + (targetHorizonY - canvasH) * curtainEase;
          currentPx = startPx + (targetPx - startPx) * curtainEase;
          currentX = startX + (targetX - startX) * curtainEase;

          // Playful hop while riding the rising black edge, then cushioned land squash
          if (dockP > 0.12 && dockP < 0.72) {
            const hopU = (dockP - 0.12) / 0.6;
            jumpOffset = -Math.sin(hopU * Math.PI) * (vw <= 768 ? 16 : 26);
          } else if (dockP >= 0.72 && dockP < 0.96) {
            const landU = (dockP - 0.72) / 0.24;
            squashY = 1 - Math.sin(landU * Math.PI) * 0.1;
          }

          if (curtainEl) {
            curtainEl.style.transform = `translate3d(0, ${(curtainY - canvasH).toFixed(2)}px, 0)`;
          }
        }

        const strideRaw = introElapsed / 78;
        const strideIdx = Math.floor(strideRaw) % 4;
        const strideProgress = strideRaw - Math.floor(strideRaw);
        const isAirborne = jumpOffset < -2;
        const sprite = isAirborne
          ? SPRITE_DINO_JUMP
          : SPRITE_DINO_RUN_FRAMES[strideIdx];

        const dinoBottom = curtainY + 0.6 + jumpOffset;
        const dinoTop = dinoBottom - DINO_ROWS * currentPx;
        const blinkMod = (introElapsed % 3200) < 110;

        // Draw staggered non-linear cacti OUTSIDE the dino squash transform so they never
        // stretch/surge horizontally when the dino lands; they rise monotonically from the dark
        // horizon edge and hand off directly into PortalDinoHorizon as real obstacles.
        const totalElapsedSec = introElapsed / 1000;
        const dockU = currentPhase === 'docking' ? appleSpringEase(dockP) : 0;
        const cactusStartPx = startPx * 0.72;
        const cPx = cactusStartPx + (targetPx - cactusStartPx) * dockU;
        const nextLiveCacti: SplashHandoffObstacle[] = [];

        context.save();
        context.fillStyle = '#ffffff';
        context.beginPath();
        context.rect(0, 0, canvasW, curtainY + 1);
        context.clip();
        for (let i = 0; i < splashCacti.length; i += 1) {
          const c = splashCacti[i];
          const cX = canvasW * c.xRatio - totalElapsedSec * splashTrackSpeed;
          const spec = CACTUS_VARIANTS[c.variantIndex];
          if (cX + spec.w * cPx >= targetX + 26 * targetPx) {
            nextLiveCacti.push({
              kind: 'cactus',
              viewportX: canvasLeft + cX,
              variantIndex: c.variantIndex,
              altitudeFactor: 0,
            });
          }
          const cactusPopU = clamp((introElapsed - c.delayMs) / 520, 0, 1);
          if (cactusPopU <= 0) continue;
          const cactusEase = 1 - Math.pow(1 - cactusPopU, 3.6);
          const cH = spec.h * cPx;
          if (cX + spec.w * cPx < currentX + 26 * currentPx || cX > canvasW + 40) continue;
          const emergeY = (1 - cactusEase) * (cH + 14);
          const cTop = curtainY + 0.6 - cH + emergeY;
          drawCactusVector(context, spec.kind, cX, cTop, cPx, Math.floor(introElapsed / 220) % 2 === 1);
        }
        context.restore();

        const isBlinking = blinkMod && !isAirborne;
        liveHandoffRef.current = {
          obstacles: nextLiveCacti,
          legToggle: strideIdx % 2 === 1,
          blinkRemaining: isBlinking ? 0.08 : 0,
          timestamp: now,
          speed: splashTrackSpeed,
          strideProgress,
        };

        context.save();
        if (Math.abs(squashY - 1) > 0.004) {
          const sx = 1 / Math.sqrt(squashY);
          context.translate(currentX + 10 * currentPx, dinoBottom);
          context.scale(sx, squashY);
          context.translate(-(currentX + 10 * currentPx), -dinoBottom);
        }
        context.fillStyle = '#ffffff';
        drawSmoothSprite(context, sprite, currentX, dinoTop, currentPx);
        drawDinoEye(context, currentX, dinoTop, currentPx, {
          blinking: isBlinking,
        });
        context.restore();

        if (currentPhase === 'docking' && dockRef.current.onHero && dockP >= 1) {
          settledFrames += 1;
          if (dockElapsed >= DOCK_TRAVEL_MS + DOCK_SETTLE_MS && settledFrames >= 2) {
            rafId = 0;
            finishSplashRef.current();
            return;
          }
        } else {
          settledFrames = 0;
        }

        rafId = window.requestAnimationFrame(render);
      } catch {
        rafId = 0;
      }
    };

    const onResize = () => {
      try {
        syncMetrics();
      } catch {
        // Ignore resize error
      }
    };
    window.addEventListener('resize', onResize, { passive: true });
    // Paint synchronously on takeover so there is zero blank frame between SSR boot and React rAF.
    render(performance.now());

    return () => {
      window.removeEventListener('resize', onResize);
      if (rafId) window.cancelAnimationFrame(rafId);
    };
  }, [splashActive, playKey]);

  if (phase === 'hidden') return null;

  const isDocking = phase === 'docking' || phase === 'leaving';
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
      role="presentation"
      aria-hidden="true"
      onClick={skipToDock}
    >
      <div className={styles.backdrop} />
      <div ref={curtainRef} className={styles.curtain} data-splash-curtain="">
        <div className={styles.curtainAurora} />
      </div>
      <div className={styles.wipe} />
      <canvas ref={dinoCanvasRef} className={styles.dinoCanvas} data-splash-dino="" aria-hidden="true" />
      <div
        ref={stageRef}
        className={`${styles.stage}${isDocking && !dock.onHero ? ` ${styles.stageLeaves}` : ''}`}
        style={isDocking && !dock.onHero ? { transform: dock.transform } : undefined}
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
              <clipPath id="splash-wordmark-sheen-clip">
                {STUDYHUB_WORDMARK_GLYPHS.filter((glyph) => glyph.tone !== 'silver').map((glyph) => (
                  <path key={`sheen-${glyph.id}`} d={glyph.d} />
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
                  style={
                    {
                      '--fill-delay': `${FILL_BASE_DELAY_MS + index * FILL_STEP_MS}ms`,
                      '--mobile-fill-delay': `${420 + index * 52}ms`,
                    } as CSSProperties
                  }
                >
                  <rect
                    x={glyph.x - 4}
                    y={-4}
                    width={glyph.width + 8}
                    height={172}
                    className={glyph.tone === 'silver' ? styles.glyphFillSilver : styles.glyphFillWhite}
                  />
                  <rect
                    x={glyph.x - 4}
                    y={-16}
                    width={glyph.width + 8}
                    height={14}
                    fill="url(#splash-crest-grad)"
                    className={styles.letterCrest}
                  />
                </g>
              </g>
            ))}
            <g clipPath="url(#splash-wordmark-sheen-clip)">
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
    </div>
  );
}