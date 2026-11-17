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
  PORTAL_CANOPY_CENTER_Y,
  PORTAL_CANOPY_VIEWBOX_HEIGHT,
  PORTAL_CANOPY_VIEWBOX_WIDTH,
} from '../lib/portalCanopy';
import { STUDYHUB_WORDMARK_GLYPHS, STUDYHUB_WORDMARK_VIEWBOX } from '../lib/studyhubWordmark';
import styles from '../styles/OpeningSplash.module.css';

export const REPLAY_SPLASH_EVENT = 'studyhub:replay-splash';

// Staggered vector trace -> liquid energy-crest bottom-up fill -> specular glint within 1.72s.
const TRACE_BASE_DELAY_MS = 60;
const TRACE_STEP_MS = 54;
const FILL_BASE_DELAY_MS = 480;
const FILL_STEP_MS = 54;

// Intro stays completely quiet through 1720ms; then the dock releases with calibrated prism facets,
// delicate dual shockwaves, crisp upper-sky star-streaks, and subtle chromatic split (<= 2.7s).
const DOCK_DELAY_MS = 1720;
// A click, or a late start of the script, still leaves this much time before the dock.
const MIN_DOCK_DELAY_MS = 120;
// The lockup travels to its place on the page in this time, and the prism transition resolves cleanly.
const DOCK_TRAVEL_MS = 840;
// The splash leaves one beat after the lockup has landed.
const DOCK_SETTLE_MS = 50;
// Where the lockup does not land on the page, the white surface fades out in this time.
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
  canopyVars?: Record<string, string>;
  horizonY?: number;
  startCx?: number;
  startCy?: number;
  targetCx?: number;
  targetCy?: number;
}

interface PrismFacet {
  cx: number;
  cy: number;
  pts: number[];
  vx: number;
  vy0: number;
  rotVel: number;
  tiltSpeed: number;
  stagger: number;
  rimAlpha: number;
  shadeTint: string;
}

interface FaultEdge {
  ax: number;
  ay: number;
  bx: number;
  by: number;
  distNorm: number;
}

interface WarpStreak {
  angle: number;
  speed: number;
  zInit: number;
  tint: string;
  weight: number;
}

interface BlastSpark {
  x0: number;
  y0: number;
  vx: number;
  vy: number;
  delay: number;
  life: number;
  len: number;
  tint: string;
}

interface PrismWarpScene {
  vw: number;
  vh: number;
  horizonY: number;
  startCx: number;
  startCy: number;
  targetCx: number;
  targetCy: number;
  facets: PrismFacet[];
  edges: FaultEdge[];
  streaks: WarpStreak[];
  sparks: BlastSpark[];
}

const REST_DOCK: SplashDock = { transform: REST_TRANSFORM, onHero: false };

const FACET_SHADES = ['#0d0f14', '#151924', '#1d2434'] as const;

const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);
const smoothstep = (t: number) => t * t * (3 - 2 * t);
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

