// S2 brand, landscape cut (2.9-7.85 s): the dot bursts into a blue field, the StudyHub bot appears,
// then it leaps into the app header and gathers 12 course cards into a 6x2 grid.
// Same cues and story as src/scenes/s2.js, re-composed for 1920x1080.
import { C, rr, g, prog, clamp, lerp, spring, snap, glide, outCubic, inCubic, bezier, lineReveal, botFace, blinkAt } from '../../core.js';
import { lockup, lockupMetrics, materialCard, COURSES } from '../../shared.js';
import { LW, LH, MERGE_L, FACE_BIG_L, FACE_HEAD_L, LOCK_BIG_L, LOCK_HEAD_L, GRID_L, gridSlotL } from '../layout.js';

export const range = [2.9, 7.85];
// No background(): during the 2.9-3.0 overlap S1 keeps its own field; S2 paints its blue field itself.

// Fast-start iris: visibly bursts on the first frame after the 3.0 s drop hit (same as portrait).
const iris = bezier(0.25, 0.3, 0.1, 1);
const IRIS_R = 1240;          // farthest corner from MERGE_L is ~1165 px
const RING_BIG = 9;           // white ring on the big face (portrait 10 at d 320)
const RING_HEAD = 4;
const POS_Y = 818;            // positioning line baseline
const POS_SIZE = 58;
const HEAD_Y = 880;           // headline baseline
const HEAD_SIZE = 96;
const REST_T = 7.6;           // from here the picture is exactly headerL() + gridCardsL() (+ headline)
const leap = bezier(0.42, -0.22, 0.22, 1);   // face move: pull back (anticipation), fast leap, soft landing
const bump = (p) => (p <= 0 || p >= 1 ? 0 : Math.sin(Math.PI * p) * (1 - p) * 1.72); // early peak ~1, decays to 0
const SHADOW = 'rgba(15,23,42,0.10)';

// ---------- Header (face + lockup) ----------
// Lockup: the big centred lockup is scaled about its visual centre into the header slot.
export function lockupTransformL(k) {
  const mBig = lockupMetrics(LOCK_BIG_L.size);
  const sc = LOCK_HEAD_L.size / LOCK_BIG_L.size;
  const ox = LW / 2, oy = LOCK_BIG_L.y - LOCK_BIG_L.size * 0.36;
  const tx = LOCK_HEAD_L.left + (mBig.w * sc) / 2;
  const ty = LOCK_HEAD_L.y - LOCK_HEAD_L.size * 0.36;
  return { x: lerp(0, tx - ox, k), y: lerp(0, ty - oy, k), s: lerp(1, sc, k), ox, oy };
}
// Final header pieces. S3 imports these; draw() uses the same functions so the hand-off is string-identical.
export function headerFaceL(over = {}) {
  return botFace({ cx: FACE_HEAD_L.cx, cy: FACE_HEAD_L.cy, d: FACE_HEAD_L.d, ring: RING_HEAD, blink: 1, look: 0, lookY: 0, ...over });
}
export function headerLockupL() {
  return g(lockup(LW / 2, LOCK_BIG_L.y, LOCK_BIG_L.size, { fill: '#ffffff' }), lockupTransformL(1));
}
export function headerL() {
  return headerFaceL() + headerLockupL();
}

// ---------- Grid (6x2) ----------
function restCard(i) {
  return materialCard({ ...gridSlotL(i), w: GRID_L.w, h: GRID_L.h, course: COURSES[i] });
}
export function gridCardsL() {
  let s = '';
  for (let i = 0; i < COURSES.length; i++) s += restCard(i);
  return s;
}

