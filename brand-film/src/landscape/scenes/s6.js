// Landscape S6 brand end card (26-30 s), 1920x1080. Same story and cue times as the portrait src/scenes/s6.js:
// a blue iris opens behind the hero note; the note hops up, curls into a squircle and lands as the StudyHub logo
// (signature morph M12: two text lines stand up and become the eyes); then the lockup, slogan and CTA.
// 16:9 composition: an optically centred stack (logo, wordmark, slogan, CTA) inside layout.js SAFE.
import { C, FONT_CN, FONT_EN, rr, rrPath, g, text, measure, prog, clamp, lerp, spring, snap, glide, bezier, outCubic, inCubic, inOutSine, lineReveal, botFace, blinkAt, num } from '../../core.js';
import { lockup } from '../../shared.js';
import { HERO_NOTE_L, heroNoteL, LW } from '../layout.js';

export const range = [26.0, 30.01];

const iris = bezier(0.42, 0, 0.12, 1);
const morphEase = bezier(0.7, 0, 0.3, 1); // each half of M12: slow cushion, fast middle, slow cushion
const turnEase = bezier(0.55, 0, 0.3, 1);
const moveEase = bezier(0.45, 0, 0.25, 1);

// Official app icon (frontend/public/icons/studyhub-app.svg), in units of the icon side (512).
const ICON = { r: 104 / 512, ew: 56 / 512, eh: 144 / 512, pitch: 128 / 512, shift: 60.43 / 512 };

// End-card stack. The block (logo top 198 .. CTA bottom 870) sits on the optical centre of the frame,
// a few px above the geometric centre; every element is horizontally centred on the frame.
const CX = LW / 2;
export const LOGO = { cx: CX, cy: 318, d: 240 };   // note width = logo side, as in the portrait cut (300/300)
const LOCK = { y: 598, size: 96 };
const SLOGAN = { y: 692, size: 48 };
const CTA = { y: 822, h: 96, size: 40, pad: 50, arrow: 29, arrowGap: 19 };
const K = LOGO.d / 300;                            // portrait -> landscape scale for the morph's pixel constants
const APEX_Y = LOGO.cy - 70 * K;                   // body centre at the top of the jump
const BRIDGE = { w: 262 * K, h: 262 * K, r: 120 * K }; // near-circle (squircle) between the page and the logo square
const LINE_GREY = '#d6deea';                       // noteCard() default line colour
const SHADOW = 'rgba(15,23,42,0.10)';
const IRIS = { r0: 112, r1: 1112 };                // r0 hides under the 240 px page; r1 > half-diagonal 1101

// The hero note's parts in local coordinates (origin = note centre), same maths as core noteCard().
const NOTE = (() => {
  const { w, h, lines } = HERO_NOTE_L;
  const pad = w * 0.16;
  const left = -w / 2 + pad;
  const hw = (w - pad * 2) * 0.55;
  const lh = Math.max(4, w * 0.075);
  const gap = (h - pad * 2 - lh) / (lines + 0.5);
  const th = Math.max(3, w * 0.05);
  const rows = [];
  for (let i = 0; i < lines; i++) {
    const lw = (w - pad * 2) * (i === lines - 1 ? 0.6 : i % 2 ? 0.86 : 1);
    rows.push({ cx: left + lw / 2, cy: -h / 2 + pad + lh + gap * (i + 1), w: lw, h: th });
  }
  return {
    w, h, r: w * 0.09,
    shadow: { dx: w * 0.035, dy: w * 0.05 },
    header: { cx: left + hw / 2, cy: -h / 2 + pad + lh / 2, w: hw, h: lh },
    rows,
  };
})();

// Logo geometry in local coordinates (origin = logo centre); identical to botFace(shape 1, eyeShift ICON.shift).
const EYES = [-1, 1].map((side) => ({ cx: side * LOGO.d * ICON.pitch / 2 + ICON.shift * LOGO.d, cy: 0, len: LOGO.d * ICON.eh, th: LOGO.d * ICON.ew }));

const lerpShape = (a, b, k) => ({ w: lerp(a.w, b.w, k), h: lerp(a.h, b.h, k), r: lerp(a.r, b.r, k) });

