// Landscape S3 use (7.85-15 s). The full-frame blue field shrinks into a phone on the right while the S2 grid
// reflows into the app's list; a three-step stepper on the left tracks find / get / share (same beats and real
// UI labels as the portrait scene). Then the hero note lifts out of the phone to the frame centre and an ink iris
// takes the frame (S4 hand-off: ink field + heroNoteL()).
import { C, FONT_EN, rr, rrPath, g, text, measure, prog, clamp, lerp, mixColor, spring, snap, bezier, outBack, outCubic, inCubic, inBack, inOutSine, outQuad, botFace, blinkAt, noteCard, rng } from '../../core.js';
import { lockup, lockupMetrics, materialCard, COURSES, GRID, downloadIcon, student, FACE, priceLabel, priceColor } from '../../shared.js';
import { LW, LH, FACE_HEAD_L, LOCK_HEAD_L, GRID_L, gridSlotL, HERO_NOTE_L, heroNoteL } from '../layout.js';
// Namespace import: S2 may or may not export headerL / gridCardsL yet; local copies below are the fallback.
import * as S2 from './s2.js';

export const range = [7.85, 15.0];
export function background() { return C.bg; }

// ---------- Curves ----------
const morph = bezier(0.7, 0, 0.3, 1);     // house morph curve
const shrink = bezier(0.5, 0, 0.22, 1);   // M5 master curve: short cushion, long even shrink, soft landing
const fieldW = bezier(0.58, 0, 0.24, 1);  // field width leads ...
const fieldH = bezier(0.66, 0, 0.3, 1);   // ... height lags: the field goes tall and narrow on the way in
const faceC = bezier(0.36, 0, 0.16, 1);   // the face leads the field's left edge
const deal = bezier(0.6, -0.18, 0.35, 1); // cards: a small pull-back, then deal into the list
const push = bezier(0.62, 0, 0.18, 1);    // page push
const bump = (p) => (p <= 0 || p >= 1 ? 0 : Math.sin(Math.PI * p) * (1 - p) * 1.72); // 0..~1, early peak, decays

// ---------- Phone geometry (at rest), drawn natively for 1920x1080 (UI text 22-34 px) ----------
const PH = { cx: 1290, cy: 548, w: 470, h: 910, r: 66 };
const BZ = 11;
const SCR = { cx: PH.cx, cy: PH.cy, w: PH.w - 2 * BZ, h: PH.h - 2 * BZ, r: PH.r - BZ };
const SL = SCR.cx - SCR.w / 2, SR = SCR.cx + SCR.w / 2, ST = SCR.cy - SCR.h / 2, SB = SCR.cy + SCR.h / 2; // 1066..1514, 104..992
const CL = SL + 22, CR = SR - 22, CW = CR - CL; // content column 1088..1492 (404)
const BAND_B = 290;                              // white app header band: ST..BAND_B
const FACE_BAR = { cx: CL + 24, cy: 184, d: 46 };
const TITLE = { x: CL + 58, y: 195, size: 32 };
const AVATAR = { cx: CR - 19, cy: 184, d: 38 };
const SEARCH = { cx: PH.cx, cy: 248, w: CW, h: 54, r: 27 };
const SEARCH_TX = CL + 50;
const CHIP_Y = 322, CHIP_H = 40;
const CARD = { w: CW, h: 118, r: 20, top: 360, gap: 12 };
const slotY = (i) => CARD.top + CARD.h / 2 + i * (CARD.h + CARD.gap); // 419, 549, 679, 809, 939
const TAB_T = 912, TAB_ICON = 938, TAB_LABEL = 975;
const TABS = ['首页', '资料', '投稿', '求购', '我的'];
const tabX = (i) => SL + SCR.w / 10 + i * SCR.w / 5;
const PANEL = { top: 220, bottom: TAB_T + 30 };
const PANEL_RECT = { cx: PH.cx, cy: (PANEL.top + PANEL.bottom) / 2, w: SCR.w, h: PANEL.bottom - PANEL.top, r: 30 };

// Detail page (at rest).
const D = {
  block: { cx: CL + 34, cy: 296, w: 68, h: 84, r: 14 },
  titleX: CL + 84, titleY: 287,
  badgeY: 330,
  freeY: 404, rateY: 400,
  shareY: 448,
  file: { cx: PH.cx, cy: 502, w: CW, h: 64, r: 16 },
  prev: { cx: PH.cx, cy: 668, w: CW, h: 232, r: 22 },
  btn: { cx: CR - 166, cy: 842, w: 332, h: 66, r: 33 },
  tray: { cx: CL + 30, cy: 840 },
};
// Upload page (at rest).
const U = {
  labelY: 262,
  field: { cx: PH.cx, cy: 306, w: CW, h: 58, r: 18 },
  zone: { cx: PH.cx, cy: 530, w: CW, h: 334, r: 28 },
  btn: { cx: PH.cx, cy: 758, w: CW, h: 66, r: 33 },
};
const NOTE_REST = { cx: PH.cx, cy: 508, w: 124, tilt: -4 };
const HERO_IDX = 2; // COURSES[2] = 概率论 #期末真题
// List rows: grid row 0, columns 0..4, fill the list from the bottom up (column 0 dives deepest), so a card that
// is still waiting in the grid never sits on a slot that is already filled. The hero keeps the middle slot.
const slotOf = (i) => 4 - i;
const HERO_TITLE = '概率论 期末真题';
const RATINGS = ['4.9', '4.7', '4.8', '4.6', '4.9'];
const SHADOW = 'rgba(15,23,42,0.10)';
const GK = GRID_L.w / GRID.w; // materialCard scales its content by w / GRID.w
const LT = 74;                 // list row: text column offset from the card's left edge

// Stepper (left half).
const STEP = { cx: 368, rows: [390, 540, 690], labelX: 448 };
const PILL_A = { w: 100, h: 70, digits: 34 };
const PILL_I = { w: 78, h: 54, digits: 26 };
const LAB_A = { size: 68, weight: 900 };
const LAB_I = { size: 48, weight: 700 };
const rowY = (p) => STEP.rows[0] + p * (STEP.rows[1] - STEP.rows[0]);

const pathD = (s) => rrPath(s.cx, s.cy, s.w, s.h, s.r);