const mulberry32 = (seed: number) => {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

const drawUniformEllipseStroke = (
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  rx: number,
  ry: number
) => {
  if (rx <= 0.5 || ry <= 0.5) return;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(rx, ry);
  ctx.beginPath();
  ctx.arc(0, 0, 1, 0, Math.PI * 2);
  ctx.restore();
  ctx.stroke();
};

const buildPrismWarpScene = (
  vw: number,
  vh: number,
  horizonY: number,
  startCx: number,
  startCy: number,
  targetCx: number,
  targetCy: number
): PrismWarpScene => {
  const rand = mulberry32((Math.round(vw) * 73856093) ^ (Math.round(vh) * 19349663) ^ 0x20261117);
  const floorTop = Math.floor(horizonY) - 1;
  const floorBottom = vh + 28;
  const floorH = Math.max(120, floorBottom - floorTop);
  const cols = vw <= 768 ? 4 : 6;
  const rows = 2;
  const leftEdge = -20;
  const rightEdge = vw + 20;
  const totalW = rightEdge - leftEdge;
  const cellW = totalW / cols;

  // Balanced medium-scale geometric lattice (~20 desktop, ~13 mobile).
  const grid: { x: number; y: number }[][] = [];
  for (let r = 0; r <= rows; r += 1) {
    const rowPts: { x: number; y: number }[] = [];
    const baseFracY = r === 0 ? 0 : r === 1 ? 0.44 : 1;
    for (let c = 0; c <= cols; c += 1) {
      let x = leftEdge + c * cellW;
      let y = floorTop + baseFracY * floorH;
      if (c > 0 && c < cols) {
        const dxRange = r === 0 ? cellW * 0.12 : r === 1 ? cellW * 0.24 : cellW * 0.18;
        x += (rand() * 2 - 1) * dxRange;
      }
      if (r === 1) {
        y += (rand() * 2 - 1) * floorH * 0.075;
      }
      rowPts.push({ x, y });
    }
    grid.push(rowPts);
  }

  const epiX = vw * 0.5;
  const epiY = floorTop;
  const maxDiag = Math.max(220, Math.hypot(vw * 0.54, floorH));
  const facets: PrismFacet[] = [];
  const edgeMap = new Map<string, FaultEdge>();

  const registerInteriorEdge = (
    rA: number,
    cA: number,
    rB: number,
    cB: number,
    pA: { x: number; y: number },
    pB: { x: number; y: number }
  ) => {
    if (
      (rA === 0 && rB === 0) ||
      (rA === rows && rB === rows) ||
      (cA === 0 && cB === 0) ||
      (cA === cols && cB === cols)
    ) {
      return;
    }
    const kA = `${rA}:${cA}`;
    const kB = `${rB}:${cB}`;
    const key = kA < kB ? `${kA}|${kB}` : `${kB}|${kA}`;
    if (edgeMap.has(key)) return;
    const midX = (pA.x + pB.x) * 0.5;
    const midY = (pA.y + pB.y) * 0.5;
    const distNorm = clamp(Math.hypot(midX - epiX, (midY - epiY) * 1.1) / maxDiag, 0, 1);
    edgeMap.set(key, { ax: pA.x, ay: pA.y, bx: pB.x, by: pB.y, distNorm });
  };

  const pushFacet = (
    verts: readonly { x: number; y: number }[],
    coords: readonly { r: number; c: number }[]
  ) => {
    const n = verts.length;
    let cx = 0;
    let cy = 0;
    for (let i = 0; i < n; i += 1) {
      cx += verts[i].x;
      cy += verts[i].y;
      const next = (i + 1) % n;
      registerInteriorEdge(coords[i].r, coords[i].c, coords[next].r, coords[next].c, verts[i], verts[next]);
    }
    cx /= n;
    cy /= n;

    const pts: number[] = [];
    for (let i = 0; i < n; i += 1) {
      pts.push(verts[i].x - cx, verts[i].y - cy);
    }

    const distNorm = clamp(Math.hypot(cx - epiX, (cy - epiY) * 1.1) / maxDiag, 0, 1);
    const signX = cx < epiX - 10 ? -1 : cx > epiX + 10 ? 1 : rand() > 0.5 ? 1 : -1;
    const relSpanX = clamp((cx - epiX) / Math.max(140, vw * 0.5), -1, 1);
    const radialMag = 42 + rand() * 58 + Math.abs(relSpanX) * 55;
    const vx = clamp(signX * radialMag, -155, 155);
    const vy0 = cy < floorTop + floorH * 0.35 ? -28 + rand() * 24 : rand() * 24;

    facets.push({
      cx,
      cy,
      pts,
      vx,
      vy0,
      rotVel: signX * (0.18 + rand() * 0.44),
      tiltSpeed: 1.1 + rand() * 1.0,
      stagger: distNorm * 0.14 + rand() * 0.025,
      rimAlpha: 0.32 + rand() * 0.22,
      shadeTint: FACET_SHADES[facets.length % FACET_SHADES.length],
    });
  };

  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      const tl = grid[r][c];
      const tr = grid[r][c + 1];
      const br = grid[r + 1][c + 1];
      const bl = grid[r + 1][c];
      const cTl = { r, c };
      const cTr = { r, c: c + 1 };
      const cBr = { r: r + 1, c: c + 1 };
      const cBl = { r: r + 1, c };

      // Mix ~65% clean angled triangles and ~35% broad quads (~20 desktop, ~13 mobile).
      if (rand() > 0.35) {
        if (rand() > 0.45) {
          pushFacet([tl, tr, br], [cTl, cTr, cBr]);
          pushFacet([tl, br, bl], [cTl, cBr, cBl]);
        } else {
          pushFacet([tl, tr, bl], [cTl, cTr, cBl]);
          pushFacet([tr, br, bl], [cTr, cBr, cBl]);
        }
      } else {
        pushFacet([tl, tr, br, bl], [cTl, cTr, cBr, cBl]);
      }
    }
  }

  // Restrained 3D star-streaks in the upper canopy.
  const streakCount = vw <= 768 ? 24 : 38;
  const streakTints = ['rgba(255,255,255,0.88)', 'rgba(186,230,253,0.82)', 'rgba(199,210,254,0.78)'];
  const streaks: WarpStreak[] = [];
  for (let i = 0; i < streakCount; i += 1) {
    streaks.push({
      angle: rand() * Math.PI * 2,
      speed: 1.2 + rand() * 1.7,
      zInit: 0.32 + rand() * 1.05,
      tint: streakTints[i % streakTints.length],
      weight: 0.65 + rand() * 0.6,
    });
  }

  // Refined micro-sparks skimming outward along the central horizon cleavage.
  const sparkCount = vw <= 768 ? 14 : 22;
  const sparkTints = ['#ffffff', '#bae6fd'];
  const sparks: BlastSpark[] = [];
  for (let i = 0; i < sparkCount; i += 1) {
    const spreadX = (rand() * 2 - 1) * vw * 0.36;
    const vx = (spreadX >= 0 ? 1 : -1) * (130 + rand() * 290) + (rand() - 0.5) * 140;
    const vy = (rand() > 0.45 ? -1 : 1) * (70 + rand() * 210);
    sparks.push({
      x0: vw * 0.5 + spreadX,
      y0: horizonY + (rand() - 0.5) * 10,
      vx,
      vy,
      delay: 0.03 + rand() * 0.12,
      life: 0.28 + rand() * 0.24,
      len: 8 + rand() * 8,
      tint: sparkTints[i % sparkTints.length],
    });
  }

  return {
    vw,
    vh,
    horizonY,
    startCx,
    startCy,
    targetCx,
    targetCy,
    facets,
    edges: Array.from(edgeMap.values()),
    streaks,
    sparks,
  };
};

