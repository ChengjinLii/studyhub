// S5 data (20-26 s): StudyHub's historical figures land row by row (icon pops, number counts, "+" spins in),
// hold for reading, then the text slides away and the three icons fly in on arcs and merge into the hero note (M11).
import { C, FONT_CN, FONT_EN, W, rr, rrLerp, g, text, measure, prog, clamp, lerp, spring, snap, bezier, outCubic, inQuad, outBack, botFace, num } from '../core.js';
import { DATA, FACES_ICON, facesIcon, heroNote, HERO_NOTE } from '../shared.js';

export const range = [20.0, 26.0];
export function background() { return C.bg; }

// ---------- Layout ----------
// The unit sits UNDER the number. Inline ("1800+ 次资料下载" on one baseline) does not fit at hero size:
// at 160/52 px it needs 352 + 500 + 18 + 260 = 1130 > 960, and fitting x <= 960 forces ~118 px numbers.
const L = { num: 160, unit: 52, numBase: 22, unitBase: 104 };
const PLUS = 0.72;               // "+" size relative to the number
const LEFT = 152;                // left edge shared by the kicker and the footnote (the faces icon's left edge)
const RIGHT = 952;               // shared right edge: pill, dividers and footnote end here
const KICK = { size: 64, h: 110, padX: 41 };
const FOOT = 34;
const NOTE_ICON = { w: 112, h: 146, tilt: -5 };
const DL = 124;                  // download icon size
const BRIDGE = 124;              // the circle every icon passes through before the hero note

const morph = bezier(0.7, 0, 0.3, 1);
const landEase = (x) => outBack(Math.pow(x, 1.4), 0.9); // soft start, ~3% overshoot, zero speed at the end

// Damped wobble (0 at t0, decays): used for squash pulses and landings.
function boing(t, t0, freq = 2.6, decay = 7) {
  const x = t - t0;
  if (x <= 0) return 0;
  return Math.exp(-decay * x) * Math.sin(2 * Math.PI * freq * x);
}

let clipN = 0;
function clipRect(content, x, y, w, h) {
  if (!content) return '';
  const id = `s5c${clipN++}`;
  return `<defs><clipPath id="${id}"><rect x="${num(x)}" y="${num(y)}" width="${num(w)}" height="${num(h)}"/></clipPath></defs><g clip-path="url(#${id})">${content}</g>`;
}

function rowTimes(q, i) {
  const r = q.rows[i];
  const c0 = r.t + q.countDelay;
  return { t0: r.t, c0, c1: c0 + q.count };
}

// Exit schedule (M11), all derived from cues.s5.out (0.55 s = 16 frames).
// Text clears first (each row slides left into its icon), then the icons fly in top to bottom, then the bridge circle opens into the hero note.
function exitPlan(q) {
  const [a, z] = q.out;
  return {
    a, z,
    text: [a, a, a + 0.05, a + 0.1, a + 0.12],  // kicker, row 0, row 1, row 2, footnote
    textDur: 0.17,
    fly: { faces: [a + 0.1, a + 0.34], note: [a + 0.14, a + 0.35], dl: [a + 0.18, a + 0.4] },
    expand: [a + 0.29, a + 0.5],                // at rest from 25.95: the last frame (25.967) is exactly heroNote()
  };
}

function textOut(t, q, gi) {
  const P = exitPlan(q);
  const s = P.text[gi];
  const k = prog(t, s, s + P.textDur, inQuad);
  return { dx: -k * 560, o: 1 - prog(t, s + P.textDur * 0.35, s + P.textDur) };
}

// Anticipation: the icon squashes wide as its row's text slides into it, holds the squash until its flight starts (f0),
// then releases it during the first frames of the flight (continuous across f0, so no pop).
function antic(t, q, gi, f0) {
  const s = exitPlan(q).text[gi];
  return prog(t, s + 0.03, f0, outCubic) * (1 - prog(t, f0, f0 + 0.09, outCubic));
}
function squashAbout(content, amt, x, y) {
  if (amt <= 1e-3) return content;
  return g(content, { sx: 1 + 0.09 * amt, sy: 1 - 0.07 * amt, ox: x, oy: y });
}