// ---------- Face M4: anticipation, leap on an arc, overshoot, settle ----------
const DIR = (() => {
  const dx = FACE_HEAD_L.cx - FACE_BIG_L.cx, dy = FACE_HEAD_L.cy - FACE_BIG_L.cy;
  const L = Math.hypot(dx, dy);
  return { dx, dy, L, px: -dy / L, py: dx / L }; // (px, py) points up-right: the leap bows up
})();
function faceK(t, q) {
  const a = q.toHeader[0];
  const main = leap(prog(t, a, q.toHeader[1] - 0.05));
  const over = 0.032 * bump(prog(t, q.toHeader[1] - 0.2, q.toHeader[1] + 0.07));
  return main + over;
}
function facePos(t, q) {
  const k = faceK(t, q);
  const arc = Math.sin(Math.PI * clamp(k)) * 70;
  return {
    k,
    cx: lerp(FACE_BIG_L.cx, FACE_HEAD_L.cx, k) + DIR.px * arc,
    cy: lerp(FACE_BIG_L.cy, FACE_HEAD_L.cy, k) + DIR.py * arc,
    d: lerp(FACE_BIG_L.d, FACE_HEAD_L.d, k),
  };
}
const faceSettled = (t, q) => t >= q.toHeader[1] + 0.07;

// Lockup trails the face by lockupDelay, on a smaller parallel arc.
function lockupK(t, q) {
  return prog(t, q.toHeader[0] + q.lockupDelay, q.toHeader[1], glide);
}

// Stretch along a velocity vector: rotate(ang) scale(1+st, 1/(1+st)) rotate(-ang), about (ox, oy).
function stretchG(content, ox, oy, ang, st, extra = {}) {
  if (Math.abs(st) < 1e-4) return g(content, { ox, oy, ...extra });
  const inner = g(content, { rot: -ang, ox, oy });
  return g(inner, { rot: ang, sx: 1 + st, sy: 1 / (1 + st), ox, oy, ...extra });
}

// ---------- Card flights ----------
// Landing times and sounds come from cues (cardsIn + o * cardStagger, o = 0..11). compose.py pans the whoosh of the
// card landing at slot o by the portrait card's i % 3 (0 left, 1 centre, 2 right). The landscape cut keeps those 12
// times and that pan per time, but chooses which 6x2 slot fills at each time, so that the card enters from the side
// the sound comes from and never crosses a landed card, the header or the readable headline:
//   left pan   -> columns 0-1 from the left edge, inner column first;
//   right pan  -> columns 4-5 from the right edge, inner column first;
//   centre pan -> columns 2-3: the bottom row first (it rises through the headline zone before 6.4 s), then the top row.
// Course i always rests in gridSlotL(i), so the rest picture is the same as with the portrait order.
const QUEUES = { L: [7, 1, 0, 6], R: [4, 10, 11, 5], C: [8, 9, 2, 3] };
const sideOf = (i) => (i % 3 === 0 ? 'L' : i % 3 === 2 ? 'R' : 'C');
let ORDER_KEY = '', SLOT_ORDER = null;
function slotOrder(q) {
  const key = q.cardOrder.join(',');
  if (key === ORDER_KEY) return SLOT_ORDER;
  const n = q.cardOrder.length;
  const sideAt = [];
  for (let i = 0; i < n; i++) sideAt[q.cardOrder[i]] = sideOf(i);
  const qs = { L: [...QUEUES.L], R: [...QUEUES.R], C: [...QUEUES.C] };
  const out = new Array(n);
  for (let o = 0; o < n; o++) out[qs[sideAt[o]].shift()] = o;
  ORDER_KEY = key; SLOT_ORDER = out;
  return out; // out[slot] = landing index o
}

