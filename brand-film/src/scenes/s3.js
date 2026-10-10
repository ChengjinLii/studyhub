// S3 use (7.85-15 s): the blue field shrinks into a phone and the app is used in three steps
// (find, get, share); then the hero note lifts out of the phone and an ink iris takes the frame.
import { C, FONT_CN, FONT_EN, rr, g, text, measure, lineReveal, prog, clamp, lerp, mixColor, spring, snap, bezier, outBack, outCubic, inCubic, inBack, inOutSine, outQuad, botFace, blinkAt, noteCard } from '../core.js';
import { lockup, materialCard, COURSES, GRID, gridSlot, downloadIcon, student, FACE, heroNote, HERO_NOTE, priceLabel, priceColor } from '../shared.js';
import { FACE_HEAD, LOCK_BIG, LOCK_HEAD, lockupTransform } from './s2.js';

export const range = [7.85, 15.0];
export function background() { return C.bg; }

// ---------- Curves ----------
const morph = bezier(0.7, 0, 0.3, 1);     // house morph curve: slow start (anticipation), soft landing
const shrink = bezier(0.5, 0, 0.22, 1);   // M5 master curve: short cushion, long even shrink, soft landing
const morphH = bezier(0.44, 0, 0.2, 1);   // phone height leads ...
const morphW = bezier(0.58, 0, 0.25, 1);  // ... width lags: the field squashes on the way in
const deal = bezier(0.6, -0.18, 0.35, 1); // cards: a small pull-back, then deal into the list
const push = bezier(0.62, 0, 0.18, 1);    // page push
const bump = (p) => (p <= 0 || p >= 1 ? 0 : Math.sin(Math.PI * p) * (1 - p) * 1.72); // 0..~1, early peak, decays

// ---------- Phone geometry (at rest) ----------
const PH = { cx: 540, cy: 1046, w: 620, h: 1200, r: 86 };
const BZ = 14;
const SCR = { cx: PH.cx, cy: PH.cy, w: PH.w - 2 * BZ, h: PH.h - 2 * BZ, r: PH.r - BZ };
const SL = SCR.cx - SCR.w / 2, SR = SCR.cx + SCR.w / 2, ST = SCR.cy - SCR.h / 2, SB = SCR.cy + SCR.h / 2;
const CL = SL + 28, CR = SR - 28, CW = CR - CL; // content column 272..808
const BAND_B = 716;                              // white app header band: ST..BAND_B
const FACE_BAR = { cx: CL + 30, cy: 558, d: 60 };
const TITLE = { x: CL + 78, y: 573, size: 40 };
const AVATAR = { cx: CR - 24, cy: 558, d: 48 };
const SEARCH = { cx: 540, cy: 652, w: CW, h: 72, r: 36 };
const SEARCH_TX = CL + 70;
const CHIP_Y = 762, CHIP_H = 52;
const CARD = { w: CW, h: 148, r: 24, top: 810, gap: 16 };
const slotY = (i) => CARD.top + CARD.h / 2 + i * (CARD.h + CARD.gap);
const TAB_T = 1528, TAB_ICON = 1562, TAB_LABEL = 1609;
const TABS = ['首页', '资料', '投稿', '求购', '我的'];
const tabX = (i) => SL + SCR.w / 10 + i * SCR.w / 5;
const PANEL = { cx: 540, top: 604, bottom: TAB_T + 40 };
const PANEL_RECT = { cx: 540, cy: (PANEL.top + PANEL.bottom) / 2, w: SCR.w, h: PANEL.bottom - PANEL.top, r: 36 };

// Detail page (at rest).
const D = {
  block: { cx: CL + 42, cy: 704, w: 84, h: 104, r: 18 },
  titleX: CL + 108, titleY: 690,
  badgeY: 742,
  freeY: 848, rateY: 844,
  shareY: 904,
  file: { cx: 540, cy: 972, w: CW, h: 80, r: 20 },
  prev: { cx: 540, cy: 1204, w: CW, h: 336, r: 28 },
  btn: { cx: CR - 224, cy: 1468, w: 448, h: 84, r: 42 },
  tray: { cx: CL + 40, cy: 1466 },
};
// Upload page (at rest).
const U = {
  labelY: 664,
  field: { cx: 540, cy: 724, w: CW, h: 76, r: 22 },
  zone: { cx: 540, cy: 1012, w: CW, h: 440, r: 32 },
  btn: { cx: 540, cy: 1324, w: CW, h: 84, r: 42 },
};
const NOTE_REST = { cx: 540, cy: 990, w: 156, tilt: -4 };
const HERO_IDX = 2; // COURSES[2] = 概率论 #期末真题
const HERO_TITLE = '概率论 期末真题';
const RATINGS = ['4.9', '4.7', '4.8', '4.6', '4.9'];
const SHADOW = 'rgba(15,23,42,0.10)';

