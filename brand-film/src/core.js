// Core helpers for the StudyHub brand film.
// Everything here is pure and deterministic: no Date, no Math.random, no CSS animation.

// Portrait frame size (the landscape cut uses its own constants in src/landscape/layout.js).
export const W = 1080;
export const H = 1920;
export const FPS = 30;
export const BPM = 120;
export const BEAT = 60 / BPM; // 0.5 s

// ---------- Palette (from frontend/styles/globals.css and the bot icon) ----------
export const C = {
  bot: '#080b12',        // studyhub-app.svg background
  ink: '#0f172a',        // --brand-secondary / --text-color
  muted: '#475569',      // --text-muted
  meta: '#64748b',       // card meta text
  blue: '#2563eb',       // --brand-primary
  blueDeep: '#1d4ed8',   // --brand-primary-strong
  blueSoft: '#dbe6fe',   // tint of brand-primary for UI fills
  indigo: '#eef2ff',     // --bg-gradient mid stop
  bg: '#f4f6fb',         // --bg-soft
  paper: '#ffffff',
  line: '#e2e8f0',       // card border
  lineStrong: '#cbd5f5', // --border-strong
  teal: '#2a9d8f',       // editorial hero accent
  amber: '#fbbf24',      // bot graduation-cap tassel
  violet: '#7c3aed',     // --brand-accent
  green: '#059669',      // --success, "免费"
  eye: '#ffffff',
};

export const FONT_CN = "'Noto Sans SC', sans-serif";
export const FONT_EN = "'Plus Jakarta Sans', 'Noto Sans SC', sans-serif";

// ---------- Math ----------
export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, k) => a + (b - a) * k;
export const invLerp = (a, b, x) => clamp((x - a) / (b - a));
export const mix = lerp;

// Normalised progress of t inside [a, b], with optional easing.
export function prog(t, a, b, ease = linear) {
  if (b <= a) return t >= b ? 1 : 0;
  return ease(clamp((t - a) / (b - a)));
}

// ---------- Easing ----------
export const linear = (x) => x;
export const inQuad = (x) => x * x;
export const outQuad = (x) => 1 - (1 - x) * (1 - x);
export const inCubic = (x) => x * x * x;
export const outCubic = (x) => 1 - Math.pow(1 - x, 3);
export const inOutCubic = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const outQuint = (x) => 1 - Math.pow(1 - x, 5);
export const inOutQuint = (x) => (x < 0.5 ? 16 * x ** 5 : 1 - Math.pow(-2 * x + 2, 5) / 2);
export const outExpo = (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x));
export const inExpo = (x) => (x <= 0 ? 0 : Math.pow(2, 10 * x - 10));
export const inOutExpo = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x < 0.5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2);
export const inOutSine = (x) => -(Math.cos(Math.PI * x) - 1) / 2;
export function outBack(x, s = 1.70158) {
  const c3 = s + 1;
  return 1 + c3 * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2);
}
export const outBackSoft = (x) => outBack(x, 1.2);
export function inBack(x, s = 1.70158) {
  return (s + 1) * x * x * x - s * x * x;
}

// Cubic-bezier easing (CSS semantics), solved by Newton + bisection.
export function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (u) => ((ax * u + bx) * u + cx) * u;
  const sy = (u) => ((ay * u + by) * u + cy) * u;
  const dx = (u) => (3 * ax * u + 2 * bx) * u + cx;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let u = x;
    for (let i = 0; i < 8; i++) {
      const e = sx(u) - x;
      if (Math.abs(e) < 1e-6) return sy(u);
      const d = dx(u);
      if (Math.abs(d) < 1e-6) break;
      u -= e / d;
    }
    let lo = 0, hi = 1;
    u = x;
    for (let i = 0; i < 30; i++) {
      const v = sx(u);
      if (Math.abs(v - x) < 1e-6) break;
      if (v < x) lo = u; else hi = u;
      u = (lo + hi) / 2;
    }
    return sy(u);
  };
}
// House curves: snappy "smart" motion (fast out, long settle) and a soft in-out for morphs.
export const snap = bezier(0.16, 1, 0.3, 1);
export const glide = bezier(0.65, 0, 0.35, 1);
export const swoop = bezier(0.7, 0, 0.2, 1);