// Transform group with 4-decimal values, so sub-percent scales (breathing, the squash tail) never step.
const p4 = (n) => (Math.abs(n) < 1e-6 ? '0' : Number(n.toFixed(4)).toString());
function gp(content, { x = 0, y = 0, sx = 1, sy = 1, rot = 0, ox = 0, oy = 0 } = {}) {
  let tr = '';
  if (x || y) tr += `translate(${p4(x)} ${p4(y)}) `;
  if (rot || sx !== 1 || sy !== 1) {
    tr += `translate(${p4(ox)} ${p4(oy)}) `;
    if (rot) tr += `rotate(${p4(rot)}) `;
    if (sx !== 1 || sy !== 1) tr += `scale(${p4(sx)} ${p4(sy)}) `;
    tr += `translate(${p4(-ox)} ${p4(-oy)})`;
  }
  return tr ? `<g transform="${tr.trim()}">${content}</g>` : content;
}

// Jump: a short push-off (constant acceleration while the anticipation squash releases), then a ballistic arc
// through APEX_Y that lands on the logo centre exactly at q.land.
const PUSH_D = 40 * K; // px covered during the push-off
function flight(t, q) {
  const launch = q.morph[0] + 0.1;           // end of the push, start of free flight
  const T = q.land - launch;
  const y0 = HERO_NOTE_L.cy - PUSH_D, y1 = LOGO.cy;
  const ta = T / (1 + Math.sqrt((y1 - APEX_Y) / (y0 - APEX_Y)));
  const G = (y0 - APEX_Y) / (ta * ta);
  const vMax = 2 * G * ta;                    // launch speed
  const push = (2 * PUSH_D) / vMax;           // push duration
  const start = launch - push;
  const u = clamp((t - start) / (q.land - start));
  if (t < start) return { launch, start, u, cy: HERO_NOTE_L.cy, vy: 0, vMax };
  if (t < launch) {
    const k = t - start, acc = vMax / push;
    return { launch, start, u, cy: HERO_NOTE_L.cy - 0.5 * acc * k * k, vy: -acc * k, vMax };
  }
  const tau = clamp(t - launch, 0, T);
  return { launch, start, u, cy: APEX_Y + G * (tau - ta) ** 2, vy: 2 * G * (tau - ta), vMax };
}

// Full M12 state at time t (exported so a containment check can sample it).
export function m12(t, cues) {
  const q = cues.s6;
  const [m0] = q.morph;
  const kA = prog(t, m0, q.morphVia, morphEase);
  const kB = prog(t, q.morphVia, q.land, morphEase);
  const page = { w: NOTE.w, h: NOTE.h, r: NOTE.r };
  const square = { w: LOGO.d, h: LOGO.d, r: LOGO.d * ICON.r };
  const body = kB > 0 ? lerpShape(BRIDGE, square, kB) : lerpShape(page, BRIDGE, kA);

  const fl = flight(t, q);
  const u = fl.u;
  // Anticipation: squash down on the bottom edge and lean back, then release into the launch.
  const ant = prog(t, q.wipeBlue[0] + 0.06, fl.start, outCubic) * (1 - prog(t, fl.start, fl.launch + 0.01, inOutSine));
  // Flight stretch along the (vertical) velocity; it grows with speed during the push-off.
  const str = t < q.land ? 0.12 * clamp(Math.abs(fl.vy) / fl.vMax) : 0;
  const cx = HERO_NOTE_L.cx - 24 * K * Math.sin(Math.PI * u);
  const rot = -7 * Math.sin(Math.PI * u) + 2.5 * ant;

  // Dark body: a circle rising from below the body fills it (the film's iris motif); the colour never passes through grey.
  const dark = prog(t, m0 + 0.18, m0 + 0.38, inOutSine);
  const shadowK = 1 - prog(t, m0, m0 + 0.2, outCubic);

  // Lines 1 and 2 stand up (rotate -90 deg) and become the eyes; length leads rotation so they stay inside the body.
  const eyes = [1, 2].map((row, j) => {
    const src = NOTE.rows[row];
    const dst = EYES[j];
    const a = m0 + 0.06 + j * 0.033;
    const b = q.land - 0.12 + j * 0.033;
    const kP = prog(t, a - 0.04, b - 0.08, moveEase); // position leads, so the pair separates before it turns
    const kR = prog(t, a + 0.02, b, turnEase);
    const kL = prog(t, a - 0.04, a + 0.3, glide);     // length leads rotation: the turning line stays inside the body
    const kT = prog(t, a + 0.04, a + 0.44, inOutSine);
    // Arc: line 1 lifts slightly, line 2 swings out to the lower right before rising into place.
    const dx = dst.cx - src.cx, dy = dst.cy - src.cy;
    const len = Math.hypot(dx, dy) || 1;
    const bulge = (j ? -26 : 10) * K * Math.sin(Math.PI * kP);
    return {
      cx: lerp(src.cx, dst.cx, kP) + (dy / len) * bulge,
      cy: lerp(src.cy, dst.cy, kP) - (dx / len) * bulge,
      len: lerp(src.w, dst.len, kL),
      th: lerp(src.h, dst.th, kT),
      rot: -90 * kR,
    };
  });

  // Header and lines 0 and 3 contract to points (pulled slightly inward) and vanish.
  const sxN = body.w / NOTE.w, syN = body.h / NOTE.h;
  const gone = [
    { p: NOTE.header, color: C.amber, t0: m0 - 0.06 },
    { p: NOTE.rows[0], color: LINE_GREY, t0: m0 - 0.02 },
    { p: NOTE.rows[3], color: LINE_GREY, t0: m0 + 0.02 },
  ].map(({ p, color, t0 }) => {
    const v = prog(t, t0, t0 + 0.2);
    const pull = 1 - 0.3 * outCubic(v);
    const sc = 1 - inCubic(clamp((v - 0.4) / 0.6));
    return { cx: p.cx * sxN * pull, cy: p.cy * syN * pull, w: lerp(p.w, p.h, outCubic(clamp(v / 0.6))) * sc, h: p.h * sc, color };
  });

  return { body, cx, cy: fl.cy, rot, ant, str, dark, shadowK, eyes, gone, u };
}