// ---------- Small pieces ----------
function capsuleLine(x1, y1, x2, y2, th, fill) {
  const L = Math.hypot(x2 - x1, y2 - y1);
  const ang = Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI;
  const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
  return g(rr({ cx, cy, w: L + th, h: th, r: th / 2 }, fill), { rot: ang, ox: cx, oy: cy });
}
// Check mark from two capsules; s = box size.
function check(cx, cy, s, fill, k = 1) {
  if (k <= 0.01) return '';
  const th = s * 0.15;
  const ax = cx - s * 0.3, ay = cy + s * 0.02, bx = cx - s * 0.08, by = cy + s * 0.24, ex = cx + s * 0.32, ey = cy - s * 0.2;
  return g(capsuleLine(ax, ay, bx, by, th, fill) + capsuleLine(bx, by, ex, ey, th, fill), { s: k, ox: cx, oy: cy });
}
// Upload glyph: arrow up over a tray, all capsules.
function uploadIcon(cx, cy, size, color) {
  const u = size / 100;
  let s = '';
  s += rr({ cx, cy: cy - 2 * u, w: 16 * u, h: 58 * u, r: 8 * u }, color);
  s += g(rr({ cx: cx - 14 * u, cy: cy - 18 * u, w: 16 * u, h: 40 * u, r: 8 * u }, color), { rot: 45, ox: cx - 14 * u, oy: cy - 18 * u });
  s += g(rr({ cx: cx + 14 * u, cy: cy - 18 * u, w: 16 * u, h: 40 * u, r: 8 * u }, color), { rot: -45, ox: cx + 14 * u, oy: cy - 18 * u });
  s += rr({ cx, cy: cy + 42 * u, w: 84 * u, h: 16 * u, r: 8 * u }, color);
  return s;
}
function searchIcon(cx, cy, color, hole) {
  return capsuleLine(cx + 7, cy + 7, cx + 15, cy + 15, 6, color) + `<circle cx="${cx}" cy="${cy}" r="13" fill="${color}"/>` + `<circle cx="${cx}" cy="${cy}" r="7.5" fill="${hole}"/>`;
}
function tabIcon(i, cx, cy, col) {
  let s = '';
  if (i === 0) { // home
    s += g(rr({ cx, cy: cy - 5, w: 22, h: 22, r: 4 }, col), { rot: 45, ox: cx, oy: cy - 5 });
    s += rr({ cx, cy: cy + 6, w: 26, h: 20, r: 5 }, col);
  } else if (i === 1) { // materials: two pages
    s += g(rr({ cx: cx + 5, cy: cy - 4, w: 22, h: 28, r: 5 }, col), { o: 0.45 });
    s += rr({ cx: cx - 3, cy: cy + 3, w: 22, h: 28, r: 5 }, col);
  } else if (i === 2) { // upload: plus in a rounded square
    s += rr({ cx, cy, w: 32, h: 32, r: 10 }, col);
    s += rr({ cx, cy, w: 16, h: 4, r: 2 }, C.paper) + rr({ cx, cy, w: 4, h: 16, r: 2 }, C.paper);
  } else if (i === 3) { // request: speech bubble
    s += rr({ cx, cy: cy - 2, w: 34, h: 26, r: 10 }, col);
    s += g(rr({ cx: cx - 8, cy: cy + 9, w: 9, h: 9, r: 2 }, col), { rot: 45, ox: cx - 8, oy: cy + 9 });
    for (const dx of [-8, 0, 8]) s += `<circle cx="${cx + dx}" cy="${cy - 2}" r="2.4" fill="${C.paper}"/>`;
  } else { // me
    s += `<circle cx="${cx}" cy="${cy - 7}" r="8" fill="${col}"/>`;
    s += rr({ cx, cy: cy + 10, w: 28, h: 13, r: 6.5 }, col);
  }
  return s;
}
function toast(str, cx, cy, kIn, kOut) {
  const k = kIn * (1 - kOut);
  if (k <= 0.01) return '';
  const tw = measure(str, 28, 700);
  const w = tw + 104, h = 68;
  const left = cx - w / 2;
  let s = rr({ cx: cx + 4, cy: cy + 6, w, h, r: h / 2 }, SHADOW);
  s += rr({ cx, cy, w, h, r: h / 2 }, C.ink);
  s += `<circle cx="${left + 40}" cy="${cy}" r="17" fill="${C.blue}"/>`;
  s += check(left + 40, cy, 30, C.paper);
  s += text(str, left + 70, cy + 10, { size: 28, weight: 700, fill: C.paper, anchor: 'start' });
  return g(s, { o: clamp(kIn * 1.4) * (1 - kOut), y: (1 - kIn) * 34 + kOut * 18, s: lerp(0.92, 1, kIn), ox: cx, oy: cy });
}
// Touch indicator: a soft dot that presses at t0, then a ripple.
function tap(t, t0, x, y) {
  if (t < t0 - 0.16 || t > t0 + 0.42) return '';
  const a = prog(t, t0 - 0.16, t0 - 0.03, outCubic);
  const press = Math.sin(Math.PI * prog(t, t0 - 0.03, t0 + 0.09));
  const fade = 1 - prog(t, t0 + 0.05, t0 + 0.18);
  const rp = prog(t, t0, t0 + 0.4, outCubic);
  let s = '';
  if (rp > 0 && rp < 1) s += `<circle cx="${x}" cy="${y}" r="${lerp(30, 92, rp).toFixed(2)}" fill="${C.blue}" opacity="${(0.28 * (1 - rp)).toFixed(3)}"/>`;
  const r = lerp(46, 32, a) * (1 - 0.18 * press);
  if (fade > 0) s += `<circle cx="${x}" cy="${y}" r="${r.toFixed(2)}" fill="${C.ink}" opacity="${(0.2 * a * fade).toFixed(3)}"/>`;
  return s;
}

// ---------- Material card that reflows from the S2 grid layout (m = 0, identical to materialCard) to the list layout (m = 1) ----------
function flowCard({ cx, cy, m, course, title = null, rating = '4.8', fill = C.paper, shadow = 1 }) {
  const w = lerp(GRID.w, CARD.w, m), h = lerp(GRID.h, CARD.h, m);
  const R = lerp(Math.min(GRID.w, GRID.h) * 0.11, CARD.r, m);
  let s = '';
  if (shadow > 0) s += rr({ cx: cx + lerp(6, 5, m), cy: cy + lerp(9, 8, m), w, h, r: R }, SHADOW);
  s += rr({ cx, cy, w, h, r: R }, fill);
  const x0 = cx - w / 2, y0 = cy - h / 2;
  const left = cx - w / 2 + 26;
  const L = (a, b) => lerp(a, b, m);
  const vis = m < 0.5 ? 1 - prog(m, 0.04, 0.22) : prog(m, 0.62, 0.9);
  const ov = (o) => (o < 1 ? { opacity: o } : {});
  // File block.
  const bx = L(left + 22, x0 + 56), by = L(cy - h / 2 + 50, cy), bw = L(44, 64), bh = L(54, 80);
  s += rr({ cx: bx, cy: by, w: bw, h: bh, r: L(10, 14) }, course.color);
  s += rr({ cx: bx, cy: L(cy - h / 2 + 44, cy - 9), w: L(22, 32), h: L(5, 7), r: L(2.5, 3.5) }, 'rgba(255,255,255,0.85)');
  s += rr({ cx: bx, cy: L(cy - h / 2 + 56, cy + 9), w: L(22, 32), h: L(5, 7), r: L(2.5, 3.5) }, 'rgba(255,255,255,0.85)');
  // Title (the hero card gains its full title as it becomes a list row).
  const tx = L(left + 60, x0 + 108), ty = L(cy - h / 2 + 62, cy - 12);
  if (vis > 0) s += text(course.name, tx, ty, { size: 32, weight: 800, fill: C.ink, anchor: 'start', o: vis });
  if (title && m > 0.4 && vis > 0) {
    const suffix = title.slice(course.name.length).trimStart();
    s += text(suffix, tx + measure(title.slice(0, title.length - suffix.length), 32, 800), ty, { size: 32, weight: 800, fill: C.ink, anchor: 'start', o: vis });
  }
  // Tag badge.
  const tw = measure(course.tag, 22, 600) + 26;
  const tl = L(left, x0 + 108), tcy = L(cy + 6, cy + 32);
  if (vis <= 0) return s;
  s += rr({ cx: tl + tw / 2, cy: tcy, w: tw, h: 38, r: 19 }, '#e8eefc', ov(vis));
  s += text(course.tag, tl + 13, tcy + 8, { size: 22, weight: 600, fill: C.blueDeep, anchor: 'start', o: vis });
  // Price.
  s += text(priceLabel(course), L(left, x0 + 108 + tw + 16), L(cy + h / 2 - 30, cy + 41), { size: 24, weight: 700, fill: priceColor(course), anchor: 'start', o: vis });
  // Rating: the grey capsule of the grid card becomes the real "评分" line.
  const capO = vis * (m < 0.5 ? 1 : 0);
  const rx = L(cx + w / 2 - 26 - 40, x0 + w - 24 - 52), ry = L(cy + h / 2 - 38, cy + 32);
  if (capO > 0) s += rr({ cx: rx, cy: ry, w: L(80, 104), h: 10, r: 5 }, C.line, capO < 1 ? { opacity: capO } : {});
  const rO = m >= 0.5 ? vis : 0;
  if (rO > 0) s += text('评分：' + rating, x0 + w - 24, cy + 40, { size: 22, weight: 600, fill: C.meta, anchor: 'end', o: rO });
  return s;
}