// Damped spring from 0 to 1 (deterministic, closed form). zeta < 1 overshoots.
export function spring(x, freq = 2.2, zeta = 0.45) {
  if (x <= 0) return 0;
  const w = 2 * Math.PI * freq;
  const wd = w * Math.sqrt(1 - zeta * zeta);
  return 1 - Math.exp(-zeta * w * x) * (Math.cos(wd * x) + (zeta * w / wd) * Math.sin(wd * x));
}

// ---------- Deterministic random ----------
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------- Color ----------
function hexToRgb(h) {
  const s = h.replace('#', '');
  const n = parseInt(s.length === 3 ? s.split('').map((c) => c + c).join('') : s, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export function mixColor(a, b, k) {
  const A = hexToRgb(a), B = hexToRgb(b);
  const r = A.map((v, i) => Math.round(lerp(v, B[i], clamp(k))));
  return '#' + r.map((v) => v.toString(16).padStart(2, '0')).join('');
}

// ---------- SVG builders ----------
const f = (n) => (Math.abs(n) < 1e-4 ? '0' : Number(n.toFixed(2)).toString());
export const num = f;

export function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Rounded-rectangle path centred on (cx, cy). r is clamped to half the short side,
// so the same function draws a circle (w = h = 2r), a capsule, a card or a page.
// This is the single morph primitive: interpolating (cx, cy, w, h, r) never self-intersects.
export function rrPath(cx, cy, w, h, r) {
  w = Math.max(0, w); h = Math.max(0, h);
  const rr = clamp(r, 0, Math.min(w, h) / 2);
  const x = cx - w / 2, y = cy - h / 2;
  if (w === 0 || h === 0) return '';
  // Kappa for quarter-circle cubic approximation.
  const k = 0.5523 * rr;
  return [
    `M${f(x + rr)},${f(y)}`,
    `H${f(x + w - rr)}`,
    `C${f(x + w - rr + k)},${f(y)} ${f(x + w)},${f(y + rr - k)} ${f(x + w)},${f(y + rr)}`,
    `V${f(y + h - rr)}`,
    `C${f(x + w)},${f(y + h - rr + k)} ${f(x + w - rr + k)},${f(y + h)} ${f(x + w - rr)},${f(y + h)}`,
    `H${f(x + rr)}`,
    `C${f(x + rr - k)},${f(y + h)} ${f(x)},${f(y + h - rr + k)} ${f(x)},${f(y + h - rr)}`,
    `V${f(y + rr)}`,
    `C${f(x)},${f(y + rr - k)} ${f(x + rr - k)},${f(y)} ${f(x + rr)},${f(y)}`,
    'Z',
  ].join('');
}

// Interpolate two rounded-rect states {cx, cy, w, h, r}.
export function rrLerp(a, b, k) {
  return { cx: lerp(a.cx, b.cx, k), cy: lerp(a.cy, b.cy, k), w: lerp(a.w, b.w, k), h: lerp(a.h, b.h, k), r: lerp(a.r, b.r, k) };
}

export function attrs(o) {
  let s = '';
  for (const k in o) {
    const v = o[k];
    if (v === undefined || v === null || v === false) continue;
    s += ` ${k}="${typeof v === 'number' ? f(v) : esc(v)}"`;
  }
  return s;
}

export function rr(s, fill, extra = {}) {
  const d = rrPath(s.cx, s.cy, s.w, s.h, s.r);
  return d ? `<path d="${d}"${attrs({ fill, ...extra })}/>` : '';
}

export function circle(cx, cy, r, fill, extra = {}) {
  if (r <= 0) return '';
  return `<circle${attrs({ cx, cy, r, fill, ...extra })}/>`;
}

export function g(content, { x = 0, y = 0, s = 1, sx, sy, rot = 0, o = 1, ox = 0, oy = 0, extra = {} } = {}) {
  if (o <= 0.001) return '';
  const SX = sx ?? s, SY = sy ?? s;
  let tr = '';
  if (x || y) tr += `translate(${f(x)} ${f(y)}) `;
  if (rot || SX !== 1 || SY !== 1) {
    tr += `translate(${f(ox)} ${f(oy)}) `;
    // 4 decimals: small settles and breathing scales (< 1%) must not step in 1% increments.
    if (rot) tr += `rotate(${Number(rot.toFixed(4))}) `;
    if (SX !== 1 || SY !== 1) tr += `scale(${Number(SX.toFixed(4))} ${Number(SY.toFixed(4))}) `;
    tr += `translate(${f(-ox)} ${f(-oy)})`;
  }
  return `<g${attrs({ transform: tr.trim() || undefined, opacity: o < 1 ? o : undefined, ...extra })}>${content}</g>`;
}

export function text(str, x, y, { size = 48, weight = 700, fill = C.ink, anchor = 'middle', family = FONT_CN, ls = 0, o = 1, extra = {} } = {}) {
  if (o <= 0.001) return '';
  return `<text${attrs({
    x, y, fill, 'font-size': size, 'font-weight': weight, 'font-family': family, 'text-anchor': anchor,
    'letter-spacing': ls || undefined, opacity: o < 1 ? o : undefined, 'dominant-baseline': 'alphabetic', ...extra,
  })}>${esc(str)}</text>`;
}

// ---------- Text measurement (canvas, after fonts load) ----------
let measureCtx = null;
export function measure(str, size, weight = 700, family = FONT_CN) {
  if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d');
  measureCtx.font = `${weight} ${size}px ${family}`;
  return measureCtx.measureText(str).width;
}

// Per-character reveal: each glyph rises and fades in with a stagger.
// Returns an SVG string. Glyph positions come from canvas measurement so they match <text>.
export function charsReveal(str, cx, y, t, t0, { size = 72, weight = 800, fill = C.ink, family = FONT_CN, stagger = 0.035, dur = 0.42, rise = 0.5, anchor = 'middle', out = null } = {}) {
  const chars = Array.from(str);
  const total = measure(str, size, weight, family);
  let x = anchor === 'middle' ? cx - total / 2 : anchor === 'end' ? cx - total : cx;
  let s = '';
  let prefix = '';
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    const startX = x + measure(prefix, size, weight, family);
    prefix += ch;
    if (ch === ' ') continue;
    const k = prog(t, t0 + i * stagger, t0 + i * stagger + dur, snap);
    let o = clamp(k * 1.6);
    let dy = (1 - k) * size * rise;
    if (out) {
      const ko = prog(t, out.t0 + i * (out.stagger ?? 0.02), out.t0 + i * (out.stagger ?? 0.02) + (out.dur ?? 0.3), inCubic);
      o *= 1 - ko;
      dy -= ko * size * (out.rise ?? 0.35);
    }
    if (o <= 0.001) continue;
    s += text(ch, startX, y + dy, { size, weight, fill, family, anchor: 'start', o });
  }
  return s;
}

// Mask-wipe line reveal: the line slides up from behind an invisible edge.
let clipSeq = 0;
export function resetClipIds() { clipSeq = 0; }
export function lineReveal(str, cx, y, t, t0, { size = 64, weight = 700, fill = C.ink, family = FONT_CN, dur = 0.5, anchor = 'middle', out = null, ls = 0 } = {}) {
  const k = prog(t, t0, t0 + dur, snap);
  if (k <= 0) return '';
  let dy = (1 - k) * size * 1.25;
  let o = 1;
  if (out) {
    const ko = prog(t, out.t0, out.t0 + (out.dur ?? 0.35), inCubic);
    dy -= ko * size * 1.25;
    if (ko >= 1) return '';
  }
  const id = `clip${clipSeq++}`;
  const top = y - size * 1.05;
  // The mask band spans far beyond any frame width so the same helper serves portrait and landscape.
  const clip = `<clipPath id="${id}"><rect x="-4000" y="${f(top)}" width="12000" height="${f(size * 1.45)}"/></clipPath>`;
  return `<defs>${clip}</defs><g clip-path="url(#${id})">${text(str, cx, y + dy, { size, weight, fill, family, anchor, o, ls })}</g>`;
}

// ---------- Brand marks ----------
// The StudyHub bot face: { cx, cy, d (diameter or square side), shape: 0 circle .. 1 app-icon rounded square,
// blink (eye openness, ew/eh = round dot), look/lookY (-1..1), happy (0..1 eyes become arcs), ring (white ring width),
// eyeShift (eye-pair offset as a fraction of d; the app icon uses 60.43/512) }.
export function botFace({ cx, cy, d, shape = 0, blink = 1, look = 0, lookY = 0, happy = 0, ring = 0, body = C.bot, eye = C.eye, eyeScale = 1, eyeShift = 0, ringColor = '#f5f7fb' }) {
  if (d <= 0.5) return '';
  const r = lerp(d / 2, d * (104 / 512), shape);
  let s = '';
  if (ring > 0) s += rr({ cx, cy, w: d + ring * 2, h: d + ring * 2, r: r + ring }, ringColor);
  s += rr({ cx, cy, w: d, h: d, r }, body);
  // Eye geometry from studyhub-app.svg (pitch 128/512, w 56/512, h 144/512), centred on the face.
  const ew = d * (56 / 512) * eyeScale;
  const eh = d * (144 / 512) * eyeScale;
  const pitch = d * (128 / 512) * eyeScale;
  const ex = look * d * 0.06 + eyeShift * d;
  const ey = lookY * d * 0.05;
  const open = clamp(blink, 0.06, 1);
  for (const side of [-1, 1]) {
    const x = cx + side * pitch / 2 + ex;
    if (happy > 0.01) {
      // Happy eyes: the capsule bends into an upward arc (^ ^). Drawn as a thick stroked arc.
      // Arc half-width 0.7*ew keeps the two arcs apart (pitch is ~2.29*ew), so they read as ^ ^ and not ~~.
      const aw = lerp(ew, ew * 1.4, happy);
      const ah = lerp(eh, ew * 1.1, happy);
      const yy = cy + ey - lerp(0, eh * 0.05, happy);
      if (happy < 0.5) {
        s += rr({ cx: x, cy: yy, w: lerp(ew, aw, happy), h: Math.max(ew, ah * open), r: 999 }, eye);
      } else {
        const sw = ew * 0.78;
        const hw = aw / 2;
        s += `<path d="M${f(x - hw)},${f(yy + ew * 0.43)} Q${f(x)},${f(yy - ew * 1.1)} ${f(x + hw)},${f(yy + ew * 0.43)}"${attrs({ fill: 'none', stroke: eye, 'stroke-width': sw, 'stroke-linecap': 'round' })}/>`;
      }
    } else {
      s += rr({ cx: x, cy: cy + ey, w: ew, h: Math.max(ew, eh * open), r: ew / 2 }, eye);
    }
  }
  return s;
}

// Blink curve matching the site's eye-blink keyframes (scaleY 1 -> 0.2 -> 0.05 -> 1), over `dur` seconds.
export function blinkAt(t, t0, dur = 0.22) {
  const x = (t - t0) / dur;
  if (x <= 0 || x >= 1) return 1;
  if (x < 0.45) return lerp(1, 0.08, outQuad(x / 0.45));
  return lerp(0.08, 1, outCubic((x - 0.45) / 0.55));
}

// A study note card: page + coloured header capsule + text-line capsules (the film's through-line).
export function noteCard({ cx, cy, w, h, r = null, fill = C.paper, accent = C.blue, lines = 4, lineColor = '#d6deea', o = 1, tilt = 0, headerK = 1, linesK = 1, shadow = true }) {
  if (o <= 0.001 || w <= 1) return '';
  const R = r ?? w * 0.09;
  let s = '';
  if (shadow) s += rr({ cx: cx + w * 0.035, cy: cy + w * 0.05, w, h, r: R }, 'rgba(15,23,42,0.10)');
  s += rr({ cx, cy, w, h, r: R }, fill);
  const pad = w * 0.16;
  const left = cx - w / 2 + pad;
  const hw = (w - pad * 2) * 0.55 * headerK;
  const lh = Math.max(4, w * 0.075);
  if (headerK > 0.01) s += rr({ cx: left + hw / 2, cy: cy - h / 2 + pad + lh / 2, w: hw, h: lh, r: lh / 2 }, accent);
  const gap = (h - pad * 2 - lh) / (lines + 0.5);
  for (let i = 0; i < lines; i++) {
    const k = clamp(linesK * lines - i);
    const lw = (w - pad * 2) * (i === lines - 1 ? 0.6 : i % 2 ? 0.86 : 1) * k;
    const ly = cy - h / 2 + pad + lh + gap * (i + 1);
    const thick = Math.max(3, w * 0.05);
    if (lw > 0.5) s += rr({ cx: left + lw / 2, cy: ly, w: lw, h: thick, r: thick / 2 }, lineColor);
  }
  return g(s, { o, rot: tilt, ox: cx, oy: cy });
}