// ---------- Kicker: "StudyHub 历史运营数据" in a tinted pill that grows from a dot ----------
function kicker(t, q) {
  const t0 = q.kicker;
  const kPop = clamp(spring(t - t0, 2.8, 0.55), 0, 1.3);
  if (kPop <= 0) return '';
  const [en, ...rest] = q.kickerText.split(' ');
  const cn = rest.join(' ');
  const S = KICK.size;
  const enW = measure(en, S, 800, FONT_EN);
  const gap = S * 0.28;
  const cnW = measure(cn, S, 700, FONT_CN);
  const fullW = enW + gap + cnW + KICK.padX * 2;
  const h = KICK.h;
  const cy = DATA.kickerY;
  // Dot pops (spring), then stretches right into the pill (circle -> capsule).
  const kW = prog(t, t0 + 0.07, t0 + 0.5, snap);
  const wNow = lerp(h, fullW, kW);
  const hh = h * kPop;
  const shape = { cx: LEFT + wNow / 2, cy, w: Math.max(hh, wNow - h * (1 - kPop)), h: hh, r: hh / 2 };
  let s = rr(shape, C.blueSoft);
  // Words rise inside the pill.
  const base = cy + S * 0.36;
  const k1 = prog(t, t0 + 0.12, t0 + 0.52, snap);
  const k2 = prog(t, t0 + 0.19, t0 + 0.59, snap);
  let words = '';
  if (k1 > 0) words += text(en, LEFT + KICK.padX, base + (1 - k1) * S * 1.1, { size: S, weight: 800, family: FONT_EN, fill: C.blue, anchor: 'start' });
  if (k2 > 0) words += text(cn, LEFT + KICK.padX + enW + gap, base + (1 - k2) * S * 1.1, { size: S, weight: 700, fill: C.blueDeep, anchor: 'start' });
  s += clipRect(words, shape.cx - shape.w / 2, cy - hh / 2, shape.w, hh);
  const out = textOut(t, q, 0);
  return g(s, { x: out.dx, o: out.o });
}

// ---------- Number with a "+" ----------
// Digits sit in fixed slots taken from the FINAL string, right-aligned, so the count never jitters sideways.
function slots(str, size) {
  const xs = [];
  for (let j = 0; j < str.length; j++) {
    const x0 = measure(str.slice(0, j), size, 800, FONT_EN);
    const x1 = measure(str.slice(0, j + 1), size, 800, FONT_EN);
    xs.push((x0 + x1) / 2);
  }
  return { xs, w: measure(str, size, 800, FONT_EN) };
}

function dataRow(t, q, i) {
  const row = q.rows[i];
  const rt = rowTimes(q, i);
  if (t < rt.t0) return '';
  const y = DATA.rows[i].y;
  const x = DATA.textX;
  const final = String(row.value);
  const sl = slots(final, L.num);
  const nb = y + L.numBase;
  const out = textOut(t, q, i + 1);

  // Number: slides up from behind a mask edge, then counts on outCubic (the audio ticks on the same curve).
  const kN = prog(t, rt.t0, rt.t0 + 0.42, snap);
  const v = Math.round(row.value * outCubic(prog(t, rt.c0, rt.c1)));
  const shown = String(v);
  let nStr = '';
  for (let j = 0; j < shown.length; j++) {
    const slot = final.length - shown.length + j;
    nStr += text(shown[j], x + sl.xs[slot], nb + (1 - kN) * L.num * 0.95, { size: L.num, weight: 800, fill: C.blue, family: FONT_EN, anchor: 'middle' });
  }
  // "+" spins and springs in on the ding.
  const kP = clamp(spring(t - rt.c1, 3.0, 0.42), 0, 1.4);
  if (kP > 0) {
    const ps = L.num * PLUS;
    const pw = measure(row.suffix, ps, 800, FONT_EN);
    const pcx = x + sl.w + 4 + pw / 2;
    const pcy = nb - L.num * 0.37;
    const plus = text(row.suffix, pcx, pcy + ps * 0.29, { size: ps, weight: 800, fill: C.blue, family: FONT_EN, anchor: 'middle' });
    nStr += g(plus, { s: kP, rot: (1 - clamp(kP)) * -120, ox: pcx, oy: pcy });
  }
  const numTop = nb - L.num * 0.92;
  let s = clipRect(g(nStr, { x: out.dx }), x - 28, numTop, W - x + 28, L.num * 1.1);

  // Unit: same mask move, two frames later.
  const kU = prog(t, rt.t0 + 0.067, rt.t0 + 0.067 + 0.42, snap);
  if (kU > 0) {
    const ux = x;
    const ub = y + L.unitBase;
    const u = text(row.unit, ux, ub + (1 - kU) * L.unit * 1.3, { size: L.unit, weight: 700, fill: C.ink, anchor: 'start' });
    s += clipRect(g(u, { x: out.dx }), x - 28, ub - L.unit * 1.05, W - x + 28, L.unit * 1.4);
  }
  // Divider under the row.
  const kD = prog(t, rt.t0 + 0.15, rt.t0 + 0.65, snap);
  const ko = prog(t, exitPlan(q).text[i + 1], exitPlan(q).text[i + 1] + 0.17, inQuad);
  const len = (RIGHT - x) * kD * (1 - ko);
  if (len > 1) s += rr({ cx: x + len / 2, cy: y + 155, w: len, h: 4, r: 2 }, C.line);
  return g(s, { o: out.o });
}

