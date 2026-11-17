import { useEffect, useRef } from 'react';
import styles from '../../styles/PortalDinoHorizon.module.css';

// Aligned with .horizonLayer bottom offset so GROUND_Y lands directly on
// the #1a1c20 (sky) to #ffffff (ground) horizon seam across desktop and mobile.
const GROUND_Y = 54;
const DINO_ROWS = 21;

interface SpanRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

// Compile both horizontal and vertical runs so external staircase corners
// round smoothly with appendRoundRectPath while interior joints stay solidly filled.
const compileSmoothSprite = (rows: readonly string[]): SpanRect[] => {
  const rects: SpanRect[] = [];
  const rowCount = rows.length;
  const colCount = rowCount > 0 ? rows[0].length : 0;

  for (let r = 0; r < rowCount; r += 1) {
    const row = rows[r];
    let runStart = -1;
    for (let c = 0; c <= colCount; c += 1) {
      const active = c < colCount && row[c] === '#';
      if (active && runStart === -1) {
        runStart = c;
      } else if (!active && runStart !== -1) {
        rects.push({ x: runStart, y: r, w: c - runStart, h: 1 });
        runStart = -1;
      }
    }
  }

  for (let c = 0; c < colCount; c += 1) {
    let runStart = -1;
    for (let r = 0; r <= rowCount; r += 1) {
      const active = r < rowCount && rows[r][c] === '#';
      if (active && runStart === -1) {
        runStart = r;
      } else if (!active && runStart !== -1) {
        const len = r - runStart;
        if (len >= 2) {
          rects.push({ x: c, y: runStart, w: 1, h: len });
        }
        runStart = -1;
      }
    }
  }

  return rects;
};

const DINO_UPPER_ROWS = [
  '..........########..',
  '.........##########.',
  '.........##.#######.',
  '.........##########.',
  '.........##########.',
  '.........#####......',
  '.........########...',
  '........######......',
  '#......########.....',
  '#.....###########...',
  '##...############.#.',
  '###.###########.....',
  '##############......',
  '##############......',
  '.############.......',
  '..##########........',
  '...########.........',
  '....######..........',
] as const;

const DINO_LEGS_BOTH = ['....##..##..........', '....##..##..........', '....###.###.........'] as const;
const DINO_LEGS_A = ['....##..###.........', '....##..............', '....###.............'] as const;
const DINO_LEGS_B = ['....###..##.........', '.........##.........', '.........###........'] as const;

const SPRITE_DINO_IDLE = compileSmoothSprite([...DINO_UPPER_ROWS, ...DINO_LEGS_BOTH]);
const SPRITE_DINO_RUN_A = compileSmoothSprite([...DINO_UPPER_ROWS, ...DINO_LEGS_A]);
const SPRITE_DINO_RUN_B = compileSmoothSprite([...DINO_UPPER_ROWS, ...DINO_LEGS_B]);

type CactusKind = 'small' | 'tall' | 'twin';

interface CactusSpec {
  kind: CactusKind;
  w: number;
  h: number;
}

const CACTUS_VARIANTS: readonly CactusSpec[] = [
  { kind: 'small', w: 8, h: 13.5 },
  { kind: 'tall', w: 9.6, h: 16 },
  { kind: 'twin', w: 14.5, h: 12.5 },
] as const;

const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);
const smoothstep = (t: number) => t * t * (3 - 2 * t);

