// S2 brand (3-8 s): the dot bursts into a blue field, the StudyHub bot appears, then gathers course materials into a grid.
import { C, FONT_CN, rr, g, text, prog, clamp, lerp, spring, snap, glide, outCubic, inCubic, outBack, bezier, rng, lineReveal, botFace, blinkAt } from '../core.js';
import { lockup, lockupMetrics, materialCard, COURSES, GRID, gridSlot } from '../shared.js';
import { MERGE } from './s1.js';

export const range = [2.9, 7.85];
// Fast-start iris: visibly bursts on the first frame after the 3.0 s drop hit (review P2-4).
const iris = bezier(0.25, 0.3, 0.1, 1);

export const FACE_BIG = { cx: 540, cy: 860, d: 320 };
export const FACE_HEAD = { cx: 150, cy: 250, d: 96 };
export const LOCK_BIG = { y: 1130, size: 108 }; // 108 px keeps the lockup inside x 96..960 (review B1)
export const LOCK_HEAD = { left: 224, y: 268, size: 46 };

// Shared with S3 so the header hand-off matches.
export function headerState(t, q) {
  // The face leads (fast-out curve, slight arc to the left); the lockup follows lockupDelay later so they never stack.
  const k = prog(t, q.toHeader[0], q.toHeader[1] - 0.05, bezier(0.33, 0, 0.12, 1));
  const kl = prog(t, q.toHeader[0] + q.lockupDelay, q.toHeader[1], glide);
  const arc = Math.sin(Math.PI * k) * 60;
  return {
    k,
    kl,
    face: { cx: lerp(FACE_BIG.cx, FACE_HEAD.cx, k) - arc, cy: lerp(FACE_BIG.cy, FACE_HEAD.cy, k), d: lerp(FACE_BIG.d, FACE_HEAD.d, k) },
  };
}

export function lockupTransform(k) {
  const mBig = lockupMetrics(LOCK_BIG.size);
  const s = lerp(1, LOCK_HEAD.size / LOCK_BIG.size, k);
  // Visual centre of the big lockup, and where that centre must land in the header.
  const ox = 540, oy = LOCK_BIG.y - LOCK_BIG.size * 0.36;
  const tx = LOCK_HEAD.left + (mBig.w * LOCK_HEAD.size / LOCK_BIG.size) / 2;
  const ty = LOCK_HEAD.y - LOCK_HEAD.size * 0.36;
  return { x: lerp(0, tx - ox, k), y: lerp(0, ty - oy, k), s, ox, oy };
}

// Card flight: from a seeded off-screen point along an arc into its grid slot.
export function cardState(t, i, q) {
  const R = rng(100 + i * 17);
  const order = q.cardOrder[i];
  const t0 = q.cardsIn + order * q.cardStagger;
  const u = prog(t, t0, t0 + q.cardFlight, (x) => x);
  const slot = gridSlot(i);
  const side = i % 3 === 0 ? -1 : i % 3 === 2 ? 1 : (R() < 0.5 ? -1 : 1);
  const sx = side < 0 ? -260 : 1340;
  const sy = slot.cy + (R() - 0.5) * 700;
  const e = snap(u);
  const cx0 = lerp(sx, slot.cx, e);
  const cy0 = lerp(sy, slot.cy, e) - Math.sin(Math.PI * e) * 120;
  const rot = (1 - e) * (side * (18 + R() * 16));
  const land = u >= 1 ? Math.sin(Math.min(1, (t - t0 - q.cardFlight) / 0.28) * Math.PI) * Math.exp(-6 * (t - t0 - q.cardFlight)) : 0;
  return { u, cx: cx0, cy: cy0, rot, sy: 1 - 0.08 * land, sx: 1 + 0.05 * land, t0 };
}