// ---------- Footnote ----------
function footnote(t, q) {
  const k = prog(t, q.footnote, q.footnote + 0.45, snap);
  if (k <= 0) return '';
  const out = textOut(t, q, 4);
  const y = DATA.footY + 10;
  const s = text(q.footnoteText, LEFT, y + (1 - k) * FOOT * 1.3, { size: FOOT, weight: 500, fill: C.muted, anchor: 'start' });
  return g(clipRect(s, 0, y - FOOT * 1.1, W, FOOT * 1.5), { x: out.dx, o: out.o });
}

// ---------- Icons ----------
// Arc from a to b with control point c; returns position and travel angle.
function arc(a, c, b, u) {
  const x = (1 - u) ** 2 * a.x + 2 * (1 - u) * u * c.x + u * u * b.x;
  const y = (1 - u) ** 2 * a.y + 2 * (1 - u) * u * c.y + u * u * b.y;
  const vx = 2 * (1 - u) * (c.x - a.x) + 2 * u * (b.x - c.x);
  const vy = 2 * (1 - u) * (c.y - a.y) + 2 * u * (b.y - c.y);
  return { x, y, ang: Math.atan2(vy, vx) * 180 / Math.PI };
}
// Stretch along the travel direction.
function stretchAlong(content, x, y, ang, str) {
  if (Math.abs(str) < 1e-3) return content;
  return `<g transform="translate(${num(x)} ${num(y)}) rotate(${num(ang)}) scale(${num(1 + str)} ${num(1 - str)}) rotate(${num(-ang)}) translate(${num(-x)} ${num(-y)})">${content}</g>`;
}

const CENTRE = { x: HERO_NOTE.cx, y: HERO_NOTE.cy };

// noteCard() geometry, with heavier header/lines for the small icon (lhK, thickK); defaults match noteCard exactly.
function paper({ cx, cy, w, h, r = null, accent = C.amber, lines = 4, lineColor = '#d6deea', tilt = 0, headerK = 1, linesK = 1, lhK = 0.075, thickK = 0.05 }) {
  if (w <= 1) return '';
  const R = r ?? w * 0.09;
  let s = rr({ cx: cx + w * 0.035, cy: cy + w * 0.05, w, h, r: R }, 'rgba(15,23,42,0.10)');
  s += rr({ cx, cy, w, h, r: R }, C.paper);
  const pad = w * 0.16;
  const left = cx - w / 2 + pad;
  const hw = (w - pad * 2) * 0.55 * headerK;
  const lh = Math.max(4, w * lhK);
  if (headerK > 0.01) s += rr({ cx: left + hw / 2, cy: cy - h / 2 + pad + lh / 2, w: hw, h: lh, r: lh / 2 }, accent);
  const gap = (h - pad * 2 - lh) / (lines + 0.5);
  for (let i = 0; i < lines; i++) {
    const k = clamp(linesK * lines - i);
    const lw = (w - pad * 2) * (i === lines - 1 ? 0.6 : i % 2 ? 0.86 : 1) * k;
    const ly = cy - h / 2 + pad + lh + gap * (i + 1);
    const thick = Math.max(3, w * thickK);
    if (lw > 0.5) s += rr({ cx: left + lw / 2, cy: ly, w: lw, h: thick, r: thick / 2 }, lineColor);
  }
  return g(s, { rot: tilt, ox: cx, oy: cy });
}
const ICON_INK = { lines: 3, lineColor: C.lineStrong, lhK: 0.1, thickK: 0.072 };