// ---------- Hand-off picture (7.85 s): full blue field + S2 header + S2 grid ----------
// Header lockup exactly as S2 draws it (S2 scales the big lockup into the slot); local copy if S2 lacks the export.
function headLockup() {
  if (typeof S2.headerLockupL === 'function') return S2.headerLockupL();
  const m = lockupMetrics(LOCK_HEAD_L.size);
  return lockup(LOCK_HEAD_L.left + m.w / 2, LOCK_HEAD_L.y, LOCK_HEAD_L.size, { fill: '#ffffff' });
}
function headerLocal() {
  return botFace({ cx: FACE_HEAD_L.cx, cy: FACE_HEAD_L.cy, d: FACE_HEAD_L.d, ring: 4, blink: 1, look: 0, lookY: 0 }) + headLockup();
}
function gridLocal() {
  let s = '';
  for (let i = 0; i < COURSES.length; i++) s += materialCard({ ...gridSlotL(i), w: GRID_L.w, h: GRID_L.h, course: COURSES[i] });
  return s;
}
function handoffIn() {
  const head = typeof S2.headerL === 'function' ? S2.headerL() : headerLocal();
  const grid = typeof S2.gridCardsL === 'function' ? S2.gridCardsL() : gridLocal();
  return `<rect width="${LW}" height="${LH}" fill="${C.blue}"/>` + head + grid;
}

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
  const s = capsuleLine(cx + 7, cy + 7, cx + 15, cy + 15, 6, color) + `<circle cx="${cx}" cy="${cy}" r="13" fill="${color}"/>` + `<circle cx="${cx}" cy="${cy}" r="7.5" fill="${hole}"/>`;
  return g(s, { s: 0.85, ox: cx + 2, oy: cy + 2 });
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
  const tw = measure(str, 24, 700);
  const w = tw + 90, h = 56;
  const left = cx - w / 2;
  let s = rr({ cx: cx + 4, cy: cy + 5, w, h, r: h / 2 }, SHADOW);
  s += rr({ cx, cy, w, h, r: h / 2 }, C.ink);
  s += `<circle cx="${left + 31}" cy="${cy}" r="14" fill="${C.blue}"/>`;
  s += check(left + 31, cy, 25, C.paper);
  s += text(str, left + 56, cy + 8.5, { size: 24, weight: 700, fill: C.paper, anchor: 'start' });
  return g(s, { o: clamp(kIn * 1.4) * (1 - kOut), y: (1 - kIn) * 28 + kOut * 14, s: lerp(0.92, 1, kIn), ox: cx, oy: cy });
}
// Touch indicator: a soft dot that presses at t0, then a ripple.
function tap(t, t0, x, y) {
  if (t < t0 - 0.16 || t > t0 + 0.42) return '';
  const a = prog(t, t0 - 0.16, t0 - 0.03, outCubic);
  const press = Math.sin(Math.PI * prog(t, t0 - 0.03, t0 + 0.09));
  const fade = 1 - prog(t, t0 + 0.05, t0 + 0.18);
  const rp = prog(t, t0, t0 + 0.4, outCubic);
  let s = '';
  if (rp > 0 && rp < 1) s += `<circle cx="${x}" cy="${y}" r="${lerp(24, 72, rp).toFixed(2)}" fill="${C.blue}" opacity="${(0.28 * (1 - rp)).toFixed(3)}"/>`;
  const r = lerp(36, 25, a) * (1 - 0.18 * press);
  if (fade > 0) s += `<circle cx="${x}" cy="${y}" r="${r.toFixed(2)}" fill="${C.ink}" opacity="${(0.2 * a * fade).toFixed(3)}"/>`;
  return s;
}

// ---------- Material card that reflows from the S2 grid card (m = 0, identical to materialCard at GRID_L size) to the list row (m = 1) ----------
function flowCard({ cx, cy, m, course, title = null, rating = '4.8', fill = C.paper, shadow = 1 }) {
  const k = GK;
  const L = (a, b) => lerp(a, b, m);
  const w = L(GRID_L.w, CARD.w), h = L(GRID_L.h, CARD.h);
  const R = L(Math.min(GRID_L.w, GRID_L.h) * 0.11, CARD.r);
  let s = '';
  if (shadow > 0) s += rr({ cx: cx + L(6, 5), cy: cy + L(9, 8), w, h, r: R }, SHADOW);
  s += rr({ cx, cy, w, h, r: R }, fill);
  const x0 = cx - w / 2, y0 = cy - h / 2;
  const gl = x0 + 26 * k; // grid-card content left
  // Title, tag and file block travel continuously; only the price and the rating cross-fade (they change rows).
  const vOut = 1 - prog(m, 0.08, 0.32), vIn = prog(m, 0.62, 0.88);
  // File block.
  const bx = L(gl + 22 * k, x0 + 40), by = L(y0 + 50 * k, cy), bw = L(44 * k, 46), bh = L(54 * k, 58);
  s += rr({ cx: bx, cy: by, w: bw, h: bh, r: L(10 * k, 12) }, course.color);
  s += rr({ cx: bx, cy: L(y0 + 44 * k, cy - 7), w: L(22 * k, 24), h: 5 * L(k, 1), r: 2.5 * L(k, 1) }, 'rgba(255,255,255,0.85)');
  s += rr({ cx: bx, cy: L(y0 + 56 * k, cy + 7), w: L(22 * k, 24), h: 5 * L(k, 1), r: 2.5 * L(k, 1) }, 'rgba(255,255,255,0.85)');
  // Title (the hero card gains its full title as it becomes a list row).
  const tsz = L(32 * k, 26);
  const tx = L(gl + 60 * k, x0 + LT), ty = L(y0 + 62 * k, cy - 14);
  s += text(course.name, tx, ty, { size: tsz, weight: 800, fill: C.ink, anchor: 'start' });
  const sufO = prog(m, 0.45, 0.85);
  if (title && sufO > 0) {
    const suffix = title.slice(course.name.length).trimStart();
    s += text(suffix, tx + measure(title.slice(0, title.length - suffix.length), tsz, 800), ty, { size: tsz, weight: 800, fill: C.ink, anchor: 'start', o: sufO });
  }
  // Tag badge.
  const gsz = L(22 * k, 22);
  const tw = measure(course.tag, gsz, 600) + L(26 * k, 24);
  const tl = L(gl, x0 + LT), tcy = L(cy + 6 * k, cy + 22), th = L(38 * k, 32);
  s += rr({ cx: tl + tw / 2, cy: tcy, w: tw, h: th, r: th / 2 }, '#e8eefc');
  s += text(course.tag, tl + L(13 * k, 12), tcy + 8 * L(k, 1), { size: gsz, weight: 600, fill: C.blueDeep, anchor: 'start' });
  // Price: bottom-left of the grid card, after the tag in the list row.
  if (vOut > 0) s += text(priceLabel(course), gl, cy + h / 2 - 30 * k, { size: 24 * k, weight: 700, fill: priceColor(course), anchor: 'start', o: vOut });
  if (vIn > 0) s += text(priceLabel(course), x0 + LT + tw + 12, cy + 30, { size: 22, weight: 700, fill: priceColor(course), anchor: 'start', o: vIn });
  // Rating: the grey capsule of the grid card becomes the real "评分" text on the title row.
  if (vOut > 0) s += rr({ cx: cx + w / 2 - 66 * k, cy: cy + h / 2 - 38 * k, w: 80 * k, h: 10 * k, r: 5 * k }, C.line, vOut < 1 ? { opacity: vOut } : {});
  if (vIn > 0) s += text('评分：' + rating, x0 + w - 18, cy - 14, { size: 22, weight: 600, fill: C.meta, anchor: 'end', o: vIn });
  return s;
}