const drawPrismWarpFrame = (ctx: CanvasRenderingContext2D, scene: PrismWarpScene, pRaw: number) => {
  const { vw, vh, horizonY, startCx, startCy, targetCx, targetCy, facets, edges, streaks, sparks } = scene;
  const p = clamp(pRaw, 0, 1);
  ctx.clearRect(0, 0, vw, vh);

  // ---------------------------------------------------------------------------
  // 1. Upper-Sky 3D WarpStreaks (restrained opacity & clear StudyHub halo)
  // ---------------------------------------------------------------------------
  const warpAlpha = (p < 0.12 ? clamp(p / 0.08, 0, 1) : clamp(1 - (p - 0.12) / 0.66, 0, 1)) * 0.52;
  if (p >= 0.02 && p <= 0.8 && warpAlpha > 0.008) {
    const trackEase = 1 - Math.pow(1 - clamp(p / 0.82, 0, 1), 3);
    const vanishX = startCx + (targetCx - startCx) * trackEase;
    const vanishY = startCy + (targetCy - startCy) * trackEase;
    const focal = Math.max(vw, vh) * 0.4;

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, vw, horizonY);
    ctx.clip();

    ctx.globalAlpha = warpAlpha;
    for (let i = 0; i < streaks.length; i += 1) {
      const s = streaks[i];
      const rawZ = s.zInit - p * s.speed * 0.95;
      const zFront = (((rawZ % 1.15) + 1.15) % 1.15) + 0.06;
      const zTail = zFront + 0.14 + 0.18 * (warpAlpha / 0.52);
      const r1 = focal * (0.18 / zFront);
      const r0 = focal * (0.18 / zTail);
      if (r0 < 56) continue;
      const cosA = Math.cos(s.angle);
      const sinA = Math.sin(s.angle);
      ctx.strokeStyle = s.tint;
      ctx.lineWidth = s.weight * clamp(1.15 - zFront * 0.45, 0.5, 1.25);
      ctx.beginPath();
      ctx.moveTo(vanishX + cosA * r0, vanishY + sinA * r0);
      ctx.lineTo(vanishX + cosA * r1, vanishY + sinA * r1);
      ctx.stroke();
    }
    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // 2. Medium-Scale Sculpted Prism Facets parting calmly outward & downward
  // ---------------------------------------------------------------------------
  for (let i = 0; i < facets.length; i += 1) {
    const pl = facets[i];
    const t = clamp((p - 0.07 - pl.stagger) / 0.72, 0, 1);
    if (t >= 0.995) continue;

    const alpha = t < 0.52 ? 1 : 1 - smoothstep((t - 0.52) / 0.48);
    if (alpha <= 0.008) continue;

    const dx = pl.vx * easeOutCubic(t);
    const dy = pl.vy0 * t + (vh * 0.58 + 260) * t * t;
    const rot = pl.rotVel * easeOutCubic(t);
    const tilt = Math.cos(pl.tiltSpeed * t);
    const scale = 1 - 0.22 * t;
    const scaleY = t <= 0.005 ? 1 : scale * Math.max(0.22, Math.abs(tilt));

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.translate(pl.cx + dx, pl.cy + dy);
    ctx.rotate(rot);
    ctx.scale(scale, scaleY);

    ctx.beginPath();
    ctx.moveTo(pl.pts[0], pl.pts[1]);
    for (let k = 2; k < pl.pts.length; k += 2) {
      ctx.lineTo(pl.pts[k], pl.pts[k + 1]);
    }
    ctx.closePath();

    if (t <= 0.005) {
      ctx.fillStyle = '#09090b';
      ctx.fill();
      ctx.strokeStyle = '#09090b';
      ctx.lineWidth = 0.8;
      ctx.stroke();
    } else {
      ctx.fillStyle = Math.abs(tilt) < 0.55 ? pl.shadeTint : t > 0.1 ? '#0d0f14' : '#09090b';
      ctx.fill();
      const rimGlow = clamp((1 - t * 0.8) * pl.rimAlpha, 0, 0.52);
      if (rimGlow > 0.01) {
        ctx.strokeStyle = `rgba(186, 230, 253, ${rimGlow.toFixed(3)})`;
        ctx.lineWidth = 1.05;
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // 3. Fault-Line Cleavage Ignition + Ice-White Horizon Laser Seam
  // ---------------------------------------------------------------------------
  if (p < 0.21) {
    const front = clamp(p / 0.09, 0, 1.15);
    const fade = p < 0.09 ? 1 : clamp(1 - (p - 0.09) / 0.11, 0, 1);
    if (fade > 0.01) {
      ctx.save();
      ctx.lineCap = 'round';
      for (let i = 0; i < edges.length; i += 1) {
        const e = edges[i];
        if (e.distNorm > front) continue;
        const glow = clamp(1 - (front - e.distNorm) * 1.15, 0.35, 1) * fade;

        ctx.strokeStyle = `rgba(125, 211, 252, ${(glow * 0.36).toFixed(3)})`;
        ctx.lineWidth = 3.2;
        ctx.beginPath();
        ctx.moveTo(e.ax, e.ay);
        ctx.lineTo(e.bx, e.by);
        ctx.stroke();

        ctx.strokeStyle = `rgba(248, 250, 252, ${(glow * 0.78).toFixed(3)})`;
        ctx.lineWidth = 1.15;
        ctx.beginPath();
        ctx.moveTo(e.ax, e.ay);
        ctx.lineTo(e.bx, e.by);
        ctx.stroke();
      }
      ctx.restore();
    }
  }

  if (p < 0.62) {
    const railFade = p < 0.14 ? clamp(p / 0.06, 0.3, 1) : clamp(1 - (p - 0.14) / 0.48, 0, 1);
    if (railFade > 0.01) {
      const spreadHalf = vw * 0.52 * Math.min(1, 0.28 + p * 6.0);
      const leftX = vw * 0.5 - spreadHalf;
      const rightX = vw * 0.5 + spreadHalf;
      const coreMax = 0.82 * railFade;
      const grad = ctx.createLinearGradient(leftX, 0, rightX, 0);
      grad.addColorStop(0, 'rgba(125, 211, 252, 0)');
      grad.addColorStop(0.16, `rgba(186, 230, 253, ${(coreMax * 0.72).toFixed(3)})`);
      grad.addColorStop(0.5, `rgba(255, 255, 255, ${coreMax.toFixed(3)})`);
      grad.addColorStop(0.84, `rgba(186, 230, 253, ${(coreMax * 0.72).toFixed(3)})`);
      grad.addColorStop(1, 'rgba(125, 211, 252, 0)');

      ctx.save();
      ctx.strokeStyle = `rgba(125, 211, 252, ${(railFade * 0.22).toFixed(3)})`;
      ctx.lineWidth = 5;
      ctx.beginPath();
      ctx.moveTo(leftX, horizonY);
      ctx.lineTo(rightX, horizonY);
      ctx.stroke();

      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(leftX, horizonY);
      ctx.lineTo(rightX, horizonY);
      ctx.stroke();
      ctx.restore();
    }
  }

  // ---------------------------------------------------------------------------
  // 4. Delicate Dual Shockwaves + Compact Ignition Flash + Refined BlastSparks
  // ---------------------------------------------------------------------------
  if (p > 0.02 && p < 0.5) {
    const waveU = clamp((p - 0.02) / 0.48, 0, 1);
    const ease = 1 - Math.pow(1 - waveU, 3);
    const maxR = Math.hypot(vw, vh) * 0.52;

    ctx.save();
    ctx.strokeStyle = `rgba(224, 242, 254, ${((1 - waveU) * 0.34).toFixed(3)})`;
    ctx.lineWidth = 1.6 * (1 - waveU) + 0.4;
    ctx.beginPath();
    ctx.arc(startCx, startCy, 16 + maxR * ease, 0, Math.PI * 2);
    ctx.stroke();

    if (waveU > 0.08) {
      const echoU = clamp((waveU - 0.08) / 0.92, 0, 1);
      const echoEase = 1 - Math.pow(1 - echoU, 3);
      ctx.strokeStyle = `rgba(165, 180, 252, ${((1 - echoU) * 0.24).toFixed(3)})`;
      ctx.lineWidth = 1.1 * (1 - echoU) + 0.35;
      ctx.beginPath();
      ctx.arc(startCx, startCy, 10 + maxR * 0.84 * echoEase, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  if (p > 0.03 && p < 0.54) {
    const hWaveU = clamp((p - 0.03) / 0.51, 0, 1);
    const hEase = 1 - Math.pow(1 - hWaveU, 2.8);
    ctx.save();
    ctx.strokeStyle = `rgba(186, 230, 253, ${((1 - hWaveU) * 0.38).toFixed(3)})`;
    ctx.lineWidth = 1.6 * (1 - hWaveU) + 0.4;
    drawUniformEllipseStroke(ctx, vw * 0.5, horizonY, 36 + vw * 0.58 * hEase, 6 + 44 * hEase);
    ctx.restore();
  }

  if (p > 0.02 && p < 0.28) {
    const flashAlpha = Math.sin(clamp((p - 0.02) / 0.26, 0, 1) * Math.PI);
    const r = vw <= 768 ? 68 : 104;
    const radGrad = ctx.createRadialGradient(vw * 0.5, horizonY, 0, vw * 0.5, horizonY, r);
    radGrad.addColorStop(0, `rgba(255, 255, 255, ${(flashAlpha * 0.46).toFixed(3)})`);
    radGrad.addColorStop(0.38, `rgba(186, 230, 253, ${(flashAlpha * 0.22).toFixed(3)})`);
    radGrad.addColorStop(1, 'rgba(9, 9, 11, 0)');
    ctx.fillStyle = radGrad;
    ctx.fillRect(vw * 0.5 - r, horizonY - r, r * 2, r * 2);
  }

  ctx.save();
  ctx.lineCap = 'round';
  for (let i = 0; i < sparks.length; i += 1) {
    const sp = sparks[i];
    if (p < sp.delay || p > sp.delay + sp.life) continue;
    const u = (p - sp.delay) / sp.life;
    const dragT = 1 - Math.pow(1 - u, 1.7);
    const sx = sp.x0 + sp.vx * dragT * 0.48;
    const sy = sp.y0 + sp.vy * dragT * 0.48 + 320 * u * u;
    const speedLen = Math.max(4, Math.hypot(sp.vx, sp.vy));
    const ux = sp.vx / speedLen;
    const uy = sp.vy / speedLen;
    const tailLen = sp.len * (1 - u * 0.55);

    ctx.globalAlpha = clamp((1 - u) * 0.68, 0, 0.68);
    ctx.strokeStyle = sp.tint;
    ctx.lineWidth = 1.15 * (1 - u * 0.5);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(sx - ux * tailLen, sy - uy * tailLen);
    ctx.stroke();
  }
  ctx.restore();
};

const measureHorizonY = (heroRect?: DOMRect): number => {
  const waveRect = document.querySelector<SVGElement>('[data-portal-canopy-wave]')?.getBoundingClientRect();
  const waveHeight = waveRect && waveRect.height > 0 ? waveRect.height : PORTAL_CANOPY_VIEWBOX_HEIGHT;
  const waveScaleY = waveHeight / PORTAL_CANOPY_VIEWBOX_HEIGHT;
  const waveTop = waveRect
    ? waveRect.top
    : heroRect
      ? heroRect.bottom - (waveHeight - 172)
      : -200;
  return waveTop + PORTAL_CANOPY_CENTER_Y * waveScaleY;
};

const measureCanopyVars = (): Record<string, string> | undefined => {
  const heroRect = document.querySelector<HTMLElement>('[data-splash-target]')?.getBoundingClientRect();
  const waveRect = document.querySelector<SVGElement>('[data-portal-canopy-wave]')?.getBoundingClientRect();
  if (!heroRect && !waveRect) return undefined;
  const waveLeft = waveRect ? waveRect.left : 0;
  const waveHeight =
    waveRect && waveRect.height > 0 ? waveRect.height : PORTAL_CANOPY_VIEWBOX_HEIGHT;
  const waveScaleY = waveHeight / PORTAL_CANOPY_VIEWBOX_HEIGHT;
  const waveTop = waveRect
    ? waveRect.top
    : heroRect
      ? heroRect.bottom - (waveHeight - 172)
      : -200;
  const waveWidth = waveRect && waveRect.width > 0 ? waveRect.width : window.innerWidth;
  const horizonY = waveTop + PORTAL_CANOPY_CENTER_Y * waveScaleY;
  return {
    '--canopy-left': `${waveLeft.toFixed(2)}px`,
    '--canopy-top': `${waveTop.toFixed(2)}px`,
    '--canopy-width': `${waveWidth.toFixed(2)}px`,
    '--canopy-height': `${waveHeight.toFixed(2)}px`,
    '--canopy-horizon-y': `${horizonY.toFixed(2)}px`,
  };
};

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
  const stageRef = useRef<HTMLDivElement>(null);
  const fxCanvasRef = useRef<HTMLCanvasElement>(null);
  const dockStartPerfRef = useRef<number>(0);
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
      const canopyVars = measureCanopyVars();
      const horizonY = measureHorizonY(heroRect);
      return {
        transform: `translate3d(${dx.toFixed(2)}px, ${dy.toFixed(2)}px, 0) scale(1)`, onHero: true,
        canopyVars,
        horizonY,
        startCx,
        startCy,
        targetCx,
        targetCy,
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
    dockStartPerfRef.current = performance.now();
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
      const fcpElapsed = fromServerMarkup ? timeSinceFirstPaint() : 0;
      const dockDelay = fromServerMarkup
        ? Math.max(MIN_DOCK_DELAY_MS, DOCK_DELAY_MS - fcpElapsed)
        : DOCK_DELAY_MS;
      const initialCanopyVars = measureCanopyVars();
      if (fromServerMarkup) {
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

  // 60fps HiDPI Canvas 2D 1.0 transition engine: quiet during intro, then calibrated prism cleavage,
  // upper-sky 3D star-streaks, dual subtle shockwaves, compact ignition bloom, and sparks during dock.
  useIsomorphicLayoutEffect(() => {
    const canvas = fxCanvasRef.current;
    if (!canvas) return undefined;
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

    const syncFxCanvasSize = () => {
      vw = Math.max(320, window.innerWidth);
      vh = Math.max(320, window.innerHeight);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const targetW = Math.round(vw * dpr);
      const targetH = Math.round(vh * dpr);
      if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
      }
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    try {
      syncFxCanvasSize();
      if (phase !== 'docking' || !dock.onHero) {
        context.clearRect(0, 0, vw, vh);
        return undefined;
      }
    } catch {
      return undefined;
    }

    let rafId = 0;
    let scene: PrismWarpScene;
    try {
      const heroRect = document.querySelector<HTMLElement>('[data-splash-target]')?.getBoundingClientRect();
      const horizonY = dock.horizonY ?? measureHorizonY(heroRect);
      const startCx = dock.startCx ?? vw * 0.5;
      const startCy = dock.startCy ?? vh * 0.5;
      const targetCx = dock.targetCx ?? startCx;
      const targetCy = dock.targetCy ?? startCy - 120;
      scene = buildPrismWarpScene(vw, vh, horizonY, startCx, startCy, targetCx, targetCy);
      // Paint solid dark facets + initial fault seams synchronously before first composite frame.
      drawPrismWarpFrame(context, scene, 0.005);
    } catch {
      return undefined;
    }

    const onResize = () => {
      try {
        syncFxCanvasSize();
      } catch {
        // Ignore transient resize errors.
      }
    };
    window.addEventListener('resize', onResize, { passive: true });

    const tick = (now: number) => {
      try {
        const p = (now - dockStartPerfRef.current) / DOCK_TRAVEL_MS;
        drawPrismWarpFrame(context, scene, p);
        if (p < 1.04) {
          rafId = window.requestAnimationFrame(tick);
        } else {
          context.clearRect(0, 0, vw, vh);
          rafId = 0;
        }
      } catch {
        rafId = 0;
      }
    };

    rafId = window.requestAnimationFrame(tick);
    return () => {
      window.removeEventListener('resize', onResize);
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
    };
  }, [phase, playKey, dock.onHero, dock.horizonY, dock.startCx, dock.startCy, dock.targetCx, dock.targetCy]);

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
          bottom-up liquid energy crest fill, metallic glint, and balanced prism-warp dock. */}
      <div className={styles.backdrop}>
        <div className={styles.gridGlow} />
      </div>
      <div className={styles.wipe} />
      {showTaijiWipe ? (
        <div className={styles.canopyStage} data-splash-taiji="" aria-hidden="true">
          <div className={styles.canopyUpperFill} />
          <svg
            className={styles.taijiWave}
            viewBox={`0 0 ${PORTAL_CANOPY_VIEWBOX_WIDTH} ${PORTAL_CANOPY_VIEWBOX_HEIGHT}`}
            preserveAspectRatio="none"
            focusable="false"
          >
            <defs>
              <radialGradient id="splash-aurora-left" cx="26%" cy="88%" r="24%">
                <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.11" />
                <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
              </radialGradient>
              <radialGradient id="splash-aurora-mid" cx="50%" cy="88%" r="24%">
                <stop offset="0%" stopColor="#818cf8" stopOpacity="0.1" />
                <stop offset="100%" stopColor="#818cf8" stopOpacity="0" />
              </radialGradient>
              <radialGradient id="splash-aurora-right" cx="74%" cy="88%" r="24%">
                <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.08" />
                <stop offset="65%" stopColor="#f59e0b" stopOpacity="0.03" />
                <stop offset="100%" stopColor="#2dd4bf" stopOpacity="0" />
              </radialGradient>
            </defs>
            <g>
              <rect width={PORTAL_CANOPY_VIEWBOX_WIDTH} height={PORTAL_CANOPY_VIEWBOX_HEIGHT} fill="#1a1c20" />
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
          </svg>
        </div>
      ) : null}
      {showTaijiWipe ? <div className={styles.whiteLowerStage} aria-hidden="true" /> : null}
      {showTaijiWipe ? (
        <canvas ref={fxCanvasRef} className={styles.fxCanvas} data-splash-fx="" aria-hidden="true" />
      ) : null}
      <div
        ref={stageRef}
        className={`${styles.stage}${isDocking && !dock.onHero ? ` ${styles.stageLeaves}` : ''}`}
        style={isDocking ? { transform: dock.transform } : undefined}
      >
        <div className={styles.lockup}>
          <span className={styles.horizonBeam} aria-hidden="true" />
          <svg
            className={`${styles.wordmarkSvg} ${styles.prismGhostCyan}`}
            viewBox={STUDYHUB_WORDMARK_VIEWBOX}
            aria-hidden="true"
            focusable="false"
          >
            {STUDYHUB_WORDMARK_GLYPHS.map((glyph) => (
              <path key={`cyan-${glyph.id}`} d={glyph.d} fill="#7dd3fc" />
            ))}
          </svg>
          <svg
            className={`${styles.wordmarkSvg} ${styles.prismGhostViolet}`}
            viewBox={STUDYHUB_WORDMARK_VIEWBOX}
            aria-hidden="true"
            focusable="false"
          >
            {STUDYHUB_WORDMARK_GLYPHS.map((glyph) => (
              <path key={`violet-${glyph.id}`} d={glyph.d} fill="#a5b4fc" />
            ))}
          </svg>
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