// ---------- M5: blue field -> phone ----------
function phoneM5(t, q) {
  const [a, z] = q.toPhone;
  const land = z - 0.02; // the "phone-land" hit in the audio
  const u = prog(t, a, land);
  const k = shrink(u);
  const kh = morphH(u), kw = morphW(u);
  const b = bump(prog(t, land - 0.05, z + 0.2));
  const sw = prog(t, land, z + 0.24);
  const rot = -2.4 * Math.sin(Math.PI * u) + 0.8 * Math.sin(Math.PI * sw) * (1 - sw);
  const body = {
    cx: PH.cx,
    cy: lerp(960, PH.cy, kh),
    w: lerp(1080, PH.w, kw),
    h: lerp(1920, PH.h, kh),
    r: lerp(0, PH.r, clamp(k * 1.3)),
  };
  const bz = BZ * prog(k, 0.12, 0.6);
  const scr = { cx: body.cx, cy: body.cy, w: body.w - 2 * bz, h: body.h - 2 * bz, r: Math.max(0, body.r - bz) };
  const col = prog(k, 0.3, 0.78, inOutSine);
  return {
    u, k, body, scr, rot,
    sx: 1 + 0.022 * b, sy: 1 - 0.034 * b,
    bodyFill: mixColor(C.blue, C.ink, prog(k, 0.12, 0.62)),
    scrFill: mixColor(C.blue, C.bg, col),
    bandFill: mixColor(C.blue, C.paper, col),
    shadow: prog(k, 0.6, 1),
    island: prog(k, 0.55, 0.95, outCubic),
  };
}

// ---------- Step labels: blue number pill + headline ----------
function stepLabels(t, q) {
  const L = [
    { t: q.label1, str: q.label1Text, n: '01' },
    { t: q.label2, str: q.label2Text, n: '02' },
    { t: q.label3, str: q.label3Text, n: '03' },
  ];
  const outT = q.noteLift[0] - 0.05;
  if (t < L[0].t - 0.05 || t > outT + 0.45) return '';
  const size = 68, y = 325, pw = 106, ph = 74, gap = 24;
  const tw = measure(L[0].str, size, 900);
  const x0 = 540 - (pw + gap + tw) / 2;
  const pcx = x0 + pw / 2, pcy = y - 25;
  let s = '';
  // Pill: dot pops, stretches to a capsule; at the end it folds back to a dot and goes.
  const d = ph * clamp(spring(t - (L[0].t - 0.04), 2.8, 0.5), 0, 1.2) * (1 - prog(t, outT + 0.08, outT + 0.22, inBack));
  const wk = prog(t, L[0].t + 0.06, L[0].t + 0.26, snap) * (1 - prog(t, outT, outT + 0.1, inCubic));
  const w = lerp(d, pw, wk);
  if (d > 0.5) {
    const pill = { cx: pcx, cy: pcy, w, h: d, r: d / 2 };
    s += rr(pill, C.blue);
    let digits = '';
    for (let i = 0; i < L.length; i++) {
      const kin = prog(t, L[i].t - 0.02, L[i].t + 0.3, snap);
      const nextT = i < L.length - 1 ? L[i + 1].t - 0.18 : outT;
      const kout = prog(t, nextT, nextT + 0.18, inCubic);
      if (kin <= 0 || kout >= 1) continue;
      const dy = (1 - kin) * ph * 0.9 - kout * ph * 0.9;
      digits += text(L[i].n, pcx, pcy + 14 + dy, { size: 40, weight: 800, family: FONT_EN, fill: C.paper, ls: 1 });
    }
    s += `<defs><clipPath id="s3pill"><path d="${rr(pill, '#000').match(/d="([^"]+)"/)[1]}"/></clipPath></defs><g clip-path="url(#s3pill)">${digits}</g>`;
  }
  for (let i = 0; i < L.length; i++) {
    const nextT = i < L.length - 1 ? L[i + 1].t - 0.2 : outT;
    s += lineReveal(L[i].str, x0 + pw + gap, y, t, L[i].t, { size, weight: 900, fill: C.ink, anchor: 'start', dur: 0.5, out: { t0: nextT, dur: 0.2 } });
  }
  return s;
}