// ---------- M5: blue field -> phone ----------
function phoneM5(t, q) {
  const [a, z] = q.toPhone;
  const land = z - 0.02; // the "phone-land" hit in the audio
  const u = prog(t, a, land);
  const k = shrink(u);
  const kw = fieldW(u), kh = fieldH(u);
  const b = bump(prog(t, land - 0.05, z + 0.2));
  const sw = prog(t, land, z + 0.24);
  // A small tilt while it travels (only once the field has left the frame edges), a wobble on landing.
  const rot = -2.2 * Math.sin(Math.PI * u) * prog(kw, 0.05, 0.4) + 0.8 * Math.sin(Math.PI * sw) * (1 - sw);
  const body = {
    cx: lerp(LW / 2, PH.cx, kw),
    cy: lerp(LH / 2, PH.cy, kh),
    w: lerp(LW, PH.w, kw),
    h: lerp(LH, PH.h, kh),
    r: lerp(0, PH.r, clamp(k * 1.3)),
  };
  const bz = BZ * prog(k, 0.12, 0.6);
  const scr = { cx: body.cx, cy: body.cy, w: body.w - 2 * bz, h: body.h - 2 * bz, r: Math.max(0, body.r - bz) };
  const col = prog(k, 0.3, 0.78, inOutSine);
  return {
    u, k, kw, body, scr, rot,
    sx: 1 + 0.025 * b, sy: 1 - 0.036 * b,
    bodyFill: mixColor(C.blue, C.ink, prog(k, 0.12, 0.62)),
    scrFill: mixColor(C.blue, C.bg, col),
    bandFill: mixColor(C.blue, C.paper, col),
    shadow: prog(k, 0.6, 1),
    island: prog(k, 0.55, 0.95, outCubic),
  };
}

// M5 card choreography. Card 5 and grid row 1 fall out through the bottom of the frame first (left to right,
// 1 frame apart, a short hop up first); grid row 0, columns 0..4, is dealt into the list rows (2 frames apart).
const DROP = [5, 6, 7, 8, 9, 10, 11];
const DEAL_ST = 0.067, DEAL_DUR = 0.28;
const DROP_ST = 0.033, DROP_DUR = 0.22;
function dropCard(t, q, i) {
  const a = q.toPhone[0];
  const order = i === 5 ? 0 : i - 6;
  const t0 = a + order * DROP_ST;
  const p = prog(t, t0, t0 + DROP_DUR);
  const gs = gridSlotL(i);
  if (p <= 0) return materialCard({ ...gs, w: GRID_L.w, h: GRID_L.h, course: COURSES[i] });
  if (p >= 1) return '';
  const R = rng(300 + i * 13);
  const side = i === 5 || i === 11 ? 1 : R() < 0.5 ? -1 : 1;
  const hop = Math.sin(Math.PI * prog(p, 0, 0.2)) * 12;
  const fall = (LH + 140 - gs.cy + GRID_L.h / 2) * Math.pow(prog(p, 0.08, 1), 1.8);
  const cx = gs.cx + side * 36 * prog(p, 0.1, 1), cy = gs.cy - hop + fall;
  const rot = side * (3 + 5 * R()) * prog(p, 0.1, 1, inCubic);
  const st = 0.1 * prog(p, 0.35, 0.8); // stretches along the fall
  return g(materialCard({ cx, cy, w: GRID_L.w, h: GRID_L.h, course: COURSES[i] }), { rot, sx: 1 - 0.6 * st, sy: 1 + st, ox: cx, oy: cy });
}
function dealCard(t, q, i) {
  const a = q.toPhone[0];
  const t0 = a + 0.02 + i * DEAL_ST;
  const uc = prog(t, t0, t0 + DEAL_DUR);
  const gs = gridSlotL(i);
  const course = COURSES[i];
  if (uc <= 0) return flowCard({ cx: gs.cx, cy: gs.cy, m: 0, course });
  const title = i === HERO_IDX ? HERO_TITLE : null;
  const kx = snap(clamp(uc * 1.12)); // x leads y: the card is thrown right, then dives into its row
  const ky = deal(uc);
  const m = clamp(ky);
  const ty = slotY(slotOf(i));
  const cx = lerp(gs.cx, PH.cx, kx), cy = lerp(gs.cy, ty, ky);
  // Stretch along the path in proportion to its length; lean into the motion.
  const dist = Math.hypot(PH.cx - gs.cx, ty - gs.cy) / 1230;
  const st = 0.12 * dist * Math.sin(Math.PI * clamp(uc * 1.1));
  const rot = 5 * dist * Math.sin(Math.PI * uc);
  return g(flowCard({ cx, cy, m, course, title, rating: RATINGS[i] }), { rot, sx: 1 + st, sy: 1 - 0.7 * st, ox: cx, oy: cy });
}

