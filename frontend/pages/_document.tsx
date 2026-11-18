import { Head, Html, Main, NextScript } from 'next/document';
import {
  CACTUS_VARIANTS,
  DINO_ROWS,
  SPRITE_DINO_IDLE,
  SPRITE_DINO_JUMP,
  SPRITE_DINO_RUN_FRAMES,
} from '../lib/dinoSprites';

const serializeSpans = (spans: readonly { x: number; y: number; w: number; h: number }[]) =>
  spans.map((s) => [s.x, s.y, s.w, s.h]);

const DINO_BOOT_DATA = JSON.stringify({
  rows: DINO_ROWS,
  idle: serializeSpans(SPRITE_DINO_IDLE),
  jump: serializeSpans(SPRITE_DINO_JUMP),
  runFrames: SPRITE_DINO_RUN_FRAMES.map(serializeSpans),
  cacti: CACTUS_VARIANTS.map((c) => ({
    w: c.w,
    h: c.h,
    body: serializeSpans(c.frames[0].body),
    cutouts: serializeSpans(c.frames[0].cutouts),
    accents: c.frames[0].accents ? serializeSpans(c.frames[0].accents) : [],
  })),
});

// Zero-dependency pre-hydration canvas boot driver: starts drawing the bottom-left dinosaur
// and staggered cacti immediately upon HTML parse (~FCP) before deferred Next.js JS chunks finish
// downloading, then hands its timeline timestamp seamlessly over to OpeningSplash on hydration.
const SPLASH_DINO_BOOT_SCRIPT = `(function () {
  if (typeof window === 'undefined' || window.location.pathname !== '/') return;
  try {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  } catch (e) {}
  var canvas = document.querySelector('[data-splash-dino]');
  if (!canvas || !canvas.getContext) return;
  var ctx;
  try {
    ctx = canvas.getContext('2d');
  } catch (e) {
    return;
  }
  if (!ctx) return;

  document.documentElement.dataset.splashState = 'playing';

  var DATA = ${DINO_BOOT_DATA};
  var startPerf = (window.performance && performance.now) ? performance.now() : Date.now();
  var rafId = 0;

  var state = {
    active: true,
    startPerf: startPerf,
    stop: function () {
      state.active = false;
      if (rafId && window.cancelAnimationFrame) {
        window.cancelAnimationFrame(rafId);
        rafId = 0;
      }
      window.removeEventListener('resize', onResize);
    }
  };
  window.__studyhubSplashBoot = state;

  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function rrect(c, x, y, w, h, r) {
    if (w <= 0 || h <= 0) return;
    r = Math.max(0, Math.min(r, w * 0.5, h * 0.5));
    if (r <= 0.05) { c.rect(x, y, w, h); return; }
    c.moveTo(x + r, y);
    c.lineTo(x + w - r, y);
    c.quadraticCurveTo(x + w, y, x + w, y + r);
    c.lineTo(x + w, y + h - r);
    c.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    c.lineTo(x + r, y + h);
    c.quadraticCurveTo(x, y + h, x, y + h - r);
    c.lineTo(x, y + r);
    c.quadraticCurveTo(x, y, x + r, y);
    c.closePath();
  }
  function drawSprite(c, spans, ox, oy, px, radScale) {
    var rad = (radScale || 0.42) * px;
    c.beginPath();
    for (var i = 0; i < spans.length; i++) {
      var s = spans[i];
      rrect(c, ox + s[0] * px, oy + s[1] * px, s[2] * px, s[3] * px, rad);
    }
    c.fill();
  }
  function drawCrisp(c, spans, ox, oy, px, pad) {
    c.beginPath();
    for (var i = 0; i < spans.length; i++) {
      var s = spans[i];
      c.rect(ox + s[0] * px - pad, oy + s[1] * px - pad, s[2] * px + pad * 2, s[3] * px + pad * 2);
    }
    c.fill();
  }
  function drawObstacle(c, spec, x, y, px) {
    c.fillStyle = '#ffffff';
    drawCrisp(c, spec.body, x, y, px, 0.015 * px);
    if (spec.cutouts && spec.cutouts.length) {
      c.fillStyle = '#1a1c20';
      drawCrisp(c, spec.cutouts, x, y, px, 0);
    }
    if (spec.accents && spec.accents.length) {
      c.fillStyle = '#ef4444';
      drawCrisp(c, spec.accents, x, y, px, 0);
    }
    c.fillStyle = '#ffffff';
  }

  var vw = 320, canvasW = 320, canvasH = 320, startPx = 5.4, startX = 96, trackSpd = 118, splashCacti = [];
  function sync() {
    vw = Math.max(320, window.innerWidth || 320);
    var rect = canvas.getBoundingClientRect();
    canvasW = Math.max(320, rect.width || vw);
    canvasH = Math.max(320, rect.height || window.innerHeight || 320);
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var tw = Math.round(canvasW * dpr), th = Math.round(canvasH * dpr);
    if (canvas.width !== tw || canvas.height !== th) {
      canvas.width = tw;
      canvas.height = th;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    startPx = vw <= 768 ? 3.9 : clamp(vw * 0.0044, 5.4, 6.8);
    startX = vw <= 768 ? Math.max(36, Math.round(canvasW * 0.1)) : Math.max(84, Math.round(canvasW * 0.12));
    trackSpd = vw <= 768 ? 68 : 118;
    splashCacti = vw <= 768
      ? [{ xRatio: 0.78, vi: 0, d: 90 }, { xRatio: 1.18, vi: 4, d: 180 }]
      : [
          { xRatio: 0.56, vi: 0, d: 80 },
          { xRatio: 0.75, vi: 4, d: 150 },
          { xRatio: 0.93, vi: 1, d: 220 },
          { xRatio: 1.12, vi: 5, d: 290 }
        ];
  }
  function onResize() { try { sync(); } catch (e) {} }
  window.addEventListener('resize', onResize, { passive: true });

  function render(now) {
    if (!state.active) return;
    try {
      ctx.clearRect(0, 0, canvasW, canvasH);
      var elapsed = Math.max(0, now - startPerf);
      var popU = clamp(elapsed / 560, 0, 1);
      var popEase = popU <= 0 ? 0 : popU >= 1 ? 1 : 1 - Math.exp(-7.2 * popU) * Math.cos(8.5 * popU);
      var emergeOffset = (1 - popEase) * (DATA.rows * startPx + 16);
      var squashY = (popU > 0.25 && popU < 0.72) ? 1 - Math.sin(((popU - 0.25) / 0.47) * Math.PI) * 0.08 : 1;

      var cPx = startPx * 0.72;
      var sec = elapsed / 1000;
      ctx.save();
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.rect(0, 0, canvasW, canvasH + 1);
      ctx.clip();
      for (var i = 0; i < splashCacti.length; i++) {
        var c = splashCacti[i];
        var cX = canvasW * c.xRatio - sec * trackSpd;
        var spec = DATA.cacti[c.vi];
        var cu = clamp((elapsed - c.d) / 520, 0, 1);
        if (cu <= 0) continue;
        var cEase = 1 - Math.pow(1 - cu, 3.6);
        var cH = spec.h * cPx;
        if (cX + spec.w * cPx < startX + 26 * startPx || cX > canvasW + 40) continue;
        drawObstacle(ctx, spec, cX, canvasH + 0.6 - cH + (1 - cEase) * (cH + 14), cPx);
      }
      ctx.restore();

      var strideIdx = Math.floor(elapsed / 78) % 4;
      var sprite = emergeOffset < -2 ? DATA.jump : DATA.runFrames[strideIdx];
      var dinoBottom = canvasH + 0.6 + emergeOffset;
      var dinoTop = dinoBottom - DATA.rows * startPx;
      var blinking = (elapsed % 3200) < 110 && !(emergeOffset < -2);

      ctx.save();
      if (Math.abs(squashY - 1) > 0.004) {
        var sx = 1 / Math.sqrt(squashY);
        ctx.translate(startX + 10 * startPx, dinoBottom);
        ctx.scale(sx, squashY);
        ctx.translate(-(startX + 10 * startPx), -dinoBottom);
      }
      ctx.fillStyle = '#ffffff';
      drawSprite(ctx, sprite, startX, dinoTop, startPx);
      if (!blinking) {
        ctx.fillStyle = '#1a1c20';
        ctx.beginPath();
        rrect(ctx, startX + 11.0 * startPx, dinoTop + 2.0 * startPx, 1.15 * startPx, 1.15 * startPx, 0.35 * startPx);
        ctx.fill();
      }
      ctx.restore();

      if (window.requestAnimationFrame) {
        rafId = window.requestAnimationFrame(render);
      }
    } catch (e) {
      state.stop();
    }
  }

  try {
    sync();
    render(startPerf);
  } catch (e) {
    state.stop();
  }
})();`;

export default function Document() {
  return (
    <Html lang="zh-CN">
      <Head />
      <body>
        <Main />
        <script dangerouslySetInnerHTML={{ __html: SPLASH_DINO_BOOT_SCRIPT }} />
        <NextScript />
      </body>
    </Html>
  );
}