// Row 0: the faces icon (already on screen at 20.0). Pulse on row-in, happy hop on the ding, a small nod in the hold.
const HOP_ORDER = [0, 2, 1]; // FACES_ICON is teal, amber, blue: hop left, top, right
function facesRow(t, q) {
  const rt = rowTimes(q, 0);
  const P = exitPlan(q);
  const cx = DATA.iconX, cy = DATA.rows[0].y;
  if (t < rt.t0) return facesIcon(cx, cy, 1, { happy: 1 }); // the S4 hand-off picture, untouched
  const pulse = boing(t, rt.t0, 2.4, 7) * 0.07;
  let s = '';
  for (let j = 0; j < FACES_ICON.length; j++) {
    const f = FACES_ICON[j];
    const order = HOP_ORDER[j];
    // Happy hop when the number lands, with a squash on landing.
    const h0 = rt.c1 + order * 0.067;
    const hx = clamp((t - h0) / 0.3);
    const inAir = t > h0 && hx < 1;
    const hop = inAir ? 4 * hx * (1 - hx) * 26 : 0;
    const air = inAir ? Math.sin(Math.PI * hx) * 0.07 : 0;
    const land = t >= h0 + 0.3 ? boing(t, h0 + 0.3, 3, 9) * 0.1 : 0;
    // Tiny life in the hold: one soft nod, derived from the hold window.
    const n0 = (rowTimes(q, 2).c1 + P.a) / 2 + order * 0.07;
    const nod = Math.sin(Math.PI * prog(t, n0, n0 + 0.3)) * 5;
    const a = { x: cx + f.dx, y: cy + f.dy };
    const [f0, f1] = P.fly.faces;
    const st = f0 + order * 0.033, en = f1 + order * 0.033;
    const u = prog(t, st, en, morph);
    if (u >= 1) continue;
    const amt = antic(t, q, 1, st);
    if (u > 0) {
      // Flight: right then down into the centre, shrinking to a dot that slips behind the bridge.
      const c = { x: lerp(a.x, CENTRE.x, 0.62) + j * 24, y: a.y - 30 + j * 20 };
      const p = arc(a, c, CENTRE, u);
      const d = lerp(f.d, 40, u);
      const eyeScale = 0.92 * (1 - prog(u, 0, 0.35));
      const str = 0.14 * Math.sin(Math.PI * u);
      s += squashAbout(stretchAlong(botFace({ cx: p.x, cy: p.y, d, shape: 0, body: f.color, happy: 1, eyeScale }), p.x, p.y, p.ang, str), amt, p.x, p.y);
      continue;
    }
    const fx = a.x, fy = a.y - hop + nod;
    const sx = 1 + pulse - air + land, sy = 1 + pulse * 0.4 + air - land;
    s += squashAbout(g(botFace({ cx: fx, cy: fy, d: f.d, shape: 0, body: f.color, happy: 1, eyeScale: 0.92 }), { sx, sy, ox: fx, oy: fy + f.d / 2 }), amt, fx, fy);
  }
  return s;
}

// Row 1: a mini hero note. In M11 it is the bridge: card -> circle -> the hero note.
function noteIcon(t, q) {
  const rt = rowTimes(q, 1);
  const P = exitPlan(q);
  if (t < rt.t0) return '';
  const cx = DATA.iconX, cy = DATA.rows[1].y;
  const kPop = clamp(spring(t - rt.t0, 2.5, 0.42), 0, 1.3);
  if (kPop <= 0.001) return '';
  const [f0, f1] = P.fly.note;
  const [e0, e1] = P.expand;
  if (t >= e1) return heroNote();
  if (t < f0) {
    // Pop in, wiggle on the ding, squash as the row's text slides in.
    const wig = boing(t, rt.c1, 3, 7);
    const tilt = lerp(-24, NOTE_ICON.tilt, clamp(kPop)) + wig * 8;
    const hop = Math.max(0, wig) * 10;
    const icon = g(paper({ cx, cy: cy - hop, w: NOTE_ICON.w, h: NOTE_ICON.h, tilt, ...ICON_INK }), { s: kPop, ox: cx, oy: cy + NOTE_ICON.h / 2 });
    return squashAbout(icon, antic(t, q, 2, f0), cx, cy);
  }
  // Flight: card -> circle along a shallow arc over the cleared row.
  const u = prog(t, f0, f1, morph);
  const a = { x: cx, y: cy };
  const c = { x: lerp(cx, CENTRE.x, 0.5), y: cy - 110 };
  const p = arc(a, c, CENTRE, u);
  const mk = prog(u, 0.08, 0.62, morph);       // shape: card -> circle
  const hk = 1 - prog(u, 0, 0.3);              // header and lines fold away while it is still a card
  let w = lerp(NOTE_ICON.w, BRIDGE, mk), h = lerp(NOTE_ICON.h, BRIDGE, mk), r = lerp(NOTE_ICON.w * 0.09, BRIDGE / 2, mk);
  let tilt = lerp(NOTE_ICON.tilt, 0, u) + Math.sin(Math.PI * u) * 12;
  let headerK = hk, linesK = hk, ink = ICON_INK;
  let str = 0.1 * Math.sin(Math.PI * u);
  if (t > e0) {
    // Expansion: circle -> hero note with a soft start and a small overshoot that comes to rest at e1.
    const E = landEase(prog(t, e0, e1));
    w = lerp(BRIDGE, HERO_NOTE.w, E);
    h = lerp(BRIDGE, HERO_NOTE.h, E);
    r = lerp(BRIDGE / 2, HERO_NOTE.w * 0.09, clamp(E));
    tilt += Math.sin(Math.PI * clamp(E)) * -5;
    headerK = prog(E, 0.55, 0.95);
    linesK = prog(E, 0.6, 1);
    ink = {};
    str *= 1 - clamp(E);
  }
  const body = paper({ cx: p.x, cy: p.y, w, h, r, headerK, linesK, tilt, ...ink });
  return squashAbout(stretchAlong(body, p.x, p.y, p.ang, str), antic(t, q, 2, f0), p.x, p.y);
}