function capsule(e, color) {
  if (e.len <= 0.5 || e.th <= 0.5) return '';
  return g(rr({ cx: e.cx, cy: e.cy, w: e.len, h: e.th, r: e.th / 2 }, color), { rot: e.rot, ox: e.cx, oy: e.cy });
}

// The morphing note/logo before landing, drawn in local coordinates and placed by transforms.
function morphBody(t, cues) {
  const m = m12(t, cues);
  const b = m.body;
  let s = '';
  if (m.shadowK > 0.01) s += rr({ cx: NOTE.shadow.dx * m.shadowK, cy: NOTE.shadow.dy * m.shadowK, w: b.w, h: b.h, r: b.r }, SHADOW);
  const body = { cx: 0, cy: 0, ...b };
  if (m.dark <= 0 || m.dark >= 1) {
    const done = m.dark >= 1;
    s += rr(body, done ? C.bot : C.paper);
    if (!done) for (const p of m.gone) if (p.w > 0.5 && p.h > 0.5) s += rr({ cx: p.cx, cy: p.cy, w: p.w, h: p.h, r: p.h / 2 }, p.color);
    for (const e of m.eyes) s += capsule(e, done ? C.eye : LINE_GREY);
  } else {
    // Dark circle centred below-left of the body; it touches the bottom edge at dark = 0 and covers the far corner at 1.
    // Light parts are clipped to the outside of the circle and dark parts to the inside, so no edge is drawn twice.
    const dc = { x: -0.2 * b.w, y: 0.95 * b.h };
    const r0 = dc.y - b.h / 2;
    const r1 = Math.hypot(b.w / 2 - dc.x, b.h / 2 + dc.y);
    const cr = lerp(r0, r1, m.dark);
    const circ = `M${num(dc.x - cr)},${num(dc.y)}a${num(cr)},${num(cr)} 0 1,0 ${num(2 * cr)},0a${num(cr)},${num(cr)} 0 1,0 ${num(-2 * cr)},0Z`;
    s += `<defs><clipPath id="ls6in"><path d="${circ}"/></clipPath><clipPath id="ls6out"><path clip-rule="evenodd" d="M-2000,-2000H2000V2000H-2000Z${circ}"/></clipPath></defs>`;
    let light = rr(body, C.paper);
    for (const p of m.gone) if (p.w > 0.5 && p.h > 0.5) light += rr({ cx: p.cx, cy: p.cy, w: p.w, h: p.h, r: p.h / 2 }, p.color);
    for (const e of m.eyes) light += capsule(e, LINE_GREY);
    let darkPart = rr(body, C.bot);
    for (const e of m.eyes) darkPart += capsule(e, C.eye);
    s += `<g clip-path="url(#ls6out)">${light}</g><g clip-path="url(#ls6in)">${darkPart}</g>`;
  }
  // Ground squash (anticipation) pivots on the bottom edge; flight stretch pivots on the centre.
  const a = m.ant;
  const ground = gp(s, { sx: 1 + 0.05 * a, sy: 1 - 0.08 * a, oy: b.h / 2 });
  const fly = gp(ground, { sx: 1 - 0.8 * m.str, sy: 1 + m.str });
  return gp(fly, { x: m.cx, y: m.cy, rot: m.rot });
}