// Per slot: entry edge, offset along that edge, arc bow (px; + bows down for L, up for R, left for T, right for B), start tilt.
// Rows open away from each other (row 0 bows up, row 1 bows down); centre columns bow outward.
const ENTRY = [
  { edge: 'L', off: -20, bow: -40, tilt: -14 },  // 0  c0r0
  { edge: 'L', off: -20, bow: -40, tilt: -18 },  // 1  c1r0
  { edge: 'T', off: 0, bow: -40, tilt: 10 },     // 2  c2r0
  { edge: 'T', off: 0, bow: -14, tilt: -8 },     // 3  c3r0 (drops between landed neighbours)
  { edge: 'R', off: -20, bow: 40, tilt: 18 },    // 4  c4r0
  { edge: 'R', off: -20, bow: 40, tilt: 14 },    // 5  c5r0
  { edge: 'L', off: 80, bow: 40, tilt: -16 },    // 6  c0r1
  { edge: 'L', off: 80, bow: 40, tilt: -20 },    // 7  c1r1
  { edge: 'B', off: -60, bow: -40, tilt: -12 },  // 8  c2r1
  { edge: 'B', off: 60, bow: 40, tilt: 12 },     // 9  c3r1
  { edge: 'R', off: 80, bow: -40, tilt: 20 },    // 10 c4r1
  { edge: 'R', off: 80, bow: -40, tilt: 16 },    // 11 c5r1
];
const V0 = 3.0, V1 = 0.35;     // Hermite travel: fast entry, still moving (0.35) at the slot -> impact
const travel = (u) => (u * u * u - 2 * u * u + u) * V0 + (-2 * u * u * u + 3 * u * u) + (u * u * u - u * u) * V1;
const travelV = (u) => (3 * u * u - 4 * u + 1) * V0 + (-6 * u * u + 6 * u) + (3 * u * u - 2 * u) * V1;
const SETTLE = 0.3;            // landing squash + rebound, then exact rest

function cardPath(i) {
  const e = ENTRY[i];
  const E = gridSlotL(i);
  let S;
  if (e.edge === 'L') S = { x: -300, y: E.cy + e.off };
  else if (e.edge === 'R') S = { x: LW + 300, y: E.cy + e.off };
  else if (e.edge === 'T') S = { x: E.cx + e.off, y: -260 };
  else S = { x: E.cx + e.off, y: LH + 260 };
  const dx = E.cx - S.x, dy = E.cy - S.y, L = Math.hypot(dx, dy);
  const Q = { x: (S.x + E.cx) / 2 + (-dy / L) * e.bow, y: (S.y + E.cy) / 2 + (dx / L) * e.bow };
  return { S, Q, E: { x: E.cx, y: E.cy }, tilt: e.tilt };
}
const PATHS = COURSES.map((_, i) => cardPath(i));

function quad(P, e) {
  const a = (1 - e) * (1 - e), b = 2 * (1 - e) * e, c = e * e;
  return { x: a * P.S.x + b * P.Q.x + c * P.E.x, y: a * P.S.y + b * P.Q.y + c * P.E.y };
}
function quadD(P, e) {
  return { x: 2 * (1 - e) * (P.Q.x - P.S.x) + 2 * e * (P.E.x - P.Q.x), y: 2 * (1 - e) * (P.Q.y - P.S.y) + 2 * e * (P.E.y - P.Q.y) };
}