// ---------- Stepper: three steps always visible; the active one is ink, large, with a blue pill ----------
function stepper(t, q) {
  const T = [q.label1, q.label2, q.label3];
  const STR = [q.label1Text, q.label2Text, q.label3Text];
  const NUM = ['01', '02', '03'];
  const outT = q.noteLift[0] - 0.1; // 14.0: the stepper clears before the note lifts
  if (t < T[0] - 0.08 || t > outT + 0.45) return '';
  // Active position (labels) and the indicator's two edges (lead edge springs ahead, trail edge follows).
  let act = 0, lead = 0, trail = 0, ant = 0;
  for (let i = 1; i < 3; i++) {
    act += prog(t, T[i] - 0.04, T[i] + 0.22, snap);
    lead += clamp(spring(t - (T[i] - 0.06), 2.3, 0.6), 0, 1.15);
    trail += prog(t, T[i] - 0.01, T[i] + 0.24, bezier(0.5, 0, 0.2, 1));
    ant += Math.sin(Math.PI * prog(t, T[i] - 0.16, T[i] - 0.04));
  }
  const kin = (i) => prog(t, T[0] - 0.02 + i * 0.067, T[0] + 0.48 + i * 0.067, snap);
  const kout = (i) => prog(t, outT + i * 0.05, outT + 0.22 + i * 0.05, inCubic);
  // Pill envelope: a dot pops (spring), stretches to a capsule; at the end it folds back to a dot and goes.
  const env = (i) => {
    const t0 = T[0] - 0.05 + i * 0.067;
    const d = clamp(spring(t - t0, 2.8, 0.5), 0, 1.2) * (1 - prog(t, outT + 0.1 + i * 0.05, outT + 0.24 + i * 0.05, inBack));
    const wk = prog(t, t0 + 0.1, t0 + 0.3, snap) * (1 - prog(t, outT + 0.02 + i * 0.05, outT + 0.12 + i * 0.05, inCubic));
    return { d, wk };
  };
  let s = '';
  // Connector line behind the pills: grows down at the start, fills blue behind the indicator, retracts at the end.
  const cGrow = prog(t, T[0] + 0.05, T[0] + 0.55, snap);
  const cBack = prog(t, outT, outT + 0.22, inCubic);
  const yTop = lerp(STEP.rows[0], STEP.rows[2], cBack), yBot = lerp(STEP.rows[0], STEP.rows[2], cGrow);
  if (yBot - yTop > 1) {
    s += rr({ cx: STEP.cx, cy: (yTop + yBot) / 2, w: 4, h: yBot - yTop, r: 2 }, C.lineStrong);
    const yb = Math.min(yBot, rowY(trail));
    if (yb - yTop > 1) s += rr({ cx: STEP.cx, cy: (yTop + yb) / 2, w: 4, h: yb - yTop, r: 2 }, C.blue);
  }
  // Base pills (upcoming: grey; done: soft blue) with their digits.
  const ai = (i) => clamp(1 - Math.abs(act - i));
  let white = '';
  for (let i = 0; i < 3; i++) {
    const { d, wk } = env(i);
    if (d <= 0.01) continue;
    const a = ai(i);
    const done = clamp(act - i);
    const ph = lerp(PILL_I.h, PILL_A.h, a) * d;
    const pw = lerp(ph, lerp(PILL_I.w, PILL_A.w, a), wk);
    const pill = { cx: STEP.cx, cy: STEP.rows[i], w: pw, h: ph, r: ph / 2 };
    s += rr(pill, mixColor(C.line, C.blueSoft, done));
    const dsz = lerp(PILL_I.digits, PILL_A.digits, a);
    const dO = clamp(wk * 1.5);
    const dig = (fill) => text(NUM[i], STEP.cx, STEP.rows[i] + dsz * 0.36, { size: dsz, weight: 800, family: FONT_EN, fill, ls: 1, o: dO });
    s += g(dig(mixColor(C.meta, C.blue, done)), { s: d, ox: STEP.cx, oy: STEP.rows[i] });
    white += g(dig(C.paper), { s: d, ox: STEP.cx, oy: STEP.rows[i] });
  }
  // The blue indicator: one capsule that bridges rows while it moves (rr family only).
  const e0 = env(0), e2 = env(2);
  const envI = act < 1.5 ? e0 : e2;
  if (envI.d > 0.01) {
    const stretch = clamp(lead - trail);
    const hh = PILL_A.h * envI.d;
    const top = rowY(trail) - hh / 2, bot = rowY(lead) + hh / 2;
    const iw = lerp(hh, PILL_A.w, envI.wk) * (1 - 0.14 * stretch) * (1 + 0.06 * ant);
    const ind = { cx: STEP.cx, cy: (top + bot) / 2, w: iw, h: (bot - top) * (1 - 0.06 * ant), r: Math.min(iw, bot - top) / 2 };
    s += rr(ind, C.blue);
    s += `<defs><clipPath id="L3pill"><path d="${pathD(ind)}"/></clipPath></defs><g clip-path="url(#L3pill)">${white}</g>`;
  }
  // Labels: size, weight and colour follow the active position; mask reveal in, mask wipe out.
  for (let i = 0; i < 3; i++) {
    const ki = kin(i), ko = kout(i);
    if (ki <= 0 || ko >= 1) continue;
    const a = ai(i);
    const size = lerp(LAB_I.size, LAB_A.size, a);
    const weight = Math.round(lerp(LAB_I.weight, LAB_A.weight, a));
    const base = STEP.rows[i] + size * 0.36;
    const dy = (1 - ki) * size * 1.25 - ko * size * 1.25;
    const label = text(STR[i], STEP.labelX, base + dy, { size, weight, fill: mixColor(C.meta, C.ink, a), anchor: 'start' });
    if (ki >= 1 && ko <= 0) { s += label; continue; }
    const id = `L3lab${i}`;
    s += `<defs><clipPath id="${id}"><rect x="${STEP.labelX - 20}" y="${(base - size * 1.08).toFixed(2)}" width="700" height="${(size * 1.45).toFixed(2)}"/></clipPath></defs><g clip-path="url(#${id})">${label}</g>`;
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
    // From off-frame left, over the stepper, down into the drop zone.
    const P0 = { x: -190, y: 250 }, P1 = { x: 640, y: 70 }, P2 = { x: NOTE_REST.cx, y: NOTE_REST.cy };
    const cx = (1 - u) ** 2 * P0.x + 2 * (1 - u) * u * P1.x + u * u * P2.x;
    const cy = (1 - u) ** 2 * P0.y + 2 * (1 - u) * u * P1.y + u * u * P2.y;
    const vx = 2 * (1 - u) * (P1.x - P0.x) + 2 * u * (P2.x - P1.x);
    const vy = 2 * (1 - u) * (P1.y - P0.y) + 2 * u * (P2.y - P1.y);
    return {
      cx, cy, w: lerp(176, NOTE_REST.w, u), tilt: lerp(-18, NOTE_REST.tilt, u) + 14 * Math.sin(Math.PI * u),
      ang: Math.atan2(vy, vx) * 180 / Math.PI, stretch: 0.12 * Math.sin(Math.PI * Math.min(1, u * 1.15)),
    };
  }
  const land = bump(prog(t, n1 - 0.02, n1 + 0.3));
  if (t < l0) return { ...NOTE_REST, land };
  // Lift: a small dip, then up and out of the phone to the hero size at the frame centre, straightening.
  const dip = Math.sin(Math.PI * prog(t, l0, l0 + 0.1));
  const x = prog(t, l0 + 0.05, l1);
  const e = outBack(x, 1.3);
  const p = snap(x);
  return {
    cx: lerp(NOTE_REST.cx, HERO_NOTE_L.cx, p),
    cy: lerp(NOTE_REST.cy, HERO_NOTE_L.cy, p) - 60 * Math.sin(Math.PI * p) + 8 * dip,
    w: lerp(NOTE_REST.w, HERO_NOTE_L.w, e),
    tilt: lerp(NOTE_REST.tilt, 0, p),
    land: 0.6 * dip,
  };
}
function drawNote(ns) {
  if (!ns) return '';
  if (ns.hero) return heroNoteL();
  const w = ns.w, h = w * (HERO_NOTE_L.h / HERO_NOTE_L.w);
  let s = noteCard({ cx: ns.cx, cy: ns.cy, w, h, accent: HERO_NOTE_L.accent, lines: HERO_NOTE_L.lines, tilt: ns.tilt });
  if (ns.stretch) {
    const a = ns.ang, st = ns.stretch;
    s = `<g transform="translate(${ns.cx.toFixed(2)} ${ns.cy.toFixed(2)}) rotate(${a.toFixed(2)}) scale(${(1 + st).toFixed(3)} ${(1 - st * 0.8).toFixed(3)}) rotate(${(-a).toFixed(2)}) translate(${(-ns.cx).toFixed(2)} ${(-ns.cy).toFixed(2)})">${s}</g>`;
  }
  if (ns.land) s = g(s, { sx: 1 + 0.1 * ns.land, sy: 1 - 0.13 * ns.land, ox: ns.cx, oy: ns.cy + h / 2 });
  return s;
}