// Row 2: download arrow + tray, built from capsules (same geometry as downloadIcon) so it can fold into one circle.
function dlIcon(t, q) {
  const rt = rowTimes(q, 2);
  const P = exitPlan(q);
  if (t < rt.t0) return '';
  const kPop = clamp(spring(t - rt.t0, 2.5, 0.42), 0, 1.3);
  if (kPop <= 0.001) return '';
  const cx = DATA.iconX, cy = DATA.rows[2].y;
  const k = DL / 100;
  // The arrow drops into the tray on the ding.
  const b = boing(t, rt.c1, 2.6, 8);
  const dip = (b > 0 ? 12 : 3) * b * k;
  const parts = [
    { s: { cx, cy: cy - 14 * k + dip, w: 16 * k, h: 56 * k, r: 8 * k }, rot: 0 },
    { s: { cx: cx - 14 * k, cy: cy + 4 * k + dip, w: 16 * k, h: 40 * k, r: 8 * k }, rot: -45 },
    { s: { cx: cx + 14 * k, cy: cy + 4 * k + dip, w: 16 * k, h: 40 * k, r: 8 * k }, rot: 45 },
    { s: { cx, cy: cy + 40 * k, w: 84 * k, h: 16 * k, r: 8 * k }, rot: 0 },
  ];
  const [f0, f1] = P.fly.dl;
  const fold = prog(t, f0 - 0.06, f0 + 0.1, morph);   // capsules -> one circle (finishes early in the flight)
  const D = 60;
  const dot = { cx, cy: cy + 6 * k, w: D, h: D, r: D / 2 };
  const amt = antic(t, q, 3, f0);
  const u = prog(t, f0, f1, morph);
  if (u >= 1) return '';
  // Flight: right then up into the centre; the folding capsules travel with it.
  const a = { x: dot.cx, y: dot.cy };
  const c = { x: lerp(a.x, CENTRE.x, 0.62), y: a.y + 30 };
  const p = u > 0 ? arc(a, c, CENTRE, u) : { x: a.x, y: a.y, ang: 0 };
  const sc = lerp(D, 40, u) / D;
  const map = (st) => ({ cx: p.x + (st.cx - dot.cx) * sc, cy: p.y + (st.cy - dot.cy) * sc, w: st.w * sc, h: st.h * sc, r: st.r * sc });
  let s = '';
  for (const pt of parts) {
    const st = map(rrLerp(pt.s, dot, fold));
    const rot = pt.rot * (1 - fold);
    s += rot ? g(rr(st, C.blue), { rot, ox: st.cx, oy: st.cy }) : rr(st, C.blue);
  }
  if (u <= 0) return squashAbout(g(s, { s: kPop, ox: cx, oy: cy + 48 * k }), amt, dot.cx, dot.cy);
  const str = 0.14 * Math.sin(Math.PI * u);
  return squashAbout(stretchAlong(s, p.x, p.y, p.ang, str), amt, p.x, p.y);
}

export function draw(t, cues) {
  const q = cues.s5;
  clipN = 0;
  let s = '';
  s += kicker(t, q);
  for (let i = 0; i < q.rows.length; i++) s += dataRow(t, q, i);
  s += footnote(t, q);
  // Icons last: the absorbed circles behind, the bridge note on top.
  s += facesRow(t, q);
  s += dlIcon(t, q);
  s += noteIcon(t, q);
  return s;
}