// Returns '' before entry, the bare rest card after settling, otherwise the card in flight / landing.
function cardAt(t, i, q) {
  const t0 = q.cardsIn + slotOrder(q)[i] * q.cardStagger;
  const F = q.cardFlight;
  if (t < t0) return '';
  const P = PATHS[i];
  const course = COURSES[i];
  const W = GRID_L.w, H = GRID_L.h;
  const tl = t - t0 - F;
  if (tl >= SETTLE) return restCard(i);
  if (tl < 0) {
    const u = (t - t0) / F;
    const e = travel(u);
    const p = quad(P, e);
    const d = quadD(P, e);
    const ang = Math.atan2(d.y, d.x) * 180 / Math.PI;
    const st = 0.11 * clamp((travelV(u) - V1) / (V0 - V1));
    const rot = (1 - e) * P.tilt;
    // Lifted while flying: the shadow sits further out and closes in on landing.
    const lift = 1 - e;
    let c = rr({ cx: lerp(6, 18, lift), cy: lerp(9, 28, lift), w: W, h: H, r: Math.min(W, H) * 0.11 }, SHADOW);
    c += materialCard({ cx: 0, cy: 0, w: W, h: H, course, shadow: false });
    return `<g transform="translate(${n(p.x)} ${n(p.y)}) rotate(${n(ang)}) scale(${n4(1 + st)} ${n4(1 / (1 + st))}) rotate(${n(-ang + rot)})">${c}</g>`;
  }
  // Landing: keeps the arrival velocity for a few px (overshoot), squashes along the arrival direction, rebounds, rests.
  const d = quadD(P, 1);
  const dl = Math.hypot(d.x, d.y);
  const ux = d.x / dl, uy = d.y / dl;
  const v = dl * V1 / F;                       // arrival speed, px/s
  const tau = 0.05;
  const ov = v * tl * Math.exp(-tl / tau) * (1 - prog(tl, 0.18, SETTLE));
  const sq = -0.14 * Math.sin(2 * Math.PI * tl / SETTLE) * Math.exp(-tl / 0.12); // ~8% squash, ~2% rebound
  const ang = Math.atan2(uy, ux) * 180 / Math.PI;
  const x = P.E.x + ux * ov, y = P.E.y + uy * ov;
  const c = materialCard({ cx: 0, cy: 0, w: W, h: H, course });
  return `<g transform="translate(${n(x)} ${n(y)}) rotate(${n(ang)}) scale(${n4(1 + sq)} ${n4(1 / (1 + sq))}) rotate(${n(-ang)})">${c}</g>`;
}
const n = (v) => Number(v.toFixed(2)).toString();
const n4 = (v) => Number(v.toFixed(4)).toString();