// ---------- The app inside the phone (final-layout coordinates) ----------
function appScreen(t, q, ph) {
  const [a] = q.toPhone;
  const land = q.toPhone[1] - 0.02;
  const m5 = t < land + 0.02;
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
      const sf = { cx: CL + sw / 2, cy: SEARCH.cy, w: sw, h: SEARCH.h * kd, r: SEARCH.r * kd };
      const fieldFill = mixColor(C.bg, C.paper, focus);
      if (focus > 0) s += rr({ ...sf, w: sf.w + 5 * focus, h: sf.h + 5 * focus, r: sf.r + 2.5 * focus }, C.blue);
      s += rr(sf, fieldFill);
      s += g(searchIcon(CL + 26, SEARCH.cy - 2, C.meta, fieldFill), { s: clamp(kd), ox: CL + 28, oy: SEARCH.cy });
      // Placeholder until the first key, then the typed query with a caret.
      const keys = q.typeKeys;
      const phO = prog(t, land - 0.06, land + 0.04) * (1 - prog(t, keys[0] - 0.04, keys[0]));
      if (phO > 0) s += text('搜课程 / 资料名 / 标签', SEARCH_TX, SEARCH.cy + 8.5, { size: 24, weight: 500, fill: C.meta, anchor: 'start', o: phO });
      const glyphs = Array.from(q.typed);
      let n = 0;
      for (let i = 0; i < glyphs.length; i++) {
        const kt = t - keys[i];
        if (kt < 0) break;
        n = i + 1;
        if (glyphs[i] === ' ') continue;
        const x = SEARCH_TX + measure(glyphs.slice(0, i).join(''), 26, 600);
        const pop = prog(kt, 0, 0.1, outCubic);
        s += g(text(glyphs[i], x, SEARCH.cy + 9.5, { size: 26, weight: 600, fill: C.ink, anchor: 'start' }), { s: lerp(1.3, 1, pop), o: clamp(0.45 + pop * 1.6), ox: x + 13, oy: SEARCH.cy });
      }
      if (focus > 0.4 && t < q.cardExpand[0]) {
        const cx = SEARCH_TX + measure(glyphs.slice(0, n).join(''), 26, 600) + 3;
        const lastKey = n > 0 ? q.typeKeys[n - 1] : q.tapSearch;
        const on = t - lastKey < 0.3 || Math.floor((t - lastKey - 0.3) / 0.4) % 2 === 1;
        if (on) s += rr({ cx, cy: SEARCH.cy, w: 3, h: 30 * focus, r: 1.5 }, C.blue);
      }
    }

    // Chips.
    const chips = ['全部', '免费', '付费', '#期末真题'];
    let cxp = CL;
    for (let j = 0; j < chips.length; j++) {
      const cw = measure(chips[j], 22, 600) + 30;
      const kc = clamp(spring(t - (land + 0.03 + j * 0.05), 3.4, 0.5), 0, 1.2);
      if (kc > 0.01) {
        let act = 0;
        if (j === 0) act = 1 - prog(t, q.chip, q.chip + 0.1);
        if (j === 3) act = prog(t, q.chip, q.chip + 0.08);
        const pop = j === 3 ? 0.12 * bump(prog(t, q.chip, q.chip + 0.3)) : 0;
        const c = { cx: cxp + cw / 2, cy: CHIP_Y, w: cw, h: CHIP_H, r: CHIP_H / 2 };
        let chip = rr(c, mixColor(C.paper, C.blue, act));
        chip += text(chips[j], c.cx, CHIP_Y + 8, { size: 22, weight: 600, fill: mixColor(C.muted, C.paper, act) });
        s += g(chip, { s: kc * (1 + pop), o: clamp(kc * 2), ox: c.cx, oy: CHIP_Y });
      }
      cxp += cw + 10;
    }

    // List cards: during M5 the grid reflows (drops first, deals on top); then the reshuffle lifts the hero.
    if (m5) {
      for (const i of DROP) s += dropCard(t, q, i);
      for (let i = 0; i <= 4; i++) s += dealCard(t, q, i); // later launches on top
    } else {
      const rs = q.reshuffle;
      const kHero = prog(t, rs[0], rs[1] - 0.03, bezier(0.5, 0, 0.2, 1));
      const dim = prog(t, rs[0] + 0.05, rs[1], snap);
      const drawCard = (i) => {
        const course = COURSES[i];
        const title = i === HERO_IDX ? HERO_TITLE : null;
        const sl = slotOf(i);
        let cy = slotY(sl), cx = PH.cx, sc = 1, o = 1, halo = 0;
        if (i === HERO_IDX) {
          cy = lerp(slotY(sl), slotY(0), kHero);
          cx = PH.cx + 12 * Math.sin(Math.PI * kHero);
          sc = 1 + 0.03 * Math.sin(Math.PI * kHero);
          halo = clamp(spring(t - (rs[1] - 0.1), 3, 0.55), 0, 1.15);
          sc *= 1 - 0.035 * Math.sin(Math.PI * prog(t, q.tapCard - 0.04, q.cardExpand[0]));
        } else {
          // The two cards above the hero step down one slot each.
          const delay = sl === 0 ? 0.04 : sl === 1 ? 0.08 : 0;
          const ks = prog(t, rs[0] + delay, rs[1] + delay * 0.5, snap);
          if (sl < 2) cy = lerp(slotY(sl), slotY(sl + 1), ks);
          o = 1 - 0.5 * dim;
        }
        let c = '';
        if (halo > 0.01) c += rr({ cx, cy, w: CARD.w + 14 * halo, h: CARD.h + 14 * halo, r: CARD.r + 7 * halo }, C.blueSoft);
        c += flowCard({ cx, cy, m: 1, course, title, rating: RATINGS[i] });
        return g(c, { s: sc, o, ox: cx, oy: cy });
      };
      for (let i = 0; i <= 4; i++) if (i !== HERO_IDX) s += drawCard(i); // bottom slot first
      if (t < q.cardExpand[0]) s += drawCard(HERO_IDX);
    }
  }

  // ---- Detail page (M6: the hero card grows into it) and the M7 download ----
  if (t >= q.cardExpand[0] && kU < 1) s += g(detailPage(t, q), { x: oldX });

  // ---- Upload page (pushed in from the right) ----
  if (kU > 0) s += g(uploadPage(t, q), { x: newX });

  // ---- Top bar: bot face (from the S2 header), page title, avatar ----
  const kf = faceC(prog(t, a + 0.01, land - 0.05));
  if (m5 && kf < 1) {
    const arc = 46 * Math.sin(Math.PI * kf);
    const fx = lerp(FACE_HEAD_L.cx, FACE_BAR.cx, kf), fy = lerp(FACE_HEAD_L.cy, FACE_BAR.cy, kf) - arc;
    const fd = lerp(FACE_HEAD_L.d, FACE_BAR.d, kf);
    const sq = 0.08 * Math.sin(Math.PI * kf); // stretched along the (horizontal) move
    s += g(botFace({ cx: fx, cy: fy, d: fd, ring: 4 * (1 - kf), blink: 1, look: 0.7 * Math.sin(Math.PI * kf) }), { sx: 1 + sq, sy: 1 - sq, ox: fx, oy: fy });
    // The white lockup rides along and fades as the header becomes the app bar.
    const lo = 1 - prog(kf, 0.02, 0.4);
    if (lo > 0) {
      const inner = headLockup();
      s += kf > 0 ? g(inner, { x: fx - FACE_HEAD_L.cx, y: fy - FACE_HEAD_L.cy, s: lerp(1, 0.8, kf), o: lo, ox: LOCK_HEAD_L.left, oy: LOCK_HEAD_L.y - 14 }) : inner;
    }
  } else {
    // Bot face lives in the app bar: one blink, and it watches the note fly in (from the upper left, then down).
    const [n0, n1] = q.noteIn;
    const lookL = prog(t, n0 - 0.05, n0 + 0.15, outCubic) * (1 - prog(t, n1 - 0.25, n1 - 0.05, outCubic));
    const lookD = prog(t, n1 - 0.2, n1, outCubic) * (1 - prog(t, n1 + 0.5, n1 + 0.75, outCubic));
    const blink = blinkAt(t, q.tapGet - 0.3) * blinkAt(t, q.noteLift[0] - 0.35);
    s += botFace({ cx: FACE_BAR.cx, cy: FACE_BAR.cy, d: FACE_BAR.d, blink, look: -0.9 * lookL + 0.5 * lookD, lookY: -0.6 * lookL + 0.8 * lookD });
  }
  const tIn = prog(t, land - 0.2, land, outCubic);
  const tSw = prog(t, q.toUpload[0] + 0.02, q.toUpload[0] + 0.26, push);
  if (tIn > 0) {
    const tOut = prog(tSw, 0, 0.4), tNew = prog(tSw, 0.35, 1);
    s += text('资料库', TITLE.x, TITLE.y + (1 - tIn) * 16 - 18 * tOut, { size: TITLE.size, weight: 900, fill: C.ink, anchor: 'start', o: tIn * (1 - tOut) });
    if (tNew > 0) s += text('投稿工作台', TITLE.x, TITLE.y + 18 * (1 - tNew), { size: TITLE.size, weight: 900, fill: C.ink, anchor: 'start', o: tNew });
  }
  const ka = clamp(spring(t - (land + 0.02), 3, 0.5), 0, 1.2);
  if (ka > 0.01) s += g(student({ cx: AVATAR.cx, cy: AVATAR.cy, d: AVATAR.d, color: FACE.sky }), { s: ka, ox: AVATAR.cx, oy: AVATAR.cy });

  // ---- Tab bar ----
  const kt = prog(t, land - 0.08, land + 0.14, snap);
  if (kt > 0) {
    let tb = rr({ cx: PH.cx, cy: (TAB_T + SB + 40) / 2 - 3, w: SCR.w, h: SB + 40 - TAB_T, r: 0 }, SHADOW);
    tb += rr({ cx: PH.cx, cy: (TAB_T + SB + 40) / 2, w: SCR.w, h: SB + 40 - TAB_T, r: 0 }, C.paper);
    const sw = prog(t, q.tapTab, q.tapTab + 0.08);
    for (let i = 0; i < 5; i++) {
      const act = i === 1 ? 1 - sw : i === 2 ? sw : 0;
      const col = mixColor(C.meta, C.blue, act);
      const pop = i === 2 ? 0.18 * bump(prog(t, q.tapTab, q.tapTab + 0.3)) : 0;
      tb += g(tabIcon(i, tabX(i), TAB_ICON, col), { s: 0.8 * (1 + pop), ox: tabX(i), oy: TAB_ICON });
      tb += text(TABS[i], tabX(i), TAB_LABEL, { size: 22, weight: act > 0.5 ? 800 : 600, fill: col });
    }
    s += g(tb, { y: (1 - kt) * 110 });
  }

  // ---- Toasts and taps (topmost UI) ----
  s += toast('下载已开始', PH.cx, 750, prog(t, q.toastDownload, q.toastDownload + 0.16, snap), prog(t, q.label3 - 0.14, q.label3 - 0.02, inCubic));
  s += toast('投稿成功，文件安全检查中', PH.cx, 846, prog(t, q.toastUpload, q.toastUpload + 0.16, snap), 0);
  s += tap(t, q.tapSearch, CR - 70, SEARCH.cy);
  s += tap(t, q.tapCard, PH.cx + 40, slotY(0));
  s += tap(t, q.tapGet, D.btn.cx + 24, D.btn.cy);
  s += tap(t, q.tapTab, tabX(2), TAB_ICON + 8);
  s += tap(t, q.tapSubmit, U.btn.cx + 30, U.btn.cy);
  return s;
}