export function draw(t, cues) {
  const q = cues.s2;
  let s = '';

  // Dot anticipation (2.9-3.0): squash before it bursts.
  if (t < q.wipe[0]) {
    const k = prog(t, 2.9, 3.0, inCubic);
    s += `<ellipse cx="${MERGE.x}" cy="${MERGE.y}" rx="${(36 * (1 + 0.25 * k)).toFixed(2)}" ry="${(36 * (1 - 0.2 * k)).toFixed(2)}" fill="${C.blue}"/>`;
    return s;
  }

  // Morph M2: iris wipe from the dot to a full blue field.
  const wk = prog(t, q.wipe[0], q.wipe[1], iris);
  if (wk < 1) s += `<circle cx="${MERGE.x}" cy="${MERGE.y}" r="${lerp(36, 1250, wk).toFixed(2)}" fill="${C.blue}"/>`;
  else s += `<rect width="1080" height="1920" fill="${C.blue}"/>`;

  // Bot face: spring in, eyes grow from dots to capsules (M3), blink, glance, then shrink to the header (M4).
  const hs = headerState(t, q);
  const grow = clamp(spring(t - q.faceIn[0], 2.0, 0.5), 0, 1.25);
  const eyeK = prog(t, q.eyesIn[0], q.eyesIn[1], snap);
  const dotRatio = 56 / 144;
  let blink = lerp(dotRatio, 1, eyeK) * blinkAt(t, q.blink);
  let look = 0;
  if (t > q.look[0] - 0.12) {
    const l1 = prog(t, q.look[0] - 0.12, q.look[0], outCubic);
    const l2 = prog(t, q.look[1] - 0.12, q.look[1], outCubic);
    const l3 = prog(t, q.look[2] - 0.1, q.look[2], outCubic);
    look = -1 * l1 + 2 * l2 - 1 * l3;
  }
  // While the cards arrive the bot looks down at them.
  const lookDown = prog(t, q.cardsIn, q.cardsIn + 0.3, snap) * (1 - prog(t, 7.2, 7.6, snap));
  const d = hs.face.d * (hs.k > 0 ? 1 : grow);
  const squash = Math.sin(Math.PI * hs.k) * 0.08;
  const ring = lerp(10, 4, hs.k);
  const face = botFace({ cx: hs.face.cx, cy: hs.face.cy, d, ring: d > 4 ? ring * Math.min(1, grow) : 0, blink, look: look + lookDown * 0.6, lookY: lookDown * 0.8 });
  s += g(face, { sx: 1 - squash, sy: 1 + squash, ox: hs.face.cx, oy: hs.face.cy });

  // Lockup: per-glyph rise, then scale into the header.
  const lt = lockupTransform(hs.kl);
  const lock = lockup(540, LOCK_BIG.y, LOCK_BIG.size, {
    fill: '#ffffff',
    reveal: (i) => {
      const k = prog(t, q.wordmark + i * 0.03, q.wordmark + i * 0.03 + 0.4, snap);
      return { o: clamp(k * 1.5), dy: (1 - k) * 60 };
    },
  });
  s += g(lock, { x: lt.x, y: lt.y, s: lt.s, ox: lt.ox, oy: lt.oy });

  // Positioning line, out before the header move.
  s += lineReveal(q.positioningText, 540, 1236, t, q.positioning, { size: 50, weight: 500, fill: '#dbe6fe', dur: 0.5, out: { t0: q.toHeader[0] - 0.12, dur: 0.3 } });

  // Cards fly in and land in the grid.
  for (let i = 0; i < COURSES.length; i++) {
    const cs = cardState(t, i, q);
    if (cs.u <= 0) continue;
    const card = materialCard({ cx: cs.cx, cy: cs.cy, w: GRID.w, h: GRID.h, course: COURSES[i] });
    s += g(card, { rot: cs.rot, sx: cs.sx, sy: cs.sy, ox: cs.cx, oy: cs.cy + GRID.h / 2 });
  }

  // Headline under the grid (until the S3 hand-off; then the overlay below keeps drawing it).
  s += headline(t, q);
  return s;
}

function headline(t, q) {
  return lineReveal(q.headlineText, 540, 1560, t, q.headline, { size: 84, weight: 900, fill: '#ffffff', dur: 0.5, out: { t0: q.headlineOut, dur: 0.3 } });
}

// The headline finishes its exit on top of S3's opening morph (film.js draws overlays after all scenes).
export const overlay = {
  range: [7.85, 8.1],
  draw: (t, cues) => headline(t, cues.s2),
};