// ---------- Hero note path (outside the phone group) ----------
function noteState(t, q) {
  const [n0, n1] = q.noteIn;
  const [l0, l1] = q.noteLift;
  if (t < n0) return null;
  if (t >= l1) return { hero: true };
  if (t < n1) {
    const x = prog(t, n0, n1);
    const u = x * (1.4 - 0.4 * x); // enters already moving, still has speed at contact
    const P0 = { x: -200, y: 980 }, P1 = { x: 200, y: 600 }, P2 = { x: NOTE_REST.cx, y: NOTE_REST.cy };
    const cx = (1 - u) ** 2 * P0.x + 2 * (1 - u) * u * P1.x + u * u * P2.x;
    const cy = (1 - u) ** 2 * P0.y + 2 * (1 - u) * u * P1.y + u * u * P2.y;
    const vx = 2 * (1 - u) * (P1.x - P0.x) + 2 * u * (P2.x - P1.x);
    const vy = 2 * (1 - u) * (P1.y - P0.y) + 2 * u * (P2.y - P1.y);
    return {
      cx, cy, w: lerp(236, NOTE_REST.w, u), tilt: lerp(-18, NOTE_REST.tilt, u) + 14 * Math.sin(Math.PI * u),
      ang: Math.atan2(vy, vx) * 180 / Math.PI, stretch: 0.12 * Math.sin(Math.PI * Math.min(1, u * 1.15)),
    };
  }
  const land = bump(prog(t, n1 - 0.02, n1 + 0.3));
  if (t < l0) return { ...NOTE_REST, land };
  // Lift: a small dip, then up and out of the phone to the hero size, straightening.
  const dip = Math.sin(Math.PI * prog(t, l0, l0 + 0.1));
  const x = prog(t, l0 + 0.05, l1);
  const e = outBack(x, 1.3);
  const p = snap(x);
  return {
    cx: lerp(NOTE_REST.cx, HERO_NOTE.cx, p),
    cy: lerp(NOTE_REST.cy, HERO_NOTE.cy, p) - 46 * Math.sin(Math.PI * p) + 8 * dip,
    w: lerp(NOTE_REST.w, HERO_NOTE.w, e),
    tilt: lerp(NOTE_REST.tilt, 0, p),
    land: 0.6 * dip,
  };
}
function drawNote(ns) {
  if (!ns) return '';
  if (ns.hero) return heroNote();
  const w = ns.w, h = w * (HERO_NOTE.h / HERO_NOTE.w);
  let s = noteCard({ cx: ns.cx, cy: ns.cy, w, h, accent: HERO_NOTE.accent, lines: HERO_NOTE.lines, tilt: ns.tilt });
  if (ns.stretch) {
    const a = ns.ang, st = ns.stretch;
    s = `<g transform="translate(${ns.cx.toFixed(2)} ${ns.cy.toFixed(2)}) rotate(${a.toFixed(2)}) scale(${(1 + st).toFixed(3)} ${(1 - st * 0.8).toFixed(3)}) rotate(${(-a).toFixed(2)}) translate(${(-ns.cx).toFixed(2)} ${(-ns.cy).toFixed(2)})">${s}</g>`;
  }
  if (ns.land) s = g(s, { sx: 1 + 0.1 * ns.land, sy: 1 - 0.13 * ns.land, ox: ns.cx, oy: ns.cy + h / 2 });
  return s;
}