// Detail page: M6 shared-element expansion of the hero card, then the M7 download.
function detailPage(t, q) {
  const [e0, e1] = q.cardExpand;
  const k = prog(t, e0, e1, bezier(0.6, 0, 0.25, 1));
  const L = (a, b) => lerp(a, b, k);
  const card = { cx: PH.cx, cy: slotY(0), w: CARD.w, h: CARD.h, r: CARD.r };
  const panel = {
    cx: L(card.cx, PANEL_RECT.cx), cy: L(card.cy, PANEL_RECT.cy), w: L(card.w, PANEL_RECT.w),
    h: L(card.h, PANEL_RECT.h) * (1 + 0.025 * Math.sin(Math.PI * k)), r: L(card.r, PANEL_RECT.r),
  };
  const course = COURSES[HERO_IDX];
  let s = '';
  const halo = 1 - prog(k, 0, 0.3);
  if (halo > 0.01) s += rr({ ...panel, w: panel.w + 14 * halo, h: panel.h + 14 * halo, r: panel.r + 7 * halo }, C.blueSoft);
  if (k < 1) s += rr({ ...panel, cx: panel.cx + 5 * (1 - k), cy: panel.cy + 8 * (1 - k) }, SHADOW);
  s += rr(panel, C.paper);
  // Shared elements: file block, title, tag, price, rating travel from the card into the page.
  const x0 = PH.cx - CARD.w / 2;
  const blk = { cx: L(x0 + 40, D.block.cx), cy: L(card.cy, D.block.cy), w: L(46, D.block.w), h: L(58, D.block.h), r: L(12, D.block.r) };
  s += rr(blk, course.color);
  s += rr({ cx: blk.cx, cy: blk.cy - blk.h * 0.11, w: blk.w * 0.5, h: blk.h * 0.088, r: blk.h * 0.044 }, 'rgba(255,255,255,0.85)');
  s += rr({ cx: blk.cx, cy: blk.cy + blk.h * 0.11, w: blk.w * 0.5, h: blk.h * 0.088, r: blk.h * 0.044 }, 'rgba(255,255,255,0.85)');
  s += text(HERO_TITLE, L(x0 + LT, D.titleX), L(card.cy - 14, D.titleY), { size: L(26, 30), weight: Math.round(L(800, 900)), fill: C.ink, anchor: 'start' });
  const tsz = 22;
  const tw = measure(course.tag, tsz, 600) + L(24, 26);
  const tl = L(x0 + LT, D.titleX), tcy = L(card.cy + 22, D.badgeY), th = L(32, 34);
  s += rr({ cx: tl + tw / 2, cy: tcy, w: tw, h: th, r: th / 2 }, '#e8eefc');
  s += text(course.tag, tl + L(12, 13), tcy + 8, { size: tsz, weight: 600, fill: C.blueDeep, anchor: 'start' });
  // 免费 travels on a downward arc under the rising tag badge (it starts beside the tag and ends below it).
  const fxK = prog(k, 0.1, 1);
  s += text('免费', lerp(x0 + LT + measure(course.tag, 22, 600) + 24 + 12, CL, fxK), L(card.cy + 30, D.freeY) + 52 * Math.sin(Math.PI * k) * (1 - k), { size: L(22, 34), weight: Math.round(L(700, 900)), fill: C.green, anchor: 'start' });
  s += text('评分：4.8', L(x0 + CARD.w - 18, CR), L(card.cy - 14, D.rateY), { size: L(22, 24), weight: Math.round(L(600, 700)), fill: C.meta, anchor: 'end' });
  // Page-only content arrives in a quick stagger.
  const item = (i, str) => {
    const ki = prog(t, e0 + 0.16 + i * 0.045, e0 + 0.4 + i * 0.045, snap);
    return ki > 0 ? g(str, { o: ki, y: (1 - ki) * 22 }) : '';
  };
  s += item(0, rr({ cx: PH.cx, cy: PANEL.top + 14, w: 48, h: 7, r: 3.5 }, C.line));
  const pw = measure('公开资料', tsz, 600) + L(24, 26);
  const pl = tl + tw + 10;
  const po = prog(k, 0.55, 0.9);
  if (po > 0) s += g(rr({ cx: pl + pw / 2, cy: tcy, w: pw, h: th, r: th / 2 }, C.bg) + text('公开资料', pl + L(12, 13), tcy + 8, { size: tsz, weight: 600, fill: C.muted, anchor: 'start' }), { o: po });
  s += item(1, text('由创作者免费分享', CL, D.shareY, { size: 24, weight: 500, fill: C.muted, anchor: 'start' }));
  let file = rr(D.file, C.bg);
  file += rr({ cx: CL + 30, cy: D.file.cy, w: 30, h: 38, r: 7 }, C.blue);
  file += rr({ cx: CL + 30, cy: D.file.cy - 4.5, w: 15, h: 3.5, r: 1.75 }, C.paper) + rr({ cx: CL + 30, cy: D.file.cy + 4.5, w: 15, h: 3.5, r: 1.75 }, C.paper);
  // Real detail-page row: label "文件", then size · type (materials/[id].tsx: formatFileSize · fileType).
  file += text('文件', CL + 60, D.file.cy + 8.5, { size: 24, weight: 700, fill: C.ink, anchor: 'start' });
  file += text('1.2 MB · PDF', D.file.cx + D.file.w / 2 - 20, D.file.cy + 8, { size: 22, weight: 500, fill: C.meta, anchor: 'end' });
  s += item(2, file);
  let prev = rr(D.prev, C.indigo);
  prev += noteCard({ cx: PH.cx + 26, cy: D.prev.cy + 5, w: 134, h: 174, accent: C.blue, lines: 5, tilt: 5, shadow: false, fill: C.bg });
  prev += noteCard({ cx: PH.cx - 16, cy: D.prev.cy, w: 134, h: 174, accent: C.blue, lines: 5, tilt: -3 });
  s += item(3, prev);

  // Action bar: download tray + the big blue button (M7).
  let bar = '';
  const fd = q.fileDrop;
  const catchB = bump(prog(t, fd[1] - 0.05, fd[1] + 0.3));
  const trayCol = mixColor(C.muted, C.blue, prog(t, fd[1] - 0.04, fd[1] + 0.06));
  bar += g(downloadIcon(D.tray.cx, D.tray.cy, 46, trayCol), { sx: 1 + 0.12 * catchB, sy: 1 - 0.16 * catchB, ox: D.tray.cx, oy: D.tray.cy + 23 });
  const badge = clamp(spring(t - (fd[1] - 0.02), 3.5, 0.45), 0, 1.25);
  if (badge > 0.01) bar += `<circle cx="${D.tray.cx + 20}" cy="${D.tray.cy - 22}" r="${(8 * badge).toFixed(2)}" fill="${C.blue}"/>`;
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
  const toBar = prog(t, p0, p0 + 0.08, morph);            // capsule 66 -> 20 high
  const fill = prog(t, p0 + 0.05, p1 - 0.08, inOutSine);   // progress
  const toDot = prog(t, p1 - 0.08, p1, morph);             // capsule -> circle
  const pop = bump(prog(t, p1 - 0.01, p1 + 0.3));
  const barH = lerp(B.h, 20, toBar);
  if (toDot <= 0) {
    const sx = 1 + 0.03 * press, sy = 1 - 0.1 * press;
    const track = { cx: B.cx, cy: B.cy, w: B.w, h: barH, r: barH / 2 };
    s += rr({ ...track, cx: B.cx + 4, cy: B.cy + 6 }, SHADOW, { opacity: 1 - toBar });
    s += rr(track, mixColor(C.blue, C.blueSoft, toBar));
    if (fill > 0) {
      const fw = lerp(barH, B.w, fill);
      s += rr({ cx: B.cx - B.w / 2 + fw / 2, cy: B.cy, w: fw, h: barH, r: barH / 2 }, C.blue);
    }
    const lo = 1 - prog(t, p0 - 0.01, p0 + 0.04);
    if (lo > 0) s += text('获取免费链接', B.cx, B.cy + 10, { size: 28, weight: 800, fill: C.paper, o: lo });
    return g(s, { sx, sy, ox: B.cx, oy: B.cy });
  }
  const d = lerp(20, B.h, toDot) * (1 + 0.1 * pop);
  const w = lerp(B.w, B.h, toDot) * (1 + 0.1 * pop) - 0.12 * B.h * pop;
  s += rr({ cx: B.cx, cy: B.cy, w: Math.max(w, d), h: d, r: d / 2 }, C.blue);
  const ck = clamp(spring(t - (p1 - 0.07), 3.4, 0.45), 0, 1.3);
  s += check(B.cx, B.cy, 42, C.paper, ck);
  // Mini file: pops out of the circle, arcs over and drops into the tray.
  const [f0, f1] = q.fileDrop;
  const u = prog(t, f0 + 0.02, f1 - 0.02, bezier(0.3, 0, 0.55, 1));
  if (u > 0 && u < 1) {
    const P0 = { x: B.cx, y: B.cy - 8 }, P1 = { x: (B.cx + D.tray.cx) / 2 + 8, y: B.cy - 150 }, P2 = { x: D.tray.cx, y: D.tray.cy + 5 };
    const x = (1 - u) ** 2 * P0.x + 2 * (1 - u) * u * P1.x + u * u * P2.x;
    const y = (1 - u) ** 2 * P0.y + 2 * (1 - u) * u * P1.y + u * u * P2.y;
    const sc = clamp(u / 0.18) * (1 - 0.5 * prog(u, 0.78, 1));
    s += noteCard({ cx: x, cy: y, w: 46 * sc, h: 60 * sc, fill: C.blue, accent: C.paper, lineColor: C.blueSoft, lines: 3, tilt: lerp(-16, 8, u) });
  }
  return s;
}