// ---------- Scene ----------
export function draw(t, cues) {
  const q = cues.s2;
  let s = '';

  // Dot anticipation (2.9-3.0): squash before it bursts.
  if (t < q.wipe[0]) {
    const k = prog(t, 2.9, 3.0, inCubic);
    s += `<ellipse cx="${MERGE_L.x}" cy="${MERGE_L.y}" rx="${(36 * (1 + 0.25 * k)).toFixed(2)}" ry="${(36 * (1 - 0.2 * k)).toFixed(2)}" fill="${C.blue}"/>`;
    return s;
  }

  // Morph M2: iris wipe from the dot to a full blue field.
  const wk = prog(t, q.wipe[0], q.wipe[1], iris);
  if (wk < 1) s += `<circle cx="${MERGE_L.x}" cy="${MERGE_L.y}" r="${lerp(36, IRIS_R, wk).toFixed(2)}" fill="${C.blue}"/>`;
  else s += `<rect width="${LW}" height="${LH}" fill="${C.blue}"/>`;

  if (t >= REST_T) return s + headerL() + gridCardsL() + headline(t, q);

  // ----- Bot face -----
  const eyeK = prog(t, q.eyesIn[0], q.eyesIn[1], snap);
  const dotRatio = 56 / 144;
  const blink = lerp(dotRatio, 1, eyeK) * blinkAt(t, q.blink);
  let look = 0;
  if (t > q.look[0] - 0.12) {
    const l1 = prog(t, q.look[0] - 0.12, q.look[0], outCubic);
    const l2 = prog(t, q.look[1] - 0.12, q.look[1], outCubic);
    const l3 = prog(t, q.look[2] - 0.1, q.look[2], outCubic);
    look = -1 * l1 + 2 * l2 - 1 * l3;
  }
  const a = q.toHeader[0];
  // During the leap the eyes lead toward the header (up-left); then the bot watches the cards land (down-right).
  const lookLead = prog(t, a - 0.06, a + 0.1, outCubic) * (1 - prog(t, q.cardsIn - 0.02, q.cardsIn + 0.22, snap));
  const lookDown = prog(t, q.cardsIn, q.cardsIn + 0.3, snap) * (1 - prog(t, 7.2, REST_T, snap));
  const eyeLook = look - 0.8 * lookLead + 0.6 * lookDown;
  const eyeLookY = -0.5 * lookLead + 0.8 * lookDown;

  if (t < a) {
    // Spring in from the dot, then hold big with a small lean into each glance.
    const lt = t - q.faceIn[0];
    const grow = clamp(spring(lt, 2.0, 0.5), 0, 1.25);
    const d = FACE_BIG_L.d * grow;
    const cx = FACE_BIG_L.cx + look * 6;
    const cy = FACE_BIG_L.cy;
    // Pop: a vertical stretch while it shoots out of the dot, then a small counter-squash at the spring's overshoot.
    const st = lt < 0.24 ? 0.1 * Math.sin(Math.PI * clamp(lt / 0.24)) : -0.035 * Math.sin(Math.PI * clamp((lt - 0.24) / 0.2));
    const face = botFace({ cx, cy, d, ring: d > 4 ? RING_BIG * Math.min(1, grow) : 0, blink, look: eyeLook, lookY: eyeLookY });
    s += Math.abs(st) > 1e-4 ? g(face, { sx: 1 / (1 + st), sy: 1 + st, ox: cx, oy: cy }) : face;
  } else if (!faceSettled(t, q)) {
    const fp = facePos(t, q);
    const h = 1 / 120;
    const p0 = facePos(t - h, q), p1 = facePos(t + h, q);
    const vx = (p1.cx - p0.cx) / (2 * h), vy = (p1.cy - p0.cy) / (2 * h);
    const speed = Math.hypot(vx, vy);
    const st = 0.12 * clamp(speed / 7000);
    const ang = Math.atan2(vy, vx) * 180 / Math.PI;
    const ring = Math.max(0, lerp(RING_BIG, RING_HEAD, fp.k));
    const face = botFace({ cx: fp.cx, cy: fp.cy, d: fp.d, ring, blink, look: eyeLook, lookY: eyeLookY });
    s += stretchG(face, fp.cx, fp.cy, ang, st);
  } else {
    s += headerFaceL({ blink, look: eyeLook, lookY: eyeLookY });
  }

  // ----- Lockup: per-glyph rise, then it trails the face into the header -----
  const kl = lockupK(t, q);
  if (kl >= 1) {
    s += headerLockupL();
  } else {
    const lt = lockupTransformL(kl);
    const arc = Math.sin(Math.PI * kl) * 40;
    const lock = lockup(LW / 2, LOCK_BIG_L.y, LOCK_BIG_L.size, {
      fill: '#ffffff',
      reveal: (i) => {
        const k = prog(t, q.wordmark + i * 0.03, q.wordmark + i * 0.03 + 0.4, snap);
        return { o: clamp(k * 1.5), dy: (1 - k) * 56 };
      },
    });
    s += g(lock, { x: lt.x + DIR.px * arc, y: lt.y + DIR.py * arc, s: lt.s, ox: lt.ox, oy: lt.oy });
  }

  // ----- Positioning line, out before the header move -----
  s += lineReveal(q.positioningText, LW / 2, POS_Y, t, q.positioning, { size: POS_SIZE, weight: 500, fill: C.blueSoft, dur: 0.5, out: { t0: q.toHeader[0] - 0.12, dur: 0.3 } });

  // ----- Headline (drawn before the cards, so a card in flight would always pass in front) -----
  s += headline(t, q);

  // ----- Cards: later arrivals on top -----
  const so = slotOrder(q);
  const order = COURSES.map((_, i) => i).sort((x, y) => so[x] - so[y]);
  for (const i of order) s += cardAt(t, i, q);
  return s;
}

function headline(t, q) {
  // Short exit (done by ~7.89 s) so S3's falling cards never cross a half-cut headline (landscape review N2).
  return lineReveal(q.headlineText, LW / 2, HEAD_Y, t, q.headline, { size: HEAD_SIZE, weight: 900, fill: '#ffffff', dur: 0.5, out: { t0: q.headlineOut, dur: 0.14 } });
}

// The headline finishes its exit on top of S3's opening morph (film.js draws overlays after all scenes).
export const overlay = {
  range: [7.85, 8.1],
  draw: (t, cues) => headline(t, cues.s2),
};