// ---------- The app inside the phone (final-layout coordinates) ----------
function appScreen(t, q, ph) {
  const m5 = t < q.toPhone[1] + 0.3;
  const [a] = q.toPhone;
  const land = q.toPhone[1] - 0.02;
  let s = '';

  // Page push to 投稿工作台.
  const kU = prog(t, q.toUpload[0], q.toUpload[1], push);
  const oldX = -0.3 * SCR.w * kU;
  const newX = SCR.w * (1 - kU);
  const detailOpen = t >= q.cardExpand[1];

  // Screen background + white header band (the band scales with the screen while it forms).
  s += rr(ph.scr, ph.scrFill);
  const sTop = ph.scr.cy - ph.scr.h / 2;
  const bandH = (BAND_B - ST) * ph.scr.h / SCR.h;
  s += rr({ cx: ph.scr.cx, cy: sTop + bandH / 2 - 40, w: ph.scr.w, h: bandH + 80, r: 0 }, ph.bandFill);

  // ---- Under the detail page: search, chips, list (hidden once the detail page is open) ----
  if (!detailOpen) {
    // Search field: a dot that stretches to a capsule after the phone lands.
    const kd = clamp(spring(t - (land - 0.16), 3.2, 0.55), 0, 1.15);
    const kw = prog(t, land - 0.1, land + 0.06, snap);
    if (kd > 0.01) {
      const focus = prog(t, q.tapSearch, q.tapSearch + 0.12, outCubic);
      const sw = lerp(SEARCH.h, SEARCH.w, kw);
      const sf = { cx: CL + sw / 2, cy: SEARCH.cy, w: sw * (kw < 1 ? 1 : 1), h: SEARCH.h * kd, r: SEARCH.r * kd };
      const fieldFill = mixColor(C.bg, C.paper, focus);
      if (focus > 0) s += rr({ ...sf, w: sf.w + 6 * focus, h: sf.h + 6 * focus, r: sf.r + 3 * focus }, C.blue);
      s += rr(sf, fieldFill);
      s += g(searchIcon(CL + 34, SEARCH.cy - 2, C.meta, fieldFill), { s: clamp(kd), ox: CL + 36, oy: SEARCH.cy });
      // Placeholder until the first key, then the typed query with a caret.
      const keys = q.typeKeys;
      const phO = prog(t, land - 0.06, land + 0.04) * (1 - prog(t, keys[0] - 0.04, keys[0]));
      if (phO > 0) s += text('搜课程 / 资料名 / 标签', SEARCH_TX, SEARCH.cy + 10, { size: 28, weight: 500, fill: C.meta, anchor: 'start', o: phO });
      const glyphs = Array.from(q.typed);
      let n = 0;
      for (let i = 0; i < glyphs.length; i++) {
        const kt = t - keys[i];
        if (kt < 0) break;
        n = i + 1;
        if (glyphs[i] === ' ') continue;
        const x = SEARCH_TX + measure(glyphs.slice(0, i).join(''), 30, 600);
        const pop = prog(kt, 0, 0.1, outCubic);
        s += g(text(glyphs[i], x, SEARCH.cy + 11, { size: 30, weight: 600, fill: C.ink, anchor: 'start' }), { s: lerp(1.3, 1, pop), o: clamp(0.45 + pop * 1.6), ox: x + 15, oy: SEARCH.cy });
      }
      if (focus > 0.4 && t < q.cardExpand[0]) {
        const cx = SEARCH_TX + measure(glyphs.slice(0, n).join(''), 30, 600) + 3;
        const lastKey = n > 0 ? keys[n - 1] : q.tapSearch;
        const on = t - lastKey < 0.3 || Math.floor((t - lastKey - 0.3) / 0.4) % 2 === 1;
        if (on) s += rr({ cx, cy: SEARCH.cy, w: 3, h: 34 * focus, r: 1.5 }, C.blue);
      }
    }

    // Chips.
    const chips = ['全部', '免费', '付费', '#期末真题'];
    let cxp = CL;
    for (let j = 0; j < chips.length; j++) {
      const cw = measure(chips[j], 26, 600) + 40;
      const kc = clamp(spring(t - (land + 0.03 + j * 0.05), 3.4, 0.5), 0, 1.2);
      if (kc > 0.01) {
        let act = 0;
        if (j === 0) act = 1 - prog(t, q.chip, q.chip + 0.1);
        if (j === 3) act = prog(t, q.chip, q.chip + 0.08);
        const pop = j === 3 ? 0.12 * bump(prog(t, q.chip, q.chip + 0.3)) : 0;
        const c = { cx: cxp + cw / 2, cy: CHIP_Y, w: cw, h: CHIP_H, r: CHIP_H / 2 };
        let chip = rr(c, mixColor(C.paper, C.blue, act));
        chip += text(chips[j], c.cx, CHIP_Y + 9, { size: 26, weight: 600, fill: mixColor(C.muted, C.paper, act) });
        s += g(chip, { s: kc * (1 + pop), o: clamp(kc * 2), ox: c.cx, oy: CHIP_Y });
      }
      cxp += cw + 14;
    }

    // List cards: during M5 they reflow from the S2 grid; then the reshuffle lifts the hero to the top.
    const rs = q.reshuffle;
    const kHero = prog(t, rs[0], rs[1] - 0.03, bezier(0.5, 0, 0.2, 1));
    const dim = prog(t, rs[0] + 0.05, rs[1], snap);
    const order = [4, 3, 1, 0, HERO_IDX];
    const drawCard = (i) => {
      const course = COURSES[i];
      const title = i === HERO_IDX ? HERO_TITLE : null;
      // Visible cards are dealt one after another (about 1.3 frames apart); the rest ride the field.
      const st = i <= 4 ? a + 0.05 + i * 0.035 : a + 0.02;
      const uc = prog(t, st, i <= 4 ? st + 0.36 : land);
      const kc = deal(uc);
      if (t <= a) return materialCard({ ...gridSlot(i), w: GRID.w, h: GRID.h, course }); // exact S2 hand-off picture
      // Target slot: list slots 0..4, the rest park below the tab bar.
      const ty = i <= 4 ? slotY(i) : SB + 110 + (i - 5) * 30;
      const gs = gridSlot(i);
      // Where the shrinking field carries this grid card.
      const sF = ph.scr.w / 1080;
      const fx = ph.scr.cx + (gs.cx - 540) * sF, fy = ph.scr.cy + (gs.cy - 960) * ph.scr.h / 1920;
      if (m5 && i > 4) {
        // Cards beyond the visible list ride the field in grid formation and dissolve.
        const o = 1 - prog(uc, 0.05, 0.5, inOutSine);
        if (o <= 0) return '';
        return g(flowCard({ cx: fx, cy: fy, m: 0, course }), { s: sF * (1 - 0.08 * (1 - o)), o, ox: fx, oy: fy });
      }
      if (m5 && uc <= 0) return g(flowCard({ cx: fx, cy: fy, m: 0, course }), { s: sF, ox: fx, oy: fy });
      if (m5 && uc < 1) {
        // Deal from the field-carried position into the list row.
        const kx = deal(clamp(uc * 1.15));
        const m = clamp(kc);
        const cx = lerp(fx, 540, kx), cy = lerp(fy, ty, kc);
        return g(flowCard({ cx, cy, m, course, title, rating: RATINGS[i] }), { s: lerp(sF, 1, m), ox: cx, oy: cy });
      }
      if (i > 4) return '';
      let cy = slotY(i), cx = 540, sc = 1, o = 1, halo = 0;
      if (i === HERO_IDX) {
        cy = lerp(slotY(2), slotY(0), kHero);
        cx = 540 + 14 * Math.sin(Math.PI * kHero);
        sc = 1 + 0.03 * Math.sin(Math.PI * kHero);
        halo = clamp(spring(t - (rs[1] - 0.1), 3, 0.55), 0, 1.15);
        // tap press on the card.
        sc *= 1 - 0.035 * Math.sin(Math.PI * prog(t, q.tapCard - 0.04, q.cardExpand[0]));
      } else {
        const delay = i === 0 ? 0.04 : i === 1 ? 0.08 : 0;
        const ks = prog(t, rs[0] + delay, rs[1] + delay * 0.5, snap);
        if (i === 0) cy = lerp(slotY(0), slotY(1), ks);
        if (i === 1) cy = lerp(slotY(1), slotY(2), ks);
        o = 1 - 0.5 * dim;
      }
      let c = '';
      if (halo > 0.01) c += rr({ cx, cy, w: CARD.w + 16 * halo, h: CARD.h + 16 * halo, r: CARD.r + 8 * halo }, C.blueSoft);
      c += flowCard({ cx, cy, m: 1, course, title, rating: RATINGS[i] });
      return g(c, { s: sc, o, ox: cx, oy: cy });
    };
    const heroOnTop = !m5 || t > land;
    for (let i = COURSES.length - 1; i >= 0; i--) if (i !== HERO_IDX || !heroOnTop) s += m5 || i <= 4 ? drawCard(i) : '';
    if (heroOnTop && t < q.cardExpand[0]) s += drawCard(HERO_IDX);
  }

  // ---- Detail page (M6: the hero card grows into it) and the M7 download ----
  if (t >= q.cardExpand[0] && kU < 1) s += g(detailPage(t, q), { x: oldX });

  // ---- Upload page (pushed in from the right) ----
  if (kU > 0) s += g(uploadPage(t, q), { x: newX });

  // ---- Top bar: bot face (from the S2 header), page title, avatar ----
  const kf = shrink(prog(t, a, land - 0.03));
  if (m5 && kf < 1) {
    const arc = 26 * Math.sin(Math.PI * kf);
    const fx = lerp(FACE_HEAD.cx, FACE_BAR.cx, kf) - arc, fy = lerp(FACE_HEAD.cy, FACE_BAR.cy, kf);
    const fd = lerp(FACE_HEAD.d, FACE_BAR.d, kf);
    s += botFace({ cx: fx, cy: fy, d: fd, ring: 4 * (1 - kf), blink: 1, look: 0 });
    // The white lockup rides along and fades as the header becomes the app bar.
    const lo = 1 - prog(kf, 0.02, 0.42);
    if (lo > 0) {
      const lt = lockupTransform(1);
      const inner = g(lockup(540, LOCK_BIG.y, LOCK_BIG.size, { fill: '#ffffff' }), lt);
      s += kf > 0 ? g(inner, { x: fx - FACE_HEAD.cx, y: fy - FACE_HEAD.cy, s: lerp(1, 0.78, kf), o: lo, ox: LOCK_HEAD.left, oy: LOCK_HEAD.y - 16 }) : inner;
    }
  } else {
    // Bot face lives in the app bar: one blink, and it watches the note fly in.
    const [n0, n1] = q.noteIn;
    const lookL = prog(t, n0 - 0.05, n0 + 0.15, outCubic) * (1 - prog(t, n1 - 0.25, n1 - 0.05, outCubic));
    const lookD = prog(t, n1 - 0.2, n1, outCubic) * (1 - prog(t, n1 + 0.5, n1 + 0.75, outCubic));
    const blink = blinkAt(t, q.tapGet - 0.3) * blinkAt(t, q.noteLift[0] - 0.35);
    s += botFace({ cx: FACE_BAR.cx, cy: FACE_BAR.cy, d: FACE_BAR.d, blink, look: -0.9 * lookL + 0.2 * lookD, lookY: 0.8 * lookD });
  }
  const tIn = prog(t, land - 0.2, land, outCubic);
  const tSw = prog(t, q.toUpload[0] + 0.02, q.toUpload[0] + 0.26, push);
  if (tIn > 0) {
    const tOut = prog(tSw, 0, 0.4), tNew = prog(tSw, 0.35, 1);
    s += text('资料库', TITLE.x, TITLE.y + (1 - tIn) * 18 - 22 * tOut, { size: TITLE.size, weight: 900, fill: C.ink, anchor: 'start', o: tIn * (1 - tOut) });
    if (tNew > 0) s += text('投稿工作台', TITLE.x, TITLE.y + 22 * (1 - tNew), { size: TITLE.size, weight: 900, fill: C.ink, anchor: 'start', o: tNew });
  }
  const ka = clamp(spring(t - (land + 0.02), 3, 0.5), 0, 1.2);
  if (ka > 0.01) s += g(student({ cx: AVATAR.cx, cy: AVATAR.cy, d: AVATAR.d, color: FACE.sky }), { s: ka, ox: AVATAR.cx, oy: AVATAR.cy });

  // ---- Tab bar ----
  const kt = prog(t, land - 0.08, land + 0.14, snap);
  if (kt > 0) {
    let tb = rr({ cx: 540, cy: (TAB_T + SB + 40) / 2 - 3, w: SCR.w, h: SB + 40 - TAB_T, r: 0 }, SHADOW);
    tb += rr({ cx: 540, cy: (TAB_T + SB + 40) / 2, w: SCR.w, h: SB + 40 - TAB_T, r: 0 }, C.paper);
    const sw = prog(t, q.tapTab, q.tapTab + 0.08);
    for (let i = 0; i < 5; i++) {
      const act = i === 1 ? 1 - sw : i === 2 ? sw : 0;
      const col = mixColor(C.meta, C.blue, act);
      const pop = i === 2 ? 0.18 * bump(prog(t, q.tapTab, q.tapTab + 0.3)) : 0;
      tb += g(tabIcon(i, tabX(i), TAB_ICON, col), { s: 1 + pop, ox: tabX(i), oy: TAB_ICON });
      tb += text(TABS[i], tabX(i), TAB_LABEL, { size: 22, weight: act > 0.5 ? 800 : 600, fill: col });
    }
    s += g(tb, { y: (1 - kt) * 130 });
  }

  // ---- Toasts and taps (topmost UI) ----
  s += toast('下载已开始', 540, 1300, prog(t, q.toastDownload, q.toastDownload + 0.16, snap), prog(t, q.label3 - 0.14, q.label3 - 0.02, inCubic));
  s += toast('投稿成功，文件安全检查中', 540, 1440, prog(t, q.toastUpload, q.toastUpload + 0.16, snap), 0);
  s += tap(t, q.tapSearch, CR - 90, SEARCH.cy);
  s += tap(t, q.tapCard, 600, slotY(0));
  s += tap(t, q.tapGet, D.btn.cx + 30, D.btn.cy);
  s += tap(t, q.tapTab, tabX(2), TAB_ICON + 10);
  s += tap(t, q.tapSubmit, U.btn.cx + 40, U.btn.cy);
  return s;
}