// Landing burst: short white capsules flicked outward from behind the logo on the beat.
function burst(t, q) {
  const k = prog(t, q.land, q.land + 0.34);
  if (k <= 0 || k >= 1) return '';
  let s = '';
  // Five rays fanned over the top and sides; the lowest ones stop well above the wordmark.
  for (const a of [-150, -90, -30, 30, 150]) {
    const rad = (a * Math.PI) / 180;
    const r = lerp(200, 318, outCubic(k)) * K;
    const len = 54 * K * Math.sin(Math.PI * Math.min(1, k * 1.15)) + 0.01;
    const th = 16 * K * (1 - inCubic(k));
    const cx = LOGO.cx + Math.cos(rad) * r, cy = LOGO.cy + Math.sin(rad) * r;
    if (th > 0.5) s += g(rr({ cx, cy, w: Math.max(len, th), h: th, r: th / 2 }, C.paper), { rot: a, ox: cx, oy: cy });
  }
  return s;
}

// The landed logo: official geometry via botFace, with the landing squash, breathing, blink and look.
function landedLogo(t, q) {
  const tl = t - q.land;
  const A = 0.13, w = (2 * Math.PI) / 0.3, td = 0.11;
  // Decayed residuals (< 1e-5) snap to exactly 0, so the held logo is the official icon path for path.
  const settle = (x) => (Math.abs(x) < 1e-5 ? 0 : x);
  const v = settle(-A * Math.cos(w * tl) * Math.exp(-tl / td));               // vertical scale offset, max squash on the beat
  const tl2 = tl - 1 / 30;                                                      // eyes follow one frame later (overlap)
  const ve = tl2 > 0 ? settle(-A * Math.cos(w * tl2) * Math.exp(-tl2 / td)) : 0;
  // Breathing (0.5%) fades in after the landing and out again before the end, so the last frame is the exact icon.
  const breatheK = prog(t, q.land + 0.6, q.land + 1.1, inOutSine) * (1 - prog(t, q.lookBack[1], q.lookBack[1] + 0.2, inOutSine));
  const breathe = 1 + 0.005 * Math.sin((2 * Math.PI * (t - q.land - 0.75)) / 1.0) * breatheK;
  // Look down at the CTA (centred below), then back to the official pose so the last frame is the canonical logo.
  const look = prog(t, q.lookCta[0], q.lookCta[1], snap) * (1 - prog(t, q.lookBack[0], q.lookBack[1], snap));
  const face = botFace({
    cx: LOGO.cx, cy: LOGO.cy, d: LOGO.d, shape: 1, eyeShift: ICON.shift, body: C.bot,
    blink: Math.min(1, 1 + 1.4 * ve) * blinkAt(t, q.blink),
    look: -0.35 * look, lookY: 1.0 * look,
  });
  const base = LOGO.cy + LOGO.d / 2;
  return gp(face, { sx: (1 - 0.9 * v) * breathe, sy: (1 + v) * breathe, ox: LOGO.cx, oy: base });
}

// Optical centring: offset that puts a line's ink (not its advance box) on the anchor. A trailing full-width
// "。" carries ~0.6 em of empty advance, which would sit the slogan ~15 px left of the logo's axis.
let inkCtx = null;
function inkShift(str, size, weight, family) {
  if (!inkCtx) inkCtx = document.createElement('canvas').getContext('2d');
  inkCtx.font = `${weight} ${size}px ${family}`;
  const m = inkCtx.measureText(str);
  // Ink spans [-left, right] from the start; shift = advance centre - ink centre.
  return (m.width - m.actualBoundingBoxRight + m.actualBoundingBoxLeft) / 2;
}

function wordmark(t, q) {
  return lockup(CX, LOCK.y, LOCK.size, {
    fill: '#ffffff',
    reveal: (i) => {
      const k = prog(t, q.wordmark + i * 0.03, q.wordmark + i * 0.03 + 0.4, snap);
      return { o: clamp(k * 1.5), dy: (1 - k) * 56 };
    },
  });
}

