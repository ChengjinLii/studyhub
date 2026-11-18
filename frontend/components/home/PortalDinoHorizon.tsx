import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  BIRD_COLS,
  BIRD_ROWS,
  CACTUS_VARIANTS,
  clamp,
  consumeSplashDinoHandoff,
  DINO_DUCK_ROWS,
  DINO_HANDOFF_EVENT,
  DINO_ROWS,
  AIR_VARIANTS,
  drawAirObstacle,
  drawCactusVector,
  drawCloudVector,
  drawDinoEye,
  drawSmoothSprite,
  getDinoViewportLayout,
  smoothstep,
  SPRITE_BIRD_A,
  SPRITE_DINO_CRASH,
  SPRITE_DINO_DUCK_A,
  SPRITE_DINO_DUCK_FRAMES,
  SPRITE_DINO_IDLE,
  SPRITE_DINO_JUMP,
  SPRITE_DINO_RUN_FRAMES,
} from '../../lib/dinoSprites';
import styles from '../../styles/PortalDinoHorizon.module.css';

type GameMode = 'auto' | 'manual';
type GameState = 'running' | 'gameover';

interface DinoObstacle {
  kind: 'cactus' | 'bird';
  x: number;
  variantIndex: number;
  altitudeFactor: number; // 0 for cactus; multiples of pixelSize above ground for bird
}

interface Cloud {
  x: number;
  y: number;
  scale: number;
  speedRatio: number;
}

interface TerrainTick {
  x: number;
  w: number;
  h: number;
  yOffset: number;
}

interface ImpactSpark {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
}

const HI_SCORE_KEY = 'studyhub:dino-hi-v1';
const MANUAL_IDLE_TIMEOUT_MS = 10000;
const GAMEOVER_IDLE_TIMEOUT_MS = 5000;