// Detail page: M6 shared-element expansion of the hero card, then the M7 download.
function detailPage(t, q) {
  const [e0, e1] = q.cardExpand;
  const k = prog(t, e0, e1, bezier(0.6, 0, 0.25, 1));
  const L = (a, b) => lerp(a, b, k);
  const card = { cx: 540, cy: slotY(0), w: CARD.w, h: CARD.h, r: CARD.r };
  const panel = {
    cx: L(card.cx, PANEL_RECT.cx), cy: L(card.cy, PANEL_RECT.cy), w: L(card.w, PANEL_RECT.w),
    h: L(card.h, PANEL_RECT.h) * (1 + 0.025 * Math.sin(Math.PI * k)), r: L(card.r, PANEL_RECT.r),
  };
  const course = COURSES[HERO_IDX];
  let s = '';
  const halo = 1 - prog(k, 0, 0.3);
  if (halo > 0.01) s += rr({ ...panel, w: panel.w + 16 * halo, h: panel.h + 16 * halo, r: panel.r + 8 * halo }, C.blueSoft);
  if (k < 1) s += rr({ ...panel, cx: panel.cx + 5 * (1 - k), cy: panel.cy + 8 * (1 - k) }, SHADOW);
  s += rr(panel, C.paper);
  // Shared elements: file block, title, tag, price, rating travel from the card into the page.
  const x0 = 540 - CARD.w / 2;
  const blk = { cx: L(x0 + 56, D.block.cx), cy: L(card.cy, D.block.cy), w: L(64, D.block.w), h: L(80, D.block.h), r: L(14, D.block.r) };
  s += rr(blk, course.color);
  s += rr({ cx: blk.cx, cy: blk.cy - blk.h * 0.11, w: blk.w * 0.5, h: blk.h * 0.088, r: blk.h * 0.044 }, 'rgba(255,255,255,0.85)');
  s += rr({ cx: blk.cx, cy: blk.cy + blk.h * 0.11, w: blk.w * 0.5, h: blk.h * 0.088, r: blk.h * 0.044 }, 'rgba(255,255,255,0.85)');
  s += text(HERO_TITLE, L(x0 + 108, D.titleX), L(card.cy - 12, D.titleY), { size: L(32, 38), weight: Math.round(L(800, 900)), fill: C.ink, anchor: 'start' });
  const tsz = L(22, 24);
  const tw = measure(course.tag, tsz, 600) + L(26, 28);
  const tl = L(x0 + 108, D.titleX), tcy = L(card.cy + 32, D.badgeY), th = L(38, 42);
  s += rr({ cx: tl + tw / 2, cy: tcy, w: tw, h: th, r: th / 2 }, '#e8eefc');
  s += text(course.tag, tl + L(13, 14), tcy + tsz * 0.36, { size: tsz, weight: 600, fill: C.blueDeep, anchor: 'start' });
  s += text('免费', L(x0 + 108 + measure(course.tag, 22, 600) + 26 + 16, CL), L(card.cy + 41, D.freeY), { size: L(24, 44), weight: Math.round(L(700, 900)), fill: C.green, anchor: 'start' });
  s += text('评分：4.8', L(x0 + CARD.w - 24, CR), L(card.cy + 40, D.rateY), { size: L(22, 28), weight: Math.round(L(600, 700)), fill: C.meta, anchor: 'end' });
  // Page-only content arrives in a quick stagger.
  const item = (i, str) => {
    const ki = prog(t, e0 + 0.16 + i * 0.045, e0 + 0.4 + i * 0.045, snap);
    return ki > 0 ? g(str, { o: ki, y: (1 - ki) * 26 }) : '';
  };
  s += item(0, rr({ cx: 540, cy: PANEL.top + 18, w: 56, h: 8, r: 4 }, C.line));
  const pw = measure('公开资料', tsz, 600) + L(26, 28);
  const pl = tl + tw + 12;
  const po = prog(k, 0.55, 0.9);
  if (po > 0) s += g(rr({ cx: pl + pw / 2, cy: tcy, w: pw, h: th, r: th / 2 }, C.bg) + text('公开资料', pl + L(13, 14), tcy + tsz * 0.36, { size: tsz, weight: 600, fill: C.muted, anchor: 'start' }), { o: po });
  s += item(1, text('由创作者免费分享', CL, D.shareY, { size: 28, weight: 500, fill: C.muted, anchor: 'start' }));
  let file = rr(D.file, C.bg);
  file += rr({ cx: CL + 38, cy: D.file.cy, w: 36, h: 44, r: 8 }, C.blue);
  file += rr({ cx: CL + 38, cy: D.file.cy - 5, w: 18, h: 4, r: 2 }, C.paper) + rr({ cx: CL + 38, cy: D.file.cy + 5, w: 18, h: 4, r: 2 }, C.paper);
  // Real detail-page row: label "文件", then size · type (materials/[id].tsx: formatFileSize · fileType).
  file += text('文件', CL + 76, D.file.cy + 10, { size: 28, weight: 700, fill: C.ink, anchor: 'start' });
  file += text('1.2 MB · PDF', D.file.cx + D.file.w / 2 - 24, D.file.cy + 10, { size: 26, weight: 500, fill: C.meta, anchor: 'end' });
  s += item(2, file);
  let prev = rr(D.prev, C.indigo);
  prev += noteCard({ cx: 540 + 34, cy: D.prev.cy + 6, w: 190, h: 246, accent: C.blue, lines: 5, tilt: 5, shadow: false, fill: C.bg });
  prev += noteCard({ cx: 540 - 20, cy: D.prev.cy, w: 190, h: 246, accent: C.blue, lines: 5, tilt: -3 });
  s += item(3, prev);

  // Action bar: download tray + the big blue button (M7).
  let bar = '';
  const fd = q.fileDrop;
  const catchB = bump(prog(t, fd[1] - 0.05, fd[1] + 0.3));
  const trayCol = mixColor(C.muted, C.blue, prog(t, fd[1] - 0.04, fd[1] + 0.06));
  bar += g(downloadIcon(D.tray.cx, D.tray.cy, 56, trayCol), { sx: 1 + 0.12 * catchB, sy: 1 - 0.16 * catchB, ox: D.tray.cx, oy: D.tray.cy + 28 });
  const badge = clamp(spring(t - (fd[1] - 0.02), 3.5, 0.45), 0, 1.25);
  if (badge > 0.01) bar += `<circle cx="${D.tray.cx + 24}" cy="${D.tray.cy - 26}" r="${(9 * badge).toFixed(2)}" fill="${C.blue}"/>`;
  bar += m7Button(t, q);
  s += item(4, bar);
  return s;
}