function uploadPage(t, q) {
  let s = '';
  s += rr({ cx: PH.cx, cy: (PANEL.top - 10 + SB + 40) / 2, w: SCR.w, h: SB + 50 - PANEL.top, r: 0 }, C.paper);
  s += text('资料标题', CL, U.labelY, { size: 24, weight: 700, fill: C.muted, anchor: 'start' });
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
    const x = CL + 20 + measure(typed + chunks[j].slice(0, lead), 26, 600);
    const pop = prog(t, tj, tj + 0.08, outCubic);
    s += g(text(chunks[j].trimStart(), x, U.field.cy + 9.5, { size: 26, weight: 600, fill: C.ink, anchor: 'start' }), { o: clamp(0.45 + pop * 1.6), y: (1 - pop) * 9 });
    typed += chunks[j];
  }
  if (focus > 0.4) {
    const on = t - lastKey < 0.3 || Math.floor((t - lastKey - 0.3) / 0.4) % 2 === 1;
    if (on) s += rr({ cx: CL + 20 + measure(typed, 26, 600) + 3, cy: U.field.cy, w: 3, h: 30 * focus, r: 1.5 }, C.blue);
  }
  // Drop zone: tinted panel; it deepens while the note hovers, the note lands, the label steps down.
  const [, n1] = q.noteIn;
  const hover = prog(t, n1 - 0.25, n1 - 0.05) * (1 - prog(t, n1 + 0.05, n1 + 0.35));
  const zb = bump(prog(t, n1 - 0.02, n1 + 0.3));
  s += g(rr(U.zone, mixColor(C.indigo, C.blueSoft, hover)), { sx: 1 + 0.012 * zb, sy: 1 - 0.012 * zb, ox: U.zone.cx, oy: U.zone.cy });
  const iconK = 1 - prog(t, n1 - 0.26, n1 - 0.08, inCubic);
  if (iconK > 0.01) s += g(uploadIcon(U.zone.cx, U.zone.cy - 40, 68, C.blue), { s: iconK, ox: U.zone.cx, oy: U.zone.cy - 40 });
  const down = prog(t, n1 - 0.12, n1 + 0.14, snap);
  s += text('选择 / 拖拽 文件', U.zone.cx, lerp(U.zone.cy + 50, U.zone.cy + 138, down), { size: 26, weight: 700, fill: C.blueDeep });
  // Submit button.
  const press = Math.sin(Math.PI * prog(t, q.tapSubmit - 0.02, q.tapSubmit + 0.12));
  let btn = rr({ ...U.btn, cx: U.btn.cx + 4, cy: U.btn.cy + 6 }, SHADOW);
  btn += rr(U.btn, mixColor(C.blue, C.blueDeep, press));
  btn += text('提交资料', U.btn.cx, U.btn.cy + 10, { size: 28, weight: 800, fill: C.paper });
  s += g(btn, { sx: 1 - 0.02 * press, sy: 1 - 0.08 * press, ox: U.btn.cx, oy: U.btn.cy });
  return s;
}