const mulberry32 = (seed: number) => {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

const formatScore = (val: number) => String(Math.min(99999, Math.floor(val))).padStart(5, '0');

const isFormElementActive = () => {
  if (typeof document === 'undefined') return false;
  const el = document.activeElement;
  if (!el) return false;
  if (el instanceof HTMLElement && el.isContentEditable) return true;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
};

export default function PortalDinoHorizon() {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const focusStageRef = useRef<HTMLDivElement>(null);
  const mobileDeckRef = useRef<HTMLDivElement>(null);

  const [portalHost, setPortalHost] = useState<HTMLElement | null>(null);
  const [bodyHost, setBodyHost] = useState<HTMLElement | null>(null);
  const [mode, setMode] = useState<GameMode>('auto');
  const [focusMode, setFocusMode] = useState(false);
  const [gameState, setGameState] = useState<GameState>('running');
  const [score, setScore] = useState(0);
  const [hiScore, setHiScore] = useState(0);
  const [duckPadActive, setDuckPadActive] = useState(false);
  const [jumpPadActive, setJumpPadActive] = useState(false);

  const modeRef = useRef<GameMode>('auto');
  const focusModeRef = useRef(false);
  const gameStateRef = useRef<GameState>('running');
  const hiScoreRef = useRef(0);
  const controlsRef = useRef<{
    pressJump: () => void;
    setTouchDuck: (next: boolean) => void;
    isGameOver: () => boolean;
  }>({
    pressJump: () => {},
    setTouchDuck: () => {},
    isGameOver: () => false,
  });
  const actionsRef = useRef<{
    startManual: () => void;
    restartManual: () => void;
    returnToAuto: () => void;
    toggleFocus: () => void;
  }>({
    startManual: () => {},
    restartManual: () => {},
    returnToAuto: () => {},
    toggleFocus: () => {},
  });

  const applyFocusMode = useCallback((next: boolean) => {
    focusModeRef.current = next;
    setFocusMode(next);
    if (typeof document !== 'undefined') {
      if (next) {
        if (document.activeElement instanceof HTMLElement) {
          document.activeElement.blur();
        }
        document.documentElement.dataset.dinoFocus = 'true';
        window.scrollTo({ top: 0, behavior: 'auto' });
      } else {
        delete document.documentElement.dataset.dinoFocus;
      }
    }
  }, []);

  useEffect(() => {
    setPortalHost(
      (containerRef.current?.closest('[data-home-portal]') as HTMLElement | null) ?? document.body
    );
    setBodyHost(document.body);
    try {
      const stored = Number.parseInt(window.localStorage.getItem(HI_SCORE_KEY) || '0', 10);
      if (Number.isFinite(stored) && stored > 0) {
        hiScoreRef.current = stored;
        setHiScore(stored);
      }
    } catch {
      // Ignore storage access errors.
    }
  }, []);

  const handleRestart = useCallback(() => {
    actionsRef.current.restartManual();
  }, []);

  const handleReturnAuto = useCallback(() => {
    actionsRef.current.returnToAuto();
  }, []);

  const handleToggleFocus = useCallback(() => {
    actionsRef.current.toggleFocus();
  }, []);

  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    if (mode === 'manual') {
      document.documentElement.dataset.dinoManual = 'true';
    } else {
      delete document.documentElement.dataset.dinoManual;
    }
    return undefined;
  }, [mode]);

  useEffect(() => {
    return () => {
      if (typeof document !== 'undefined') {
        delete document.documentElement.dataset.dinoFocus;
        delete document.documentElement.dataset.dinoManual;
      }
    };
  }, []);

  useEffect(() => {
    if (!focusMode) return undefined;
    const preventScroll = (event: Event) => {
      event.preventDefault();
    };
    window.addEventListener('wheel', preventScroll, { passive: false });
    window.addEventListener('touchmove', preventScroll, { passive: false });
    return () => {
      window.removeEventListener('wheel', preventScroll);
      window.removeEventListener('touchmove', preventScroll);
    };
  }, [focusMode]);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let cssWidth = Math.max(320, Math.round(container.clientWidth));
    let cssHeight = Math.max(80, Math.round(container.clientHeight) || 118);
    let groundY = cssHeight - 14;
    let vw = typeof window !== 'undefined' ? window.innerWidth : cssWidth;
    let vh = typeof window !== 'undefined' ? window.innerHeight : 900;
    let layout = getDinoViewportLayout(cssWidth, vw, vh);
    let reducedMotion = Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
    let isVisible = true;
    let isTabVisible = document.visibilityState !== 'hidden';
    let splashReady =
      document.documentElement.dataset.splashState === undefined ||
      document.documentElement.dataset.splashState === 'done';

    const rand = mulberry32(0x20261117);
    const obstacles: DinoObstacle[] = [];
    const clouds: Cloud[] = [];
    const ticks: TerrainTick[] = [];
    const sparks: ImpactSpark[] = [];

    const seedDecorations = () => {
      clouds.length = 0;
      const cloudCount = vw <= 768 ? 2 : 4;
      for (let i = 0; i < cloudCount; i += 1) {
        clouds.push({
          x: cssWidth * (0.25 + i * 0.28) + rand() * 80,
          y: Math.max(12, groundY - (22 + rand() * 20) * layout.pixelSize * 0.72),
          scale: layout.pixelSize * (0.65 + rand() * 0.25),
          speedRatio: 0.16 + rand() * 0.1,
        });
      }

      ticks.length = 0;
      const count = Math.max(20, Math.floor(cssWidth / 34));
      for (let i = 0; i < count; i += 1) {
        ticks.push({
          x: (i / count) * cssWidth + rand() * 24,
          w: 1.5 + rand() * 4.5,
          h: rand() > 0.7 ? 1.8 : 1.1,
          yOffset: rand() > 0.72 ? -1.4 : 2.2 + rand() * 2.5,
        });
      }
    };

    let lastGroundIdx = -1;
    let lastAirIdx = -1;
    let consecutiveAirCount = 0;

    // 5/6 aerial obstacles sit at torso/head band (require ducking) and 1/6 skim low (jump).
    const DUCK_DOMINANT_AIR_HEIGHTS = [13, 14, 15, 13, 15, 4] as const;

    const pickNextAirAltitude = () =>
      DUCK_DOMINANT_AIR_HEIGHTS[Math.floor(rand() * DUCK_DOMINANT_AIR_HEIGHTS.length)];

    const pickNextGroundVariant = () => {
      let next = Math.floor(rand() * CACTUS_VARIANTS.length);
      if (next === lastGroundIdx) {
        next = (next + 1 + Math.floor(rand() * (CACTUS_VARIANTS.length - 1))) % CACTUS_VARIANTS.length;
      }
      lastGroundIdx = next;
      return next;
    };

    const pickNextAirVariant = () => {
      let next = Math.floor(rand() * AIR_VARIANTS.length);
      if (next === lastAirIdx) {
        next = (next + 1) % AIR_VARIANTS.length;
      }
      lastAirIdx = next;
      return next;
    };

    const spawnInitialObstacles = (manualStart: boolean) => {
      obstacles.length = 0;
      consecutiveAirCount = 0;
      const minGap = Math.max(230, cssWidth * 0.24);
      const maxGap = Math.max(minGap + 110, cssWidth * 0.38);
      let cursor = manualStart
        ? Math.max(layout.dinoX + 360, cssWidth * 0.68)
        : Math.max(layout.dinoX + 260, cssWidth * 0.44);
      const endX = cssWidth + 180;
      const demoSequence: readonly { kind: 'cactus' | 'bird'; variantIndex: number; altitude: number }[] = [
        { kind: 'cactus', variantIndex: 4, altitude: 0 },
        { kind: 'bird', variantIndex: 1, altitude: 14 },
        { kind: 'cactus', variantIndex: 5, altitude: 0 },
        { kind: 'bird', variantIndex: 0, altitude: 13 },
      ];
      let idx = 0;
      while (cursor <= endX) {
        if (!manualStart && idx < demoSequence.length) {
          const preset = demoSequence[idx];
          obstacles.push({
            kind: preset.kind,
            x: cursor,
            variantIndex: preset.variantIndex,
            altitudeFactor: preset.altitude,
          });
          if (preset.kind === 'bird') {
            lastAirIdx = preset.variantIndex;
            consecutiveAirCount += 1;
          } else {
            lastGroundIdx = preset.variantIndex;
            consecutiveAirCount = 0;
          }
        } else {
          const useAir =
            idx > 0 && (manualStart ? idx === 2 : consecutiveAirCount < 2 && rand() < 0.38);
          if (useAir) {
            consecutiveAirCount += 1;
            obstacles.push({
              kind: 'bird',
              x: cursor,
              variantIndex: pickNextAirVariant(),
              altitudeFactor: pickNextAirAltitude(),
            });
          } else {
            consecutiveAirCount = 0;
            obstacles.push({
              kind: 'cactus',
              x: cursor,
              variantIndex: pickNextGroundVariant(),
              altitudeFactor: 0,
            });
          }
        }
        idx += 1;
        cursor += minGap + rand() * (maxGap - minGap);
      }
    };

    const syncCanvasSize = (reseedIfNeeded = false) => {
      const nextWidth = Math.max(320, Math.round(container.clientWidth));
      const nextHeight = Math.max(80, Math.round(container.clientHeight) || 118);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const widthChanged = Math.abs(nextWidth - cssWidth) > 2;
      cssWidth = nextWidth;
      cssHeight = nextHeight;
      groundY = cssHeight - 14;
      vw = window.innerWidth;
      vh = window.innerHeight;
      layout = getDinoViewportLayout(cssWidth, vw, vh);
      const targetW = Math.round(cssWidth * dpr);
      const targetH = Math.round(cssHeight * dpr);
      if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.imageSmoothingEnabled = true;
      if (reseedIfNeeded && widthChanged) {
        seedDecorations();
        spawnInitialObstacles(modeRef.current === 'manual');
      }
    };

    syncCanvasSize(false);
    seedDecorations();
    spawnInitialObstacles(false);

    let dinoY = 0; // <= 0 while airborne
    let dinoVy = 0;
    let queuedJump = false;
    let keyDucking = false;
    let touchDucking = false;
    let ducking = false;
    const syncDuckState = () => {
      ducking = keyDucking || touchDucking;
    };
    let autoDuckTimer = 0;
    let manualScore = 0;
    let distanceAccumulator = 0;
    let lastReportedScore = -1;
    let currentSpeed = layout.baseSpeed;
    let strideClock = 0;
    let wingClock = 0;
    let strideStep = 0;
    let legToggle = false;
    let wingToggle = false;
    let blinkCooldown = 2.6;
    let blinkRemaining = 0;
    let shakeTimer = 0;
    let autoCrashTimer = 0;
    let squashY = 1; // Subtle Apple landing / jump stretch & squash
    let lastManualInputAt = 0;
    let decorOpacity = 1;
    let handoffStartSpeed = layout.baseSpeed;
    let handoffBlendElapsed = 1;
    let preserveNextLastTime = false;

    const markManualActivity = () => {
      lastManualInputAt = performance.now();
    };

    const triggerJump = (boost = 1) => {
      if (gameStateRef.current === 'gameover') return;
      if (dinoY < -0.5) {
        queuedJump = true;
        return;
      }
      dinoY = 0;
      dinoVy = layout.jumpVy * boost;
      keyDucking = false;
      touchDucking = false;
      ducking = false;
      squashY = 1.1;
      queuedJump = false;
    };

    const resetRound = (nextMode: GameMode, jumpOnStart: boolean) => {
      modeRef.current = nextMode;
      gameStateRef.current = 'running';
      if (nextMode === 'manual') {
        markManualActivity();
      }
      if (nextMode === 'auto') {
        applyFocusMode(false);
      }
      setMode(nextMode);
      setGameState('running');
      dinoY = 0;
      dinoVy = 0;
      queuedJump = false;
      keyDucking = false;
      touchDucking = false;
      ducking = false;
      autoDuckTimer = 0;
      manualScore = 0;
      distanceAccumulator = 0;
      lastReportedScore = 0;
      setScore(0);
      currentSpeed = layout.baseSpeed;
      shakeTimer = 0;
      autoCrashTimer = 0;
      sparks.length = 0;
      strideStep = 0;
      legToggle = false;
      squashY = 1;
      spawnInitialObstacles(nextMode === 'manual');
      if (jumpOnStart) {
        triggerJump(0.92);
      }
    };

    actionsRef.current = {
      startManual: () => resetRound('manual', true),
      restartManual: () => resetRound('manual', true),
      returnToAuto: () => resetRound('auto', false),
      toggleFocus: () => {
        if (modeRef.current !== 'manual') return;
        markManualActivity();
        touchDucking = false;
        keyDucking = false;
        syncDuckState();
        applyFocusMode(!focusModeRef.current);
      },
    };

    controlsRef.current = {
      pressJump: () => {
        if (reducedMotion || !splashReady) return;
        markManualActivity();
        if (modeRef.current === 'auto') {
          actionsRef.current.startManual();
        } else if (gameStateRef.current === 'gameover') {
          actionsRef.current.restartManual();
        } else {
          triggerJump(1);
        }
      },
      setTouchDuck: (next: boolean) => {
        touchDucking = next;
        syncDuckState();
        if (next && modeRef.current === 'manual') {
          markManualActivity();
        }
      },
      isGameOver: () => gameStateRef.current === 'gameover',
    };

    let stopLoop = () => {};

    const emitImpactSparks = (hitX: number, hitY: number) => {
      shakeTimer = 0.24;
      sparks.length = 0;
      for (let i = 0; i < 10; i += 1) {
        const ang = (Math.PI * 2 * i) / 10 + rand() * 0.4;
        const spd = 65 + rand() * 95;
        sparks.push({
          x: hitX,
          y: hitY,
          vx: Math.cos(ang) * spd,
          vy: Math.sin(ang) * spd - 35,
          life: 0.36 + rand() * 0.14,
          maxLife: 0.5,
        });
      }
    };

    const triggerDeath = (hitX: number, hitY: number) => {
      if (modeRef.current !== 'manual') {
        autoCrashTimer = 0.95;
        emitImpactSparks(hitX, hitY);
        return;
      }
      gameStateRef.current = 'gameover';
      setGameState('gameover');
      markManualActivity();
      const finalScore = Math.floor(manualScore);
      setScore(finalScore);
      if (finalScore > hiScoreRef.current) {
        hiScoreRef.current = finalScore;
        setHiScore(finalScore);
        try {
          window.localStorage.setItem(HI_SCORE_KEY, String(finalScore));
        } catch {
          // Ignore storage write errors.
        }
      }
      emitImpactSparks(hitX, hitY);
    };

    const renderFrame = () => {
      try {
        ctx.clearRect(0, 0, cssWidth, cssHeight);
        const px = layout.pixelSize;
        const leftExitBoundary = Math.max(8, layout.dinoX - 58);

        ctx.save();
        if (shakeTimer > 0) {
          const mag = (shakeTimer / 0.24) * 3.5;
          ctx.translate((Math.sin(shakeTimer * 95) * mag), (Math.cos(shakeTimer * 120) * mag * 0.6));
        }

        // Clip above ground seam
        ctx.beginPath();
        ctx.rect(0, 0, cssWidth, groundY + 6);
        ctx.clip();

        // 1. Subtle monochrome clouds drifting across the upper dark sky
        if (decorOpacity > 0.01) {
          ctx.fillStyle = `rgba(255, 255, 255, ${(0.13 * decorOpacity).toFixed(3)})`;
          for (let i = 0; i < clouds.length; i += 1) {
            const cl = clouds[i];
            drawCloudVector(ctx, cl.x, cl.y, cl.scale);
          }

          // 2. Scrolling ground ticks & pebbles along the horizon edge
          ctx.fillStyle = `rgba(255, 255, 255, ${(0.32 * decorOpacity).toFixed(3)})`;
          for (let i = 0; i < ticks.length; i += 1) {
            const tk = ticks[i];
            if (tk.x < leftExitBoundary - 12 || tk.x > cssWidth + 8) continue;
            ctx.fillRect(tk.x, groundY + tk.yOffset, tk.w, tk.h);
          }
        }

        // 3. Pixel-art cacti/campus props & aerial flyers (SPRITE_BIRD_A, paper_plane, ufo)
        ctx.fillStyle = '#ffffff';
        for (let i = 0; i < obstacles.length; i += 1) {
          const obs = obstacles[i];
          if (obs.kind === 'cactus') {
            const variant = CACTUS_VARIANTS[obs.variantIndex];
            const obsW = variant.w * px;
            const obsH = variant.h * px;
            const cx = obs.x + obsW / 2;
            if (cx < leftExitBoundary || obs.x > cssWidth + 40) continue;
            const tL = clamp((cx - leftExitBoundary) / 22, 0, 1);
            const vis = smoothstep(tL);
            if (vis <= 0.01) continue;
            const drawY = groundY + 0.6 - obsH * vis;
            drawCactusVector(ctx, variant.kind, obs.x, drawY, px, wingToggle);
          } else {
            const birdW = BIRD_COLS * px;
            const birdH = BIRD_ROWS * px;
            const cx = obs.x + birdW / 2;
            if (cx < leftExitBoundary || obs.x > cssWidth + 24) continue;
            const alphaL = clamp((cx - leftExitBoundary) / 32, 0, 1);
            const alphaR = clamp((cssWidth - cx) / 24, 0, 1);
            const vis = Math.min(smoothstep(alphaL), smoothstep(alphaR));
            if (vis <= 0.02) continue;
            ctx.save();
            ctx.globalAlpha = vis;
            const airKind = AIR_VARIANTS[obs.variantIndex % AIR_VARIANTS.length];
            const bobY = airKind === 'bird' ? 0 : Math.sin(obs.x * 0.035) * 1.3 * px;
            const birdTop = groundY - obs.altitudeFactor * px - birdH + bobY;
            if (reducedMotion && airKind === 'bird') {
              drawSmoothSprite(ctx, SPRITE_BIRD_A, obs.x, birdTop, px);
            } else {
              drawAirObstacle(ctx, obs.variantIndex, wingToggle, obs.x, birdTop, px);
            }
            ctx.restore();
          }
        }

        // 4. White T-Rex (standing / 4-frame running / jump tuck / ducking / dizzy crash) at left of search box
        const isCrashed = gameStateRef.current === 'gameover' || autoCrashTimer > 0;
        const isDucking = !isCrashed && ducking && dinoY >= -0.5;
        const airborneStr = dinoY < -0.5 ? 'true' : 'false';
        const duckingStr = isDucking ? 'true' : 'false';
        if (container.dataset.dinoAirborne !== airborneStr) {
          container.dataset.dinoAirborne = airborneStr;
        }
        if (container.dataset.dinoDucking !== duckingStr) {
          container.dataset.dinoDucking = duckingStr;
        }
        const sprite = isCrashed
          ? SPRITE_DINO_CRASH
          : isDucking
            ? reducedMotion
              ? SPRITE_DINO_DUCK_A
              : SPRITE_DINO_DUCK_FRAMES[strideStep]
            : reducedMotion
              ? SPRITE_DINO_IDLE
              : dinoY < -0.5
                ? SPRITE_DINO_JUMP
                : SPRITE_DINO_RUN_FRAMES[strideStep];

        const rows = isDucking ? DINO_DUCK_ROWS : DINO_ROWS;
        const dinoBottom = groundY + 0.6 + dinoY;
        const spriteHeight = rows * px;
        const dinoTop = dinoBottom - spriteHeight;

        ctx.save();
        if (Math.abs(squashY - 1) > 0.005) {
          const sx = 1 / Math.sqrt(squashY);
          ctx.translate(layout.dinoX + 10 * px, dinoBottom);
          ctx.scale(sx, squashY);
          ctx.translate(-(layout.dinoX + 10 * px), -dinoBottom);
        }
        ctx.fillStyle = '#ffffff';
        drawSmoothSprite(ctx, sprite, layout.dinoX, dinoTop, px);
        drawDinoEye(ctx, layout.dinoX, dinoTop, px, {
          crashed: isCrashed,
          blinking: blinkRemaining > 0 && dinoY >= -0.5 && !reducedMotion,
          ducking: isDucking,
        });
        ctx.restore();

        // 5. Impact sparks on death
        if (sparks.length > 0) {
          ctx.fillStyle = '#ffffff';
          for (let i = 0; i < sparks.length; i += 1) {
            const sp = sparks[i];
            if (sp.life <= 0) continue;
            ctx.globalAlpha = clamp(sp.life / sp.maxLife, 0, 1);
            const r = Math.max(1.2, px * 0.9);
            ctx.fillRect(sp.x - r * 0.5, sp.y - r * 0.5, r, r);
          }
          ctx.globalAlpha = 1;
        }

        ctx.restore();
      } catch {
        stopLoop();
      }
    };

    const stepSimulation = (dt: number) => {
      if (shakeTimer > 0) {
        shakeTimer = Math.max(0, shakeTimer - dt);
      }
      for (let i = sparks.length - 1; i >= 0; i -= 1) {
        const sp = sparks[i];
        sp.x += sp.vx * dt;
        sp.y += sp.vy * dt;
        sp.vy += 320 * dt;
        sp.life -= dt;
        if (sp.life <= 0) sparks.splice(i, 1);
      }

      if (modeRef.current === 'manual') {
        const idleMs = performance.now() - lastManualInputAt;
        const limitMs = focusModeRef.current
          ? 30000
          : gameStateRef.current === 'gameover'
            ? GAMEOVER_IDLE_TIMEOUT_MS
            : MANUAL_IDLE_TIMEOUT_MS;
        if (idleMs >= limitMs) {
          actionsRef.current.returnToAuto();
          return;
        }
      }

      if (gameStateRef.current === 'gameover') {
        return;
      }
      if (autoCrashTimer > 0) {
        autoCrashTimer = Math.max(0, autoCrashTimer - dt);
        if (autoCrashTimer === 0) {
          resetRound('auto', false);
        }
        return;
      }

      const px = layout.pixelSize;
      const isManual = modeRef.current === 'manual';
      if (isManual) {
        const speedBoost = Math.min(130, manualScore * 0.16);
        currentSpeed = layout.baseSpeed + speedBoost;
        distanceAccumulator += currentSpeed * dt;
        manualScore = distanceAccumulator / 16;
        const rounded = Math.floor(manualScore);
        if (rounded !== lastReportedScore) {
          lastReportedScore = rounded;
          setScore(rounded);
        }
      } else {
        if (handoffBlendElapsed < 0.85) {
          handoffBlendElapsed = Math.min(0.85, handoffBlendElapsed + dt);
          const ramp = smoothstep(clamp(handoffBlendElapsed / 0.85, 0, 1));
          currentSpeed = handoffStartSpeed + (layout.baseSpeed - handoffStartSpeed) * ramp;
        } else {
          currentSpeed = layout.baseSpeed;
        }
      }
      if (decorOpacity < 1) {
        decorOpacity = Math.min(1, decorOpacity + dt / 0.45);
      }

      // Clouds
      for (let i = 0; i < clouds.length; i += 1) {
        const cl = clouds[i];
        cl.x -= currentSpeed * cl.speedRatio * dt;
        if (cl.x < -60) {
          cl.x = cssWidth + 20 + rand() * 80;
          cl.y = Math.max(12, groundY - (22 + rand() * 20) * px * 0.72);
        }
      }

      // Terrain ticks
      for (let i = 0; i < ticks.length; i += 1) {
        const tk = ticks[i];
        tk.x -= currentSpeed * dt;
        if (tk.x + tk.w < 0) {
          tk.x = cssWidth + rand() * 30;
          tk.w = 1.5 + rand() * 4.5;
        }
      }

      // Obstacles
      const leftRemovalBoundary = Math.max(-40, layout.dinoX - 74);
      let rightmostObsX = -Infinity;
      for (let i = obstacles.length - 1; i >= 0; i -= 1) {
        const obs = obstacles[i];
        const birdBonus = obs.kind === 'bird' ? 1.12 : 1;
        obs.x -= currentSpeed * birdBonus * dt;
        const w =
          obs.kind === 'bird'
            ? BIRD_COLS * px
            : CACTUS_VARIANTS[obs.variantIndex].w * px;
        if (obs.x + w < leftRemovalBoundary) {
          obstacles.splice(i, 1);
        } else if (obs.x > rightmostObsX) {
          rightmostObsX = obs.x;
        }
      }

      // Spawn new obstacles from the right blank area
      const minGap = Math.max(210, cssWidth * 0.24) + (isManual ? Math.min(110, manualScore * 0.2) : 0);
      const maxGap = Math.max(minGap + 120, cssWidth * 0.4);
      while (rightmostObsX < cssWidth + 24) {
        const base = Number.isFinite(rightmostObsX)
          ? Math.max(rightmostObsX, cssWidth + 16)
          : cssWidth + 24;
        const nextX = base + minGap + rand() * (maxGap - minGap);
        const allowBird = !isManual || manualScore >= 6;
        const spawnBird = allowBird && consecutiveAirCount < 2 && rand() < 0.38;
        if (spawnBird) {
          consecutiveAirCount += 1;
          obstacles.push({
            kind: 'bird',
            x: nextX,
            variantIndex: pickNextAirVariant(),
            altitudeFactor: pickNextAirAltitude(),
          });
        } else {
          consecutiveAirCount = 0;
          obstacles.push({
            kind: 'cactus',
            x: nextX,
            variantIndex: pickNextGroundVariant(),
            altitudeFactor: 0,
          });
        }
        rightmostObsX = nextX;
      }

      // Real demo AI when user hasn't clicked the black edge: plays by the exact same
      // physics & hitboxes (no invincibility), centering jump apex over obstacles or ducking birds.
      if (!isManual) {
        if (autoDuckTimer > 0) {
          autoDuckTimer = Math.max(0, autoDuckTimer - dt);
          ducking = autoDuckTimer > 0;
        }
        const dinoCenterX = layout.dinoX + 9 * px;
        const idealApexLead = currentSpeed * (Math.abs(layout.jumpVy) / layout.gravity);
        if (dinoY >= -0.5) {
          let nextObs: DinoObstacle | null = null;
          let minRight = Infinity;
          for (let i = 0; i < obstacles.length; i += 1) {
            const obs = obstacles[i];
            const w = obs.kind === 'bird' ? BIRD_COLS * px : CACTUS_VARIANTS[obs.variantIndex].w * px;
            if (obs.x + w > layout.dinoX + 4 * px && obs.x < minRight) {
              minRight = obs.x;
              nextObs = obs;
            }
          }
          if (nextObs) {
            if (nextObs.kind === 'bird' && nextObs.altitudeFactor >= 12) {
              const birdLead = nextObs.x - (layout.dinoX + 22 * px);
              if (birdLead <= currentSpeed * 0.16) {
                ducking = true;
                autoDuckTimer = Math.max(autoDuckTimer, (nextObs.x + BIRD_COLS * px - layout.dinoX) / Math.max(80, currentSpeed) + 0.06);
              }
            } else {
              const obsW =
                nextObs.kind === 'bird'
                  ? BIRD_COLS * px
                  : CACTUS_VARIANTS[nextObs.variantIndex].w * px;
              const obsCenter = nextObs.x + obsW * 0.5;
              const centerDist = obsCenter - dinoCenterX;
              const leadAdjusted = nextObs.kind === 'bird' ? idealApexLead * 1.12 : idealApexLead;
              if (centerDist >= -4 * px && centerDist <= leadAdjusted) {
                ducking = false;
                autoDuckTimer = 0;
                triggerJump(1);
              }
            }
          }
        }
      }

      // Vertical physics + snap fast-drop when ducking mid-air
      if (dinoY < 0 || dinoVy < 0) {
        if (ducking && isManual && dinoVy < 0) {
          dinoVy *= 0.32;
        }
        const grav = ducking && isManual ? layout.gravity * 3.0 : layout.gravity;
        dinoY += dinoVy * dt;
        dinoVy += grav * dt;
        if (dinoY >= 0) {
          dinoY = 0;
          dinoVy = 0;
          squashY = 0.88; // Tactile Apple landing squash
          if (queuedJump) {
            triggerJump(0.95);
          }
        }
      }

      // Recover squashY towards 1 smoothly
      squashY += (1 - squashY) * Math.min(1, dt * 16);

      // Real hitbox collision check in BOTH manual play and auto-demo mode (no invincibility)
      {
        const isDuck = ducking && dinoY >= -0.5;
        const dinoBoxLeft = layout.dinoX + 5 * px;
        const dinoBoxRight = layout.dinoX + (isDuck ? 22 : 13) * px;
        const dinoBoxBottom = groundY + dinoY - 2 * px;
        const dinoBoxTop = groundY + dinoY - (isDuck ? DINO_DUCK_ROWS - 2 : DINO_ROWS - 3) * px;

        for (let i = 0; i < obstacles.length; i += 1) {
          const obs = obstacles[i];
          let obsLeft: number;
          let obsRight: number;
          let obsTop: number;
          let obsBottom: number;
          if (obs.kind === 'cactus') {
            const spec = CACTUS_VARIANTS[obs.variantIndex];
            obsLeft = obs.x + 2 * px;
            obsRight = obs.x + (spec.w - 2) * px;
            obsBottom = groundY;
            const topInset = spec.kind === 'coffee' ? 4.5 : 2;
            obsTop = groundY - (spec.h - topInset) * px;
          } else {
            const airKind = AIR_VARIANTS[obs.variantIndex % AIR_VARIANTS.length];
            const bobY = airKind === 'bird' ? 0 : Math.sin(obs.x * 0.035) * 1.3 * px;
            obsLeft = obs.x + 3 * px;
            obsRight = obs.x + (BIRD_COLS - 3) * px;
            obsBottom = groundY - obs.altitudeFactor * px + bobY - 2 * px;
            obsTop = groundY - obs.altitudeFactor * px + bobY - (BIRD_ROWS - 3) * px;
          }

          if (
            dinoBoxRight > obsLeft &&
            dinoBoxLeft < obsRight &&
            dinoBoxBottom > obsTop &&
            dinoBoxTop < obsBottom
          ) {
            triggerDeath((dinoBoxRight + obsLeft) * 0.5, (dinoBoxTop + dinoBoxBottom) * 0.5);
            return;
          }
        }
      }

      // 4-frame stride, wing flap / steam & UFO blink, eye blink clocks
      strideClock += dt;
      if (strideClock >= 0.068) {
        const steps = Math.floor(strideClock / 0.068);
        strideClock %= 0.068;
        strideStep = (strideStep + steps) % 4;
        legToggle = strideStep % 2 === 1;
      }

      wingClock += dt;
      if (wingClock >= 0.16) {
        wingClock %= 0.16;
        wingToggle = !wingToggle;
      }

      if (blinkRemaining > 0) {
        blinkRemaining -= dt;
      } else {
        blinkCooldown -= dt;
        if (blinkCooldown <= 0) {
          blinkRemaining = 0.11;
          blinkCooldown = 2.8 + rand() * 2.4;
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
          if (preserveNextLastTime) {
            preserveNextLastTime = false;
          } else {
            lastTime = 0;
          }
          rafId = window.requestAnimationFrame(tick);
        }
      } else {
        preserveNextLastTime = false;
        stopLoop();
      }
    };

    syncLoop();

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
              if (!entry.isIntersecting && modeRef.current === 'manual' && !focusModeRef.current) {
                actionsRef.current.returnToAuto();
                return;
              }
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

    const adoptSplashHandoffIfPresent = () => {
      const handoff = consumeSplashDinoHandoff();
      if (!handoff) return false;
      legToggle = handoff.legToggle;
      strideStep = handoff.legToggle ? 1 : 0;
      blinkRemaining = handoff.blinkRemaining;
      strideClock = clamp(handoff.strideProgress, 0, 1) * 0.068;
      handoffStartSpeed = handoff.speed > 0 ? handoff.speed : layout.baseSpeed;
      handoffBlendElapsed = 0;
      currentSpeed = handoffStartSpeed;
      decorOpacity = 0;
      lastTime = handoff.timestamp;
      preserveNextLastTime = true;
      const items = handoff.obstacles;
      if (items.length > 0) {
        const horizonLeft = container.getBoundingClientRect().left;
        const minGap = Math.max(210, cssWidth * 0.24);
        const maxGap = Math.max(minGap + 110, cssWidth * 0.38);
        const nextObstacles: DinoObstacle[] = [];
        let rightmost = -Infinity;
        for (let i = 0; i < items.length; i += 1) {
          const item = items[i];
          const localX = item.viewportX - horizonLeft;
          const obsW =
            item.kind === 'cactus' ? CACTUS_VARIANTS[item.variantIndex].w * layout.pixelSize : 0;
          if (localX + obsW < layout.dinoX + 26 * layout.pixelSize) continue;
          nextObstacles.push({
            kind: item.kind,
            x: localX,
            variantIndex: item.variantIndex,
            altitudeFactor: item.altitudeFactor,
          });
          if (localX > rightmost) rightmost = localX;
        }
        if (nextObstacles.length > 0) {
          consecutiveAirCount = 0;
          while (rightmost < cssWidth + 140) {
            const nextX = Math.max(rightmost, cssWidth * 0.85) + minGap + rand() * (maxGap - minGap);
            const isAir = consecutiveAirCount < 2 && rand() < 0.38;
            if (isAir) consecutiveAirCount += 1;
            else consecutiveAirCount = 0;
            nextObstacles.push({
              kind: isAir ? 'bird' : 'cactus',
              x: nextX,
              variantIndex: isAir ? pickNextAirVariant() : pickNextGroundVariant(),
              altitudeFactor: isAir ? pickNextAirAltitude() : 0,
            });
            rightmost = nextX;
          }
          obstacles.length = 0;
          obstacles.push(...nextObstacles);
        }
      }
      return true;
    };

    const onHandoffEvent = () => {
      adoptSplashHandoffIfPresent();
      splashReady = true;
      syncLoop();
    };
    window.addEventListener(DINO_HANDOFF_EVENT, onHandoffEvent);

    if (splashReady) {
      adoptSplashHandoffIfPresent();
    }

    const splashObserver =
      typeof MutationObserver !== 'undefined'
        ? new MutationObserver(() => {
            const state = document.documentElement.dataset.splashState;
            const nextReady = state === undefined || state === 'done';
            if (nextReady !== splashReady) {
              splashReady = nextReady;
              if (nextReady) {
                adoptSplashHandoffIfPresent();
              }
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
      if (motionMql.addEventListener) motionMql.addEventListener('change', onMotionChange);
      else if (motionMql.addListener) motionMql.addListener(onMotionChange);
    }

    // Black edge interaction: clicking the dark canopy edge switches from auto-pilot to manual play,
    // jumps while running, and restarts after Game Over.
    const portalEl = container.closest('[data-home-portal]');
    let touchStartY: number | null = null;
    const isInteractiveTarget = (target: Element | null) =>
      Boolean(
        target?.closest(
          'a, button, input, select, textarea, label, [role="button"], [data-portal-mobile-tabs], [data-portal-anniversary], [data-search-pill], [class*="advancedPanel"]'
        )
      );

    const isOnBlackEdgeBand = (clientY: number) => {
      const rect = canvas.getBoundingClientRect();
      if (!rect.height) return false;
      const horizonClientY = rect.top + (groundY / cssHeight) * rect.height;
      return clientY >= horizonClientY - 120 && clientY <= horizonClientY + 26;
    };

    const onWindowPointerDown = (e: Event) => {
      const pe = e as PointerEvent;
      if (reducedMotion || !splashReady) return;
      if (pe.pointerType === 'mouse' && pe.button !== 0) return;
      const target = pe.target as Element | null;
      if (isInteractiveTarget(target)) return;
      if (focusModeRef.current) return;
      if (!portalEl || (target && !portalEl.contains(target))) return;
      if (!isOnBlackEdgeBand(pe.clientY)) return;

      touchStartY = pe.clientY;
      markManualActivity();
      if (modeRef.current === 'auto') {
        actionsRef.current.startManual();
      } else if (gameStateRef.current === 'gameover') {
        actionsRef.current.restartManual();
      } else {
        triggerJump(1);
      }
    };

    const onPortalPointerMove = (e: Event) => {
      const pe = e as PointerEvent;
      if (touchStartY === null || modeRef.current !== 'manual') return;
      if (pe.clientY - touchStartY > 24) {
        ducking = true;
      }
    };

    const onPortalPointerUp = () => {
      if (touchStartY !== null) {
        touchStartY = null;
        if (modeRef.current === 'manual') {
          ducking = false;
        }
      }
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (modeRef.current !== 'manual' || !splashReady || reducedMotion) return;
      if (isFormElementActive()) return;

      if (event.key === 'f' || event.key === 'F') {
        event.preventDefault();
        actionsRef.current.toggleFocus();
        return;
      }

      if (event.key === 'Escape') {
        event.preventDefault();
        if (focusModeRef.current) {
          markManualActivity();
          applyFocusMode(false);
        } else {
          actionsRef.current.returnToAuto();
        }
        return;
      }

      if (event.key === ' ' || event.key === 'ArrowUp' || event.key === 'w' || event.key === 'W') {
        event.preventDefault();
        markManualActivity();
        if (gameStateRef.current === 'gameover') {
          actionsRef.current.restartManual();
        } else {
          triggerJump(1);
        }
        return;
      }

      if (event.key === 'ArrowDown' || event.key === 's' || event.key === 'S') {
        event.preventDefault();
        markManualActivity();
        keyDucking = true;
        syncDuckState();
      }
    };

    const onKeyUp = (event: KeyboardEvent) => {
      if (modeRef.current !== 'manual') return;
      if (event.key === 'ArrowDown' || event.key === 's' || event.key === 'S') {
        keyDucking = false;
        syncDuckState();
      }
    };

    const onWindowFocusIn = () => {
      if (modeRef.current === 'manual' && !focusModeRef.current && isFormElementActive()) {
        actionsRef.current.returnToAuto();
      }
    };

    window.addEventListener('pointerdown', onWindowPointerDown, { passive: true });
    window.addEventListener('pointermove', onPortalPointerMove, { passive: true });
    window.addEventListener('pointerup', onPortalPointerUp, { passive: true });
    window.addEventListener('pointercancel', onPortalPointerUp, { passive: true });
    window.addEventListener('focusin', onWindowFocusIn);
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);

    return () => {
      stopLoop();
      resizeObserver?.disconnect();
      intersectionObserver?.disconnect();
      window.removeEventListener(DINO_HANDOFF_EVENT, onHandoffEvent);
      splashObserver?.disconnect();
      window.removeEventListener('resize', onWindowResize);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (motionMql) {
        if (motionMql.removeEventListener) motionMql.removeEventListener('change', onMotionChange);
        else if (motionMql.removeListener) motionMql.removeListener(onMotionChange);
      }
      window.removeEventListener('pointerdown', onWindowPointerDown);
      window.removeEventListener('pointermove', onPortalPointerMove);
      window.removeEventListener('pointerup', onPortalPointerUp);
      window.removeEventListener('pointercancel', onPortalPointerUp);
      window.removeEventListener('focusin', onWindowFocusIn);
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [applyFocusMode]);

  useEffect(() => {
    if (gameState === 'gameover') {
      controlsRef.current.setTouchDuck(false);
      setDuckPadActive(false);
      setJumpPadActive(false);
    }
  }, [gameState]);

  useEffect(() => {
    if (mode !== 'manual') {
      controlsRef.current.setTouchDuck(false);
      setDuckPadActive(false);
      setJumpPadActive(false);
      return undefined;
    }

    const stageEl = focusMode ? focusStageRef.current : null;
    const deckEl = mobileDeckRef.current;
    if (!stageEl && !deckEl) return undefined;

    const duckTouches = new Set<number>();
    const jumpTouches = new Set<number>();
    const skyTouches = new Map<number, { startY: number; ducked: boolean }>();
    let mouseStartY: number | null = null;
    let jumpHoldUntil = 0;
    let jumpReleaseTimer: ReturnType<typeof setTimeout> | null = null;

    const tapHaptic = (ms = 8) => {
      if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
        try {
          navigator.vibrate(ms);
        } catch {
          // Ignore browsers that block or disallow programmatic vibration
        }
      }
    };

    const pulseJumpPad = () => {
      if (jumpReleaseTimer !== null) {
        clearTimeout(jumpReleaseTimer);
        jumpReleaseTimer = null;
      }
      jumpHoldUntil = Date.now() + 85;
      setJumpPadActive(true);
    };

    const syncTouchPads = () => {
      const stillDucking =
        !controlsRef.current.isGameOver() &&
        (duckTouches.size > 0 || Array.from(skyTouches.values()).some((item) => item.ducked));
      controlsRef.current.setTouchDuck(stillDucking);
      setDuckPadActive(stillDucking);

      if (jumpTouches.size > 0) {
        setJumpPadActive(true);
        return;
      }

      const remaining = jumpHoldUntil - Date.now();
      if (remaining > 0) {
        if (jumpReleaseTimer === null) {
          jumpReleaseTimer = setTimeout(() => {
            jumpReleaseTimer = null;
            if (jumpTouches.size === 0) {
              setJumpPadActive(false);
            }
          }, remaining);
        }
      } else {
        if (jumpReleaseTimer !== null) {
          clearTimeout(jumpReleaseTimer);
          jumpReleaseTimer = null;
        }
        setJumpPadActive(false);
      }
    };

    const onTouchStart = (event: TouchEvent) => {
      event.preventDefault();
      for (let i = 0; i < event.changedTouches.length; i += 1) {
        const touch = event.changedTouches[i];
        const target = touch.target instanceof Element ? touch.target : null;
        if (target?.closest('[data-dino-duck-pad]')) {
          if (!controlsRef.current.isGameOver()) {
            duckTouches.add(touch.identifier);
            controlsRef.current.setTouchDuck(true);
            setDuckPadActive(true);
            tapHaptic(6);
          }
        } else if (target?.closest('[data-dino-jump-pad]')) {
          jumpTouches.add(touch.identifier);
          pulseJumpPad();
          tapHaptic(8);
          controlsRef.current.pressJump();
        } else if (stageEl) {
          skyTouches.set(touch.identifier, { startY: touch.clientY, ducked: false });
          controlsRef.current.pressJump();
        }
      }
    };

    const onTouchMove = (event: TouchEvent) => {
      event.preventDefault();
      let changed = false;
      for (let i = 0; i < event.changedTouches.length; i += 1) {
        const touch = event.changedTouches[i];
        if (jumpTouches.has(touch.identifier)) continue;

        const state = skyTouches.get(touch.identifier);
        if (state && !state.ducked && touch.clientY - state.startY > 16) {
          state.ducked = true;
          changed = true;
        }

        const under =
          typeof document !== 'undefined' ? document.elementFromPoint(touch.clientX, touch.clientY) : null;
        const overDuck = Boolean(under?.closest('[data-dino-duck-pad]'));
        if (overDuck && !controlsRef.current.isGameOver()) {
          if (!duckTouches.has(touch.identifier)) {
            duckTouches.add(touch.identifier);
            changed = true;
          }
        } else if (duckTouches.delete(touch.identifier)) {
          changed = true;
        }
      }
      if (changed) {
        syncTouchPads();
      }
    };

    const finishTouch = (event: TouchEvent) => {
      event.preventDefault();
      for (let i = 0; i < event.changedTouches.length; i += 1) {
        const id = event.changedTouches[i].identifier;
        duckTouches.delete(id);
        jumpTouches.delete(id);
        skyTouches.delete(id);
      }
      syncTouchPads();
    };

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return;
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest('[data-dino-duck-pad]')) {
        if (!controlsRef.current.isGameOver()) {
          controlsRef.current.setTouchDuck(true);
          setDuckPadActive(true);
        }
      } else if (target?.closest('[data-dino-jump-pad]')) {
        pulseJumpPad();
        controlsRef.current.pressJump();
      } else if (stageEl) {
        mouseStartY = event.clientY;
        controlsRef.current.pressJump();
      }
    };

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return;
      if (mouseStartY !== null && event.clientY - mouseStartY > 20) {
        controlsRef.current.setTouchDuck(true);
        setDuckPadActive(true);
      }
    };

    const onPointerUp = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return;
      mouseStartY = null;
      syncTouchPads();
    };

    if (deckEl) {
      deckEl.addEventListener('touchstart', onTouchStart, { passive: false });
      deckEl.addEventListener('touchmove', onTouchMove, { passive: false });
      deckEl.addEventListener('touchend', finishTouch, { passive: false });
      deckEl.addEventListener('touchcancel', finishTouch, { passive: false });
      deckEl.addEventListener('pointerdown', onPointerDown);
    }

    if (stageEl) {
      stageEl.addEventListener('touchstart', onTouchStart, { passive: false });
      stageEl.addEventListener('touchmove', onTouchMove, { passive: false });
      stageEl.addEventListener('touchend', finishTouch, { passive: false });
      stageEl.addEventListener('touchcancel', finishTouch, { passive: false });
      stageEl.addEventListener('pointerdown', onPointerDown);
      stageEl.addEventListener('pointermove', onPointerMove);
    }

    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);

    return () => {
      if (jumpReleaseTimer !== null) {
        clearTimeout(jumpReleaseTimer);
      }
      if (deckEl) {
        deckEl.removeEventListener('touchstart', onTouchStart);
        deckEl.removeEventListener('touchmove', onTouchMove);
        deckEl.removeEventListener('touchend', finishTouch);
        deckEl.removeEventListener('touchcancel', finishTouch);
        deckEl.removeEventListener('pointerdown', onPointerDown);
      }
      if (stageEl) {
        stageEl.removeEventListener('touchstart', onTouchStart);
        stageEl.removeEventListener('touchmove', onTouchMove);
        stageEl.removeEventListener('touchend', finishTouch);
        stageEl.removeEventListener('touchcancel', finishTouch);
        stageEl.removeEventListener('pointerdown', onPointerDown);
        stageEl.removeEventListener('pointermove', onPointerMove);
      }
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
      controlsRef.current.setTouchDuck(false);
      setDuckPadActive(false);
      setJumpPadActive(false);
    };
  }, [bodyHost, focusMode, mode, portalHost]);

  return (
    <div
      ref={containerRef}
      className={styles.horizonLayer}
      data-portal-dino-horizon=""
      data-dino-mode={mode}
      data-dino-state={gameState}
      data-dino-focus={focusMode ? 'true' : 'false'}
    >
      <canvas ref={canvasRef} className={styles.horizonCanvas} aria-hidden="true" />
      {mode === 'auto' ? (
        <span className={styles.autoHint} aria-hidden="true">
          点击黑边玩小恐龙
        </span>
      ) : (
        <div className={styles.horizonHud}>
          <span className={styles.hudScore} aria-live="polite">
            {hiScore > 0 ? `HI ${formatScore(hiScore)}  ` : ''}
            {formatScore(score)}
          </span>
          <button
            type="button"
            className={`${styles.hudChip}${focusMode ? ` ${styles.hudChipActive}` : ''}`}
            data-dino-focus-toggle=""
            aria-pressed={focusMode}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={handleToggleFocus}
          >
            {focusMode ? '退出全屏' : '全屏'}
          </button>
          {gameState !== 'gameover' ? (
            <button
              type="button"
              className={styles.hudChip}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={handleReturnAuto}
            >
              自动
            </button>
          ) : null}
        </div>
      )}
      {mode === 'manual' && gameState === 'gameover' ? (
        <div className={styles.gameOverOverlay} role="status" aria-live="assertive">
          <span className={styles.gameOverText}>GAME OVER</span>
          <button
            type="button"
            className={styles.hudChip}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={handleRestart}
          >
            重来
          </button>
          {!focusMode ? (
            <button
              type="button"
              className={`${styles.hudChip} ${styles.mobileGameOverFocus}`}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={handleToggleFocus}
            >
              全屏
            </button>
          ) : null}
          <button
            type="button"
            className={styles.hudChip}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={handleReturnAuto}
          >
            切回自动
          </button>
        </div>
      ) : null}
      {mode === 'manual' && focusMode ? (
        <div className={styles.focusLegend} aria-hidden="true">
          <span className={styles.focusLegendDesktop}>
            空格 / ↑ / W / 点击屏幕跳跃 · ↓ / S 下蹲 · F / Esc 退出全屏
          </span>
        </div>
      ) : null}
      {mode === 'manual' && focusMode && portalHost
        ? createPortal(
            <div ref={focusStageRef} className={styles.focusStageOverlay} data-dino-focus-stage="" />,
            portalHost
          )
        : null}
      {mode === 'manual' && bodyHost
        ? createPortal(
            <div
              ref={mobileDeckRef}
              className={styles.mobileControlDeck}
              data-dino-mobile-deck=""
              data-dino-focus={focusMode ? 'true' : 'false'}
            >
              {focusMode ? (
                <p className={styles.mobileDeckHint} aria-hidden="true">
                  点黑幕也可跳跃 · 下滑速降 · 点上方退出全屏
                </p>
              ) : null}
              <div className={styles.mobilePadGrid}>
                <div
                  role="button"
                  aria-label="按住下蹲"
                  data-dino-duck-pad=""
                  data-active={duckPadActive ? 'true' : 'false'}
                  className={styles.mobileControlPad}
                >
                  <span className={styles.mobilePadGlyph} aria-hidden="true">
                    <svg
                      viewBox="0 0 24 24"
                      className={styles.mobilePadSvg}
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.4"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M12 4.5v10.5" />
                      <path d="M7.5 10.5 12 15l4.5-4.5" />
                      <path d="M6.5 19h11" />
                    </svg>
                  </span>
                  <span className={styles.mobilePadCopy}>
                    <span className={styles.mobilePadTitle}>下蹲</span>
                    <span className={styles.mobilePadSub}>按住 · 速降</span>
                  </span>
                </div>
                <div
                  role="button"
                  aria-label={gameState === 'gameover' ? '再来一局' : '点击跳跃'}
                  data-dino-jump-pad=""
                  data-active={jumpPadActive ? 'true' : 'false'}
                  className={`${styles.mobileControlPad} ${styles.mobileControlPadPrimary}`}
                >
                  <span className={styles.mobilePadGlyph} aria-hidden="true">
                    {gameState === 'gameover' ? (
                      <svg
                        viewBox="0 0 24 24"
                        className={styles.mobilePadSvg}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.35"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3L19.5 9" />
                        <path d="M19.5 5v4h-4" />
                      </svg>
                    ) : (
                      <svg
                        viewBox="0 0 24 24"
                        className={styles.mobilePadSvg}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.4"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M12 15.5V5" />
                        <path d="M7.5 9.5 12 5l4.5 4.5" />
                        <path d="M6.5 19h11" />
                      </svg>
                    )}
                  </span>
                  <span className={styles.mobilePadCopy}>
                    <span className={styles.mobilePadTitle}>
                      {gameState === 'gameover' ? '再来一局' : '跳跃'}
                    </span>
                    <span className={styles.mobilePadSub}>
                      {gameState === 'gameover' ? '轻触重开' : '轻触起跳'}
                    </span>
                  </span>
                </div>
              </div>
            </div>,
            bodyHost
          )
        : null}
    </div>
  );
}