// M7: button -> squash -> progress capsule that fills -> circle with a check; a mini file hops into the tray.
function m7Button(t, q) {
  const B = D.btn;
  const [p0, p1] = q.progress;
  let s = '';
  const press = Math.sin(Math.PI * prog(t, q.tapGet - 0.02, p0 + 0.04));
  const toBar = prog(t, p0, p0 + 0.08, morph);            // capsule 84 -> 24 high
  const fill = prog(t, p0 + 0.05, p1 - 0.08, inOutSine);   // progress
  const toDot = prog(t, p1 - 0.08, p1, morph);             // capsule -> circle
  const pop = bump(prog(t, p1 - 0.01, p1 + 0.3));
  const barH = lerp(B.h, 24, toBar);
  if (toDot <= 0) {
    const sx = 1 + 0.03 * press, sy = 1 - 0.1 * press;
    const track = { cx: B.cx, cy: B.cy, w: B.w, h: barH, r: barH / 2 };
    s += rr({ ...track, cx: B.cx + 5, cy: B.cy + 7 }, SHADOW, { opacity: 1 - toBar });
    s += rr(track, mixColor(C.blue, C.blueSoft, toBar));
    if (fill > 0) {
      const fw = lerp(barH, B.w, fill);
      s += rr({ cx: B.cx - B.w / 2 + fw / 2, cy: B.cy, w: fw, h: barH, r: barH / 2 }, C.blue);
    }
    const lo = 1 - prog(t, p0 - 0.01, p0 + 0.04);
    if (lo > 0) s += text('获取免费链接', B.cx, B.cy + 11, { size: 32, weight: 800, fill: C.paper, o: lo });
    return g(s, { sx, sy, ox: B.cx, oy: B.cy });
  }
  const d = lerp(24, B.h, toDot) * (1 + 0.1 * pop);
  const w = lerp(B.w, B.h, toDot) * (1 + 0.1 * pop) - 0.12 * B.h * pop;
  s += rr({ cx: B.cx, cy: B.cy, w: Math.max(w, d), h: d, r: d / 2 }, C.blue);
  const ck = clamp(spring(t - (p1 - 0.07), 3.4, 0.45), 0, 1.3);
  s += check(B.cx, B.cy, 52, C.paper, ck);
  // Mini file: pops out of the circle, arcs over and drops into the tray.
  const [f0, f1] = q.fileDrop;
  const u = prog(t, f0 + 0.02, f1 - 0.02, bezier(0.3, 0, 0.55, 1));
  if (u > 0 && u < 1) {
    const P0 = { x: B.cx, y: B.cy - 10 }, P1 = { x: (B.cx + D.tray.cx) / 2 + 10, y: B.cy - 190 }, P2 = { x: D.tray.cx, y: D.tray.cy + 6 };
    const x = (1 - u) ** 2 * P0.x + 2 * (1 - u) * u * P1.x + u * u * P2.x;
    const y = (1 - u) ** 2 * P0.y + 2 * (1 - u) * u * P1.y + u * u * P2.y;
    const sc = clamp(u / 0.18) * (1 - 0.5 * prog(u, 0.78, 1));
    s += noteCard({ cx: x, cy: y, w: 56 * sc, h: 72 * sc, fill: C.blue, accent: C.paper, lineColor: C.blueSoft, lines: 3, tilt: lerp(-16, 8, u) });
  }
  return s;
}