// CTA: a white dot springs up, stretches into a capsule button, then the label rises inside it.
function ctaButton(t, q) {
  const lt = t - q.cta;
  if (lt <= 0) return '';
  const wCn = measure('立即访问', CTA.size, 700, FONT_CN);
  const gap = CTA.size * 0.28;
  const wEn = measure('study-hub.cn', CTA.size, 700, FONT_EN);
  const content = wCn + gap + wEn + CTA.arrowGap + CTA.arrow;
  const W = content + CTA.pad * 2;
  // Springs pop and overshoot, then blend to exactly 1 so the button is still when the hold starts (cta + 0.3).
  const still = prog(lt, 0.18, 0.3, inOutSine);
  const pop = lerp(Math.max(0, spring(lt, 5, 0.6)), 1, still);
  const open = lerp(Math.max(0, spring(lt - 0.04, 4.8, 0.62)), 1, still);
  const h = CTA.h * pop * (1 - 0.06 * Math.sin(Math.PI * clamp(open)) * (1 - clamp(open)));
  const w = lerp(CTA.h, W, open) * pop;
  const btn = { cx: CX, cy: CTA.y, w, h, r: h / 2 };
  let s = rr({ ...btn, cy: CTA.y + 9 * pop }, SHADOW) + rr(btn, C.paper);

  const k = prog(t, q.cta + 0.1, q.cta + 0.3, snap); // starts once the button is ~99% open; settled when the hold starts
  if (k > 0) {
    const x0 = CX - content / 2;
    const rise = (1 - k) * 34;
    const base = CTA.y + CTA.size * 0.36 + rise;
    let c = '';
    c += text('立即访问', x0, base, { size: CTA.size, weight: 700, fill: C.blue, family: FONT_CN, anchor: 'start' });
    c += text('study-hub.cn', x0 + wCn + gap, base, { size: CTA.size, weight: 700, fill: C.blue, family: FONT_EN, anchor: 'start' });
    // Arrow from capsules: shaft plus two arms meeting at the tip.
    const th = 6, tipX = CX + content / 2 - (1 - k) * 12, ay = CTA.y + rise;
    const armL = 17, shaftL = CTA.arrow;
    c += rr({ cx: tipX - shaftL / 2, cy: ay, w: shaftL, h: th, r: th / 2 }, C.blue);
    for (const sgn of [-1, 1]) {
      const dir = [-Math.SQRT1_2, sgn * Math.SQRT1_2];
      const acx = tipX - th / 2 + dir[0] * (armL / 2 - th / 2), acy = ay + dir[1] * (armL / 2 - th / 2);
      c += g(rr({ cx: acx, cy: acy, w: armL, h: th, r: th / 2 }, C.blue), { rot: -sgn * 45, ox: acx, oy: acy });
    }
    s += `<defs><clipPath id="ls6cta"><path d="${rrPath(btn.cx, btn.cy, btn.w, btn.h, btn.r)}"/></clipPath></defs>`;
    s += `<g clip-path="url(#ls6cta)">${g(c, { o: clamp(k * 2) })}</g>`;
  }
  return s;
}

export function draw(t, cues) {
  const q = cues.s6;
  // Hand-off from S5: the soft field and the hero note, untouched.
  if (t <= q.wipeBlue[0]) return heroNoteL();
  let s = '';
  // Blue iris from behind the note (starts hidden under the page).
  if (t < q.wipeBlue[1]) {
    const k = prog(t, q.wipeBlue[0], q.wipeBlue[1], iris);
    s += `<circle cx="${HERO_NOTE_L.cx}" cy="${HERO_NOTE_L.cy}" r="${num(lerp(IRIS.r0, IRIS.r1, k))}" fill="${C.blue}"/>`;
  }
  if (t < q.land) {
    s += morphBody(t, cues);
  } else {
    s += burst(t, q);
    s += landedLogo(t, q);
  }
  s += wordmark(t, q);
  s += lineReveal(q.sloganText, CX + inkShift(q.sloganText, SLOGAN.size, 700, FONT_CN), SLOGAN.y, t, q.slogan, { size: SLOGAN.size, weight: 700, fill: '#ffffff', dur: 0.5 });
  s += ctaButton(t, q);
  return s;
}

export function background(t, cues) {
  return t < cues.s6.wipeBlue[1] ? C.bg : C.blue;
}