const mulberry32 = (seed: number) => {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

interface Obstacle {
  x: number;
  variantIndex: number;
}

interface StageBounds {
  stageLeft: number;
  stageRight: number;
  stageWidth: number;
  edgeZone: number;
}

interface ViewportProfile {
  pixelSize: number;
  speed: number;
  jumpVy: number;
  gravity: number;
  dinoX: number;
  stageLeft: number;
  stageRight: number;
  stageWidth: number;
  edgeZone: number;
  minGap: number;
  maxGap: number;
  autoJumpMin: number;
  autoJumpMax: number;
}

const getStageBounds = (cssWidth: number, vw: number): StageBounds => {
  let stageWidth: number;
  if (vw <= 768) {
    stageWidth = Math.max(240, cssWidth - 48);
  } else if (vw <= 900) {
    stageWidth = Math.min(cssWidth - 64, 480);
  } else if (vw <= 1024) {
    stageWidth = Math.min(cssWidth - 64, 520);
  } else {
    stageWidth = Math.min(cssWidth - 64, 680);
  }
  const stageLeft = (cssWidth - stageWidth) / 2;
  const stageRight = stageLeft + stageWidth;
  const edgeZone = vw <= 768 ? 42 : 64;
  return { stageLeft, stageRight, stageWidth, edgeZone };
};

const getViewportProfile = (cssWidth: number): ViewportProfile => {
  const vh = typeof window !== 'undefined' ? window.innerHeight : 900;
  const vw = typeof window !== 'undefined' ? window.innerWidth : cssWidth;
  const isMobile = vw <= 768;
  const stage = getStageBounds(cssWidth, vw);

  if (isMobile) {
    const dinoX = Math.round(stage.stageLeft + stage.stageWidth * 0.15);
    const compactMobile = vh <= 680;
    return compactMobile
      ? {
          ...stage,
          pixelSize: 0.68,
          speed: 68,
          jumpVy: -138,
          gravity: 860,
          dinoX,
          minGap: 185,
          maxGap: 280,
          autoJumpMin: 8,
          autoJumpMax: 16,
        }
      : {
          ...stage,
          pixelSize: 0.76,
          speed: 74,
          jumpVy: -150,
          gravity: 880,
          dinoX,
          minGap: 195,
          maxGap: 295,
          autoJumpMin: 9,
          autoJumpMax: 17,
        };
  }

  const dinoX = Math.round(stage.stageLeft + stage.stageWidth * 0.16);

  if (vh <= 650) {
    return {
      ...stage,
      pixelSize: 0.72,
      speed: 74,
      jumpVy: -144,
      gravity: 870,
      dinoX,
      minGap: 240,
      maxGap: 365,
      autoJumpMin: 9,
      autoJumpMax: 18,
    };
  }

  if (vh <= 820) {
    return {
      ...stage,
      pixelSize: 0.8,
      speed: 80,
      jumpVy: -158,
      gravity: 880,
      dinoX,
      minGap: 260,
      maxGap: 390,
      autoJumpMin: 10,
      autoJumpMax: 19,
    };
  }

  return {
    ...stage,
    pixelSize: 0.92,
    speed: 86,
    jumpVy: -182,
    gravity: 920,
    dinoX,
    minGap: 285,
    maxGap: 430,
    autoJumpMin: 11,
    autoJumpMax: 21,
  };
};

const appendRoundRectPath = (
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  rawR: number
) => {
  if (w <= 0 || h <= 0) return;
  const r = Math.max(0, Math.min(rawR, w * 0.5, h * 0.5));
  if (r <= 0.05) {
    ctx.rect(x, y, w, h);
    return;
  }
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
};

const addRoundBar = (
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number
) => {
  appendRoundRectPath(ctx, x, y, w, h, Math.min(r, w / 2, h / 2));
};

const drawCactusVector = (
  ctx: CanvasRenderingContext2D,
  kind: CactusKind,
  x: number,
  y: number,
  px: number
) => {
  ctx.beginPath();
  if (kind === 'small') {
    addRoundBar(ctx, x + 2.6 * px, y, 2.8 * px, 15 * px, 1.4 * px);
    addRoundBar(ctx, x, y + 4.5 * px, 1.8 * px, 4.4 * px, 0.9 * px);
    addRoundBar(ctx, x + 0.8 * px, y + 7.2 * px, 2.8 * px, 1.8 * px, 0.9 * px);
    addRoundBar(ctx, x + 6.2 * px, y + 3.2 * px, 1.8 * px, 4.4 * px, 0.9 * px);
    addRoundBar(ctx, x + 4.4 * px, y + 5.9 * px, 2.8 * px, 1.8 * px, 0.9 * px);
  } else if (kind === 'tall') {
    addRoundBar(ctx, x + 3.2 * px, y, 3.2 * px, 17.5 * px, 1.6 * px);
    addRoundBar(ctx, x, y + 5.2 * px, 2.0 * px, 5.2 * px, 1.0 * px);
    addRoundBar(ctx, x + 0.9 * px, y + 8.5 * px, 3.2 * px, 2.0 * px, 1.0 * px);
    addRoundBar(ctx, x + 7.6 * px, y + 3.5 * px, 2.0 * px, 5.3 * px, 1.0 * px);
    addRoundBar(ctx, x + 5.4 * px, y + 6.9 * px, 3.2 * px, 2.0 * px, 1.0 * px);
  } else {
    addRoundBar(ctx, x + 2.2 * px, y, 2.4 * px, 14 * px, 1.2 * px);
    addRoundBar(ctx, x, y + 4.2 * px, 1.5 * px, 3.6 * px, 0.75 * px);
    addRoundBar(ctx, x + 0.6 * px, y + 6.3 * px, 2.4 * px, 1.5 * px, 0.75 * px);
    addRoundBar(ctx, x + 5.2 * px, y + 2.8 * px, 1.5 * px, 3.6 * px, 0.75 * px);
    addRoundBar(ctx, x + 3.6 * px, y + 4.9 * px, 2.4 * px, 1.5 * px, 0.75 * px);

    addRoundBar(ctx, x + 10.2 * px, y + 2.3 * px, 2.2 * px, 11.7 * px, 1.1 * px);
    addRoundBar(ctx, x + 8.2 * px, y + 5.4 * px, 1.4 * px, 3.0 * px, 0.7 * px);
    addRoundBar(ctx, x + 8.8 * px, y + 7.0 * px, 2.2 * px, 1.4 * px, 0.7 * px);
    addRoundBar(ctx, x + 12.9 * px, y + 4.4 * px, 1.4 * px, 3.1 * px, 0.7 * px);
    addRoundBar(ctx, x + 11.2 * px, y + 6.1 * px, 2.2 * px, 1.4 * px, 0.7 * px);
  }
  ctx.fill();
};

const drawSmoothSprite = (
  ctx: CanvasRenderingContext2D,
  spans: readonly SpanRect[],
  originX: number,
  originY: number,
  px: number
) => {
  const radius = 0.42 * px;
  ctx.beginPath();
  for (let i = 0; i < spans.length; i += 1) {
    const s = spans[i];
    appendRoundRectPath(ctx, originX + s.x * px, originY + s.y * px, s.w * px, s.h * px, radius);
  }
  ctx.fill();
};

export default function PortalDinoHorizon() {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let cssWidth = Math.max(320, Math.round(container.clientWidth));
    const cssHeight = Math.max(60, Math.round(container.clientHeight) || 68);
    let profile = getViewportProfile(cssWidth);
    let reducedMotion = Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
    let isVisible = true;
    let isTabVisible = document.visibilityState !== 'hidden';
    let splashReady =
      document.documentElement.dataset.splashState === undefined ||
      document.documentElement.dataset.splashState === 'done';

    const rand = mulberry32(0x20261117);
    const obstacles: Obstacle[] = [];

    const seedInitialTrack = () => {
      obstacles.length = 0;
      let nextObsX = profile.stageLeft + profile.stageWidth * 0.62;
      while (nextObsX < profile.stageRight + 24) {
        obstacles.push({
          x: nextObsX,
          variantIndex: Math.floor(rand() * CACTUS_VARIANTS.length),
        });
        nextObsX += profile.minGap + rand() * (profile.maxGap - profile.minGap);
      }
    };

    const syncCanvasSize = (reseedIfNeeded = false) => {
      const nextWidth = Math.max(320, Math.round(container.clientWidth));
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const widthChanged = Math.abs(nextWidth - cssWidth) > 2;
      cssWidth = nextWidth;
      profile = getViewportProfile(cssWidth);
      const targetW = Math.round(cssWidth * dpr);
      const targetH = Math.round(cssHeight * dpr);
      if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.imageSmoothingEnabled = true;
      if (reseedIfNeeded && widthChanged) {
        seedInitialTrack();
      }
    };

    syncCanvasSize(false);
    seedInitialTrack();

    let dinoY = 0; // <= 0 while airborne
    let dinoVy = 0;
    let queuedJump = false;
    let strideClock = 0;
    let legToggle = false;
    let blinkCooldown = 2.9;
    let blinkRemaining = 0;

    const triggerJump = (boost = 1) => {
      if (dinoY < -0.5) {
        queuedJump = true;
        return;
      }
      dinoY = 0;
      dinoVy = profile.jumpVy * boost;
      queuedJump = false;
    };

    let stopLoop = () => {};

    const renderFrame = () => {
      try {
        ctx.clearRect(0, 0, cssWidth, cssHeight);
      const px = profile.pixelSize;

      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, cssWidth, GROUND_Y + 1);
      ctx.clip();

      // 1. Pure #ffffff cacti rising out of GROUND_Y at stageRight and sinking into GROUND_Y at stageLeft
      ctx.fillStyle = '#ffffff';
      for (let i = 0; i < obstacles.length; i += 1) {
        const obs = obstacles[i];
        const variant = CACTUS_VARIANTS[obs.variantIndex];
        const obsW = variant.w * px;
        const obsH = variant.h * px;
        const cx = obs.x + obsW / 2;
        if (cx < profile.stageLeft || cx > profile.stageRight) continue;
        const tR = clamp((profile.stageRight - cx) / profile.edgeZone, 0, 1);
        const tL = clamp((cx - profile.stageLeft) / profile.edgeZone, 0, 1);
        const vis = Math.min(smoothstep(tR), smoothstep(tL));
        if (vis <= 0.01) continue;
        const drawY = GROUND_Y - obsH * vis;
        drawCactusVector(ctx, variant.kind, obs.x, drawY, px);
      }

      // 2. Pure #ffffff T-Rex fused into GROUND_Y when planted, leaping cleanly into #1a1c20
      const dinoBottom = GROUND_Y + 0.6 + dinoY;
      const dinoTop = dinoBottom - DINO_ROWS * px;
      const activeSprite = reducedMotion
        ? SPRITE_DINO_IDLE
        : dinoY < -0.5
        ? SPRITE_DINO_IDLE
        : legToggle
        ? SPRITE_DINO_RUN_A
        : SPRITE_DINO_RUN_B;

      ctx.fillStyle = '#ffffff';
      drawSmoothSprite(ctx, activeSprite, profile.dinoX, dinoTop, px);

      if (blinkRemaining <= 0 || dinoY < -0.5 || reducedMotion) {
        ctx.fillStyle = '#1a1c20';
        ctx.beginPath();
        appendRoundRectPath(
          ctx,
          profile.dinoX + 11 * px,
          dinoTop + 2 * px,
          1.15 * px,
          1.15 * px,
          0.35 * px
        );
        ctx.fill();
      }

        ctx.restore();
      } catch {
        stopLoop();
      }
    };

    const stepSimulation = (dt: number) => {
      let rightmostObsX = -Infinity;
      for (let i = obstacles.length - 1; i >= 0; i -= 1) {
        obstacles[i].x -= profile.speed * dt;
        const w = CACTUS_VARIANTS[obstacles[i].variantIndex].w * profile.pixelSize;
        if (obstacles[i].x + w < profile.stageLeft - 24) {
          obstacles.splice(i, 1);
        } else if (obstacles[i].x > rightmostObsX) {
          rightmostObsX = obstacles[i].x;
        }
      }

      while (rightmostObsX < profile.stageRight + 24) {
        const base = Number.isFinite(rightmostObsX)
          ? Math.max(rightmostObsX, profile.stageRight)
          : profile.stageRight;
        const nextX = base + profile.minGap + rand() * (profile.maxGap - profile.minGap);
        obstacles.push({
          x: nextX,
          variantIndex: Math.floor(rand() * CACTUS_VARIANTS.length),
        });
        rightmostObsX = nextX;
      }

      const footFrontX = profile.dinoX + 13 * profile.pixelSize;
      if (dinoY >= -0.5) {
        for (let i = 0; i < obstacles.length; i += 1) {
          const obs = obstacles[i];
          const gap = obs.x - footFrontX;
          if (gap >= profile.autoJumpMin && gap <= profile.autoJumpMax) {
            triggerJump(1);
            break;
          }
        }
      }

      if (dinoY < 0 || dinoVy < 0) {
        dinoY += dinoVy * dt;
        dinoVy += profile.gravity * dt;
        if (dinoY >= 0) {
          dinoY = 0;
          dinoVy = 0;
          if (queuedJump) {
            triggerJump(0.95);
          }
        }
      }

      strideClock += dt;
      if (strideClock >= 0.095) {
        strideClock %= 0.095;
        legToggle = !legToggle;
      }

      if (blinkRemaining > 0) {
        blinkRemaining -= dt;
      } else {
        blinkCooldown -= dt;
        if (blinkCooldown <= 0) {
          blinkRemaining = 0.11;
          blinkCooldown = 3.1 + rand() * 2.2;
        }
      }
    };

    let rafId = 0;
    let lastTime = 0;

    stopLoop = () => {
      if (rafId) {
        window.cancelAnimationFrame(rafId);
        rafId = 0;
      }
      lastTime = 0;
    };

    const tick = (now: number) => {
      if (reducedMotion || !isVisible || !isTabVisible || !splashReady) {
        rafId = 0;
        lastTime = 0;
        return;
      }
      if (!lastTime) lastTime = now;
      const dt = Math.min(0.05, Math.max(0.001, (now - lastTime) / 1000));
      lastTime = now;
      stepSimulation(dt);
      renderFrame();
      rafId = window.requestAnimationFrame(tick);
    };

    const syncLoop = () => {
      renderFrame();
      if (!reducedMotion && isVisible && isTabVisible && splashReady) {
        if (!rafId) {
          lastTime = 0;
          rafId = window.requestAnimationFrame(tick);
        }
      } else {
        stopLoop();
      }
    };

    try {
      syncLoop();
    } catch {
      stopLoop();
    }

    const resizeObserver =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => {
            syncCanvasSize(true);
            renderFrame();
          })
        : null;
    resizeObserver?.observe(container);

    const onWindowResize = () => {
      syncCanvasSize(true);
      renderFrame();
    };
    window.addEventListener('resize', onWindowResize, { passive: true });

    const intersectionObserver =
      typeof IntersectionObserver !== 'undefined'
        ? new IntersectionObserver(
            (entries) => {
              const entry = entries[0];
              if (!entry) return;
              isVisible = entry.isIntersecting;
              syncLoop();
            },
            { threshold: 0.01 }
          )
        : null;
    intersectionObserver?.observe(container);

    const onVisibilityChange = () => {
      isTabVisible = document.visibilityState !== 'hidden';
      syncLoop();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    const splashObserver =
      typeof MutationObserver !== 'undefined'
        ? new MutationObserver(() => {
            const state = document.documentElement.dataset.splashState;
            const nextReady = state === undefined || state === 'done';
            if (nextReady !== splashReady) {
              splashReady = nextReady;
              syncLoop();
            }
          })
        : null;
    splashObserver?.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-splash-state'],
    });

    const motionMql =
      typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-reduced-motion: reduce)')
        : null;
    const onMotionChange = (e: MediaQueryListEvent) => {
      reducedMotion = e.matches;
      syncLoop();
    };
    if (motionMql) {
      if (motionMql.addEventListener) {
        motionMql.addEventListener('change', onMotionChange);
      } else if (motionMql.addListener) {
        motionMql.addListener(onMotionChange);
      }
    }

    // Optional light interaction: tapping/clicking within the centered horizon runway triggers
    // a jump without blocking buttons, inputs, or links.
    const portalEl = container.closest('[data-home-portal]');
    const onPortalPointerDown = (e: Event) => {
      const pe = e as PointerEvent;
      if (reducedMotion || !splashReady) return;
      if (pe.pointerType === 'mouse' && pe.button !== 0) return;
      const target = pe.target as Element | null;
      if (
        target?.closest(
          'a, button, input, select, textarea, label, [role="button"], [data-portal-mobile-tabs]'
        )
      ) {
        return;
      }
      const rect = canvas.getBoundingClientRect();
      if (!rect.height) return;
      const horizonClientY = rect.top + (GROUND_Y / cssHeight) * rect.height;
      const inStageX =
        pe.clientX >= rect.left + profile.stageLeft - 24 &&
        pe.clientX <= rect.left + profile.stageRight + 24;
      if (inStageX && pe.clientY >= horizonClientY - 34 && pe.clientY <= horizonClientY + 18) {
        triggerJump(1.04);
      }
    };
    portalEl?.addEventListener('pointerdown', onPortalPointerDown, { passive: true });

    return () => {
      stopLoop();
      resizeObserver?.disconnect();
      intersectionObserver?.disconnect();
      splashObserver?.disconnect();
      window.removeEventListener('resize', onWindowResize);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (motionMql) {
        if (motionMql.removeEventListener) {
          motionMql.removeEventListener('change', onMotionChange);
        } else if (motionMql.removeListener) {
          motionMql.removeListener(onMotionChange);
        }
      }
      portalEl?.removeEventListener('pointerdown', onPortalPointerDown);
    };
  }, []);

  return (
    <div ref={containerRef} className={styles.horizonLayer} data-portal-dino-horizon="" aria-hidden="true">
      <canvas ref={canvasRef} className={styles.horizonCanvas} />
    </div>
  );
}