function uploadPage(t, q) {
  let s = '';
  s += rr({ cx: 540, cy: (PANEL.top - 10 + SB + 40) / 2, w: SCR.w, h: SB + 50 - PANEL.top, r: 0 }, C.paper);
  s += text('资料标题', CL, U.labelY, { size: 26, weight: 700, fill: C.muted, anchor: 'start' });
  // Title field: focus tint, then the title fills in (one chunk per key sound).
  const [y0, y1] = q.titleType;
  const focus = prog(t, y0 - 0.06, y0 + 0.04) * (1 - prog(t, q.tapSubmit, q.tapSubmit + 0.1));
  s += rr(U.field, mixColor(C.bg, C.indigo, focus));
  const chunks = ['线性', '代数', ' 第三', '章', ' 笔', '记'];
  let typed = '';
  let lastKey = y0;
  for (let j = 0; j < chunks.length; j++) {
    const tj = y0 + j * (y1 - y0) / chunks.length;
    if (t < tj) break;
    lastKey = tj;
    const lead = chunks[j].length - chunks[j].trimStart().length;
    const x = CL + 24 + measure(typed + chunks[j].slice(0, lead), 30, 600);
    const pop = prog(t, tj, tj + 0.08, outCubic);
    s += g(text(chunks[j].trimStart(), x, U.field.cy + 11, { size: 30, weight: 600, fill: C.ink, anchor: 'start' }), { o: clamp(0.45 + pop * 1.6), y: (1 - pop) * 10 });
    typed += chunks[j];
  }
  if (focus > 0.4) {
    const on = t - lastKey < 0.3 || Math.floor((t - lastKey - 0.3) / 0.4) % 2 === 1;
    if (on) s += rr({ cx: CL + 24 + measure(typed, 30, 600) + 3, cy: U.field.cy, w: 3, h: 34 * focus, r: 1.5 }, C.blue);
  }
  // Drop zone: tinted panel; it deepens while the note hovers, the note lands, the label steps down.
  const [n0, n1] = q.noteIn;
  const hover = prog(t, n1 - 0.25, n1 - 0.05) * (1 - prog(t, n1 + 0.05, n1 + 0.35));
  const zb = bump(prog(t, n1 - 0.02, n1 + 0.3));
  s += g(rr(U.zone, mixColor(C.indigo, C.blueSoft, hover)), { sx: 1 + 0.012 * zb, sy: 1 - 0.012 * zb, ox: U.zone.cx, oy: U.zone.cy });
  const iconK = 1 - prog(t, n1 - 0.26, n1 - 0.08, inCubic);
  if (iconK > 0.01) s += g(uploadIcon(U.zone.cx, U.zone.cy - 64, 84, C.blue), { s: iconK, ox: U.zone.cx, oy: U.zone.cy - 64 });
  const down = prog(t, n1 - 0.12, n1 + 0.14, snap);
  s += text('选择 / 拖拽 文件', U.zone.cx, lerp(U.zone.cy + 58, U.zone.cy + 176, down), { size: 30, weight: 700, fill: C.blueDeep });
  // Submit button.
  const press = Math.sin(Math.PI * prog(t, q.tapSubmit - 0.02, q.tapSubmit + 0.12));
  let btn = rr({ ...U.btn, cx: U.btn.cx + 5, cy: U.btn.cy + 7 }, SHADOW);
  btn += rr(U.btn, mixColor(C.blue, C.blueDeep, press));
  btn += text('提交资料', U.btn.cx, U.btn.cy + 11, { size: 32, weight: 800, fill: C.paper });
  s += g(btn, { sx: 1 - 0.02 * press, sy: 1 - 0.08 * press, ox: U.btn.cx, oy: U.btn.cy });
  return s;
}

// ---------- Scene ----------
export function draw(t, cues) {
  const q = cues.s3;
  let s = '';
  const ph = phoneM5(t, q);
  const [o0, o1] = q.phoneOut;

  // Phone: M5 morph, then rest, then it sinks and shrinks away (with a small lift first).
  if (t < o1) {
    const lift = prog(t, o0, o0 + 0.1, outQuad);
    const sink = prog(t, o0 + 0.06, o1, inCubic);
    const dy = -14 * lift * (1 - sink) + 1500 * sink;
    const sOut = 1 - 0.24 * sink;
    let p = '';
    if (ph.shadow > 0) p += rr({ ...ph.body, cx: ph.body.cx + 14 * ph.shadow, cy: ph.body.cy + 20 * ph.shadow }, SHADOW);
    // Side keys peek out of the body once it has formed.
    const keys = prog(ph.k, 0.75, 1);
    if (keys > 0) {
      const bx = ph.body.cx + ph.body.w / 2, by = ph.body.cy - ph.body.h / 2;
      p += rr({ cx: bx + 2 * keys, cy: by + 300, w: 8, h: 120, r: 4 }, C.ink);
      p += rr({ cx: ph.body.cx - ph.body.w / 2 - 2 * keys, cy: by + 250, w: 8, h: 80, r: 4 }, C.ink);
      p += rr({ cx: ph.body.cx - ph.body.w / 2 - 2 * keys, cy: by + 360, w: 8, h: 80, r: 4 }, C.ink);
    }
    p += rr(ph.body, ph.bodyFill);
    const clipD = rr(ph.scr, '#000').match(/d="([^"]+)"/)[1];
    p += `<defs><clipPath id="s3scr"><path d="${clipD}"/></clipPath></defs><g clip-path="url(#s3scr)">${appScreen(t, q, ph)}</g>`;
    if (ph.island > 0.01) {
      const iw = lerp(36, 128, ph.island) * clamp(ph.island * 3);
      const ih = 36 * clamp(ph.island * 3);
      p += rr({ cx: 540, cy: ph.scr.cy - ph.scr.h / 2 + 30, w: iw, h: ih, r: ih / 2 }, C.ink);
    }
    s += g(p, { y: dy, s: sOut, sx: ph.sx * sOut, sy: ph.sy * sOut, rot: ph.rot, ox: ph.body.cx, oy: ph.body.cy });
  }

  // Step labels above the phone.
  s += stepLabels(t, q);

  // M8: ink iris from behind the note.
  const [w0, w1] = q.wipeInk;
  const kw = prog(t, w0, w1 - 0.07, bezier(0.45, 0, 0.2, 1));
  if (kw >= 1) s += `<rect width="1080" height="1920" fill="${C.ink}"/>`;
  else if (kw > 0) s += `<circle cx="${HERO_NOTE.cx}" cy="${HERO_NOTE.cy}" r="${lerp(60, 1160, kw).toFixed(2)}" fill="${C.ink}"/>`;

  // The hero note flies in over the phone, rests in the drop zone, then lifts out to the hero position.
  s += drawNote(noteState(t, q));
  return s;
}