// ---------- Scene ----------
export function draw(t, cues) {
  const q = cues.s3;
  // Hand-off frame: exactly the picture S2 ends on.
  if (t <= q.toPhone[0]) return handoffIn();
  let s = '';
  const ph = phoneM5(t, q);
  const [o0, o1] = q.phoneOut;

  // Phone: M5 morph, then rest, then a small lift and it sinks out of the frame (shrinking a little).
  if (t < o1) {
    const lift = prog(t, o0, o0 + 0.1, outQuad);
    const sink = prog(t, o0 + 0.06, o1, inCubic);
    const dy = -12 * lift * (1 - sink) + 1060 * sink;
    const sOut = 1 - 0.22 * sink;
    let p = '';
    if (ph.shadow > 0) p += rr({ ...ph.body, cx: ph.body.cx + 12 * ph.shadow, cy: ph.body.cy + 16 * ph.shadow }, SHADOW);
    // Side keys peek out of the body once it has formed.
    const keys = prog(ph.k, 0.75, 1);
    if (keys > 0) {
      const bx = ph.body.cx + ph.body.w / 2, by = ph.body.cy - ph.body.h / 2;
      p += rr({ cx: bx + 2 * keys, cy: by + 228, w: 7, h: 92, r: 3.5 }, C.ink);
      p += rr({ cx: ph.body.cx - ph.body.w / 2 - 2 * keys, cy: by + 190, w: 7, h: 60, r: 3.5 }, C.ink);
      p += rr({ cx: ph.body.cx - ph.body.w / 2 - 2 * keys, cy: by + 272, w: 7, h: 60, r: 3.5 }, C.ink);
    }
    p += rr(ph.body, ph.bodyFill);
    p += `<defs><clipPath id="L3scr"><path d="${pathD(ph.scr)}"/></clipPath></defs><g clip-path="url(#L3scr)">${appScreen(t, q, ph)}</g>`;
    if (ph.island > 0.01) {
      const iw = lerp(28, 96, ph.island) * clamp(ph.island * 3);
      const ih = 28 * clamp(ph.island * 3);
      p += rr({ cx: ph.body.cx, cy: ph.scr.cy - ph.scr.h / 2 + 22, w: iw, h: ih, r: ih / 2 }, C.ink);
    }
    s += g(p, { y: dy, sx: ph.sx * sOut, sy: ph.sy * sOut, rot: ph.rot, ox: ph.body.cx, oy: ph.body.cy });
  }

  // Stepper on the left.
  s += stepper(t, q);

  // M8: ink iris from behind the note.
  const [w0, w1] = q.wipeInk;
  const kw = prog(t, w0, w1 - 0.07, bezier(0.45, 0, 0.2, 1));
  if (kw >= 1) s += `<rect width="${LW}" height="${LH}" fill="${C.ink}"/>`;
  else if (kw > 0) s += `<circle cx="${HERO_NOTE_L.cx}" cy="${HERO_NOTE_L.cy}" r="${lerp(60, 1140, kw).toFixed(2)}" fill="${C.ink}"/>`;

  // The hero note flies in over the stepper, rests in the drop zone, then lifts out to the frame centre.
  s += drawNote(noteState(t, q));
  return s;
}
