// S1 hook (0-3 s): a group chat fills with unanswered "求资料" bubbles, then they implode into one blue dot.
import { C, FONT_CN, rr, g, text, measure, charsReveal, prog, clamp, lerp, mixColor, spring, snap, glide, inCubic, outCubic, rng } from '../core.js';
import { student, FACE } from '../shared.js';

export const range = [0, 3.0];
export const MERGE = { x: 540, y: 860 }; // where all bubbles meet; S2's face grows from here

const AV_X = 150;
const AV_D = 92;
const B_GAP = 70;     // avatar centre to bubble edge
const B_H = 110;
const B_R = 38;
const TOP = 630;
const PITCH = 136;
const FONT = 44;
const AV_X_ME = 1080 - 150 - 36; // "me" sits on the right, kept clear of the platform's right rail

export function draw(t, cues) {
  const q = cues.s1;
  let s = '';
  const [a0, a1] = q.anticipate;
  const [i0, i1] = q.implode;
  const ant = prog(t, a0, a1, outCubic) * (1 - prog(t, i0, i0 + 0.12));

  // Headline: per-glyph pop in, rise out.
  s += charsReveal(q.headline, 540, 400, t, q.headlineIn, {
    size: 96, weight: 900, fill: C.ink, stagger: 0.035, dur: 0.45, rise: 0.55,
    out: { t0: q.headlineOut, stagger: 0.018, dur: 0.28, rise: 0.6 },
  });

  const R = rng(7);
  const n = q.bubbles.length;
  // Draw from the newest to the oldest so the implode overlaps read top-down.
  for (let i = 0; i < n; i++) {
    const b = q.bubbles[i];
    const lt = t - b.t;
    if (lt < -0.06) continue;
    const jitter = R();
    const me = b.face === 'me';
    const color = me ? C.ink : FACE[b.face];
    const tw = measure(b.text, FONT, 500, FONT_CN);
    const bw = tw + 76;
    const cy = TOP + i * PITCH;
    const avx = me ? AV_X_ME : AV_X;
    const bLeft = me ? avx - B_GAP - bw : avx + B_GAP;
    const bcx = bLeft + bw / 2;
    const tailX = me ? bLeft + bw : bLeft;
    const dir = me ? 1 : -1;
    const bFill = me ? C.blue : C.paper;
    const tFill = me ? '#ffffff' : C.ink;

    // Entrance: avatar pops 2 frames early, bubble springs out from its tail.
    const kAv = clamp(spring(lt + 0.06, 2.6, 0.45), 0, 1.3);
    const kB = clamp(spring(lt, 2.4, 0.42), 0, 1.3);
    // Idle: soft bob and the avatar glances around while nobody answers.
    const bob = Math.sin((t * 2.2 + jitter * 6.28) * Math.PI) * 3 * prog(t, 1.2, 1.6);
    const look = Math.sin(t * 5.5 + jitter * 9) * 0.9 * prog(t, 1.35, 1.7);
    const grow = 1 + 0.06 * ant;

    // Implode: each element morphs to a circle and swoops along an arc to MERGE.
    const st = i0 + 0.016 * (n - 1 - i);
    const u = prog(t, st, i1, glide);
    // Text fades out just before its bubble starts to travel, so it never smears across the fast move (review P2-3).
    const textO = 1 - prog(t, st - 0.12, st + 0.02);
    if (u >= 1) continue;

    if (u <= 0) {
      // Avatar.
      s += g(student({ cx: avx, cy: cy + bob, d: AV_D, color, look: me ? -0.6 : look }), { s: kAv * grow, ox: avx, oy: cy });
      // Bubble with tail; others are white, "me" is brand blue.
      let body = '';
      body += rr({ cx: bcx + 6, cy: cy + 9 + bob, w: bw, h: B_H, r: B_R }, 'rgba(15,23,42,0.08)');
      body += `<path d="M${tailX - dir * 2},${cy - 32 + bob} L${tailX + dir * 20},${cy - 42 + bob} L${tailX - dir * 2},${cy - 6 + bob} Z" fill="${bFill}"/>`;
      body += rr({ cx: bcx, cy: cy + bob, w: bw, h: B_H, r: B_R }, bFill);
      body += text(b.text, bLeft + 38, cy + 16 + bob, { size: FONT, weight: 500, fill: tFill, anchor: 'start', o: textO });
      s += g(body, { s: kB * grow, ox: tailX + dir * 20, oy: cy - 42 });
      continue;
    }

    // --- Morph M1: bubble -> circle -> dot, travelling on a curved path with squash & stretch. ---
    const shrinkTo = 120 * (1 - u) + 44 * u;
    const morphK = clamp(u / 0.45);
    const w = lerp(bw * grow, shrinkTo, outCubic(morphK));
    const h = lerp(B_H * grow, shrinkTo, outCubic(morphK));
    const travel = prog(u, 0.15, 1, (x) => x);
    const sx0 = bcx, sy0 = cy;
    const ctrlX = lerp(sx0, MERGE.x, 0.5) + (i % 2 ? 160 : -160);
    const ctrlY = lerp(sy0, MERGE.y, 0.5) - 120;
    const px = (1 - travel) ** 2 * sx0 + 2 * (1 - travel) * travel * ctrlX + travel ** 2 * MERGE.x;
    const py = (1 - travel) ** 2 * sy0 + 2 * (1 - travel) * travel * ctrlY + travel ** 2 * MERGE.y;
    const vx = 2 * (1 - travel) * (ctrlX - sx0) + 2 * travel * (MERGE.x - ctrlX);
    const vy = 2 * (1 - travel) * (ctrlY - sy0) + 2 * travel * (MERGE.y - ctrlY);
    const ang = Math.atan2(vy, vx) * 180 / Math.PI;
    const str = 0.14 * Math.sin(Math.PI * travel);
    const fill = mixColor(bFill, C.blue, prog(u, 0.25, 0.75));
    let m = rr({ cx: 0, cy: 0, w, h, r: Math.min(w, h) / 2 * lerp(B_R / (B_H / 2), 1, morphK) }, fill);
    const to = textO;
    if (to > 0) m += text(b.text, -w / 2 + 38, 16, { size: FONT, weight: 500, fill: tFill, anchor: 'start', o: to });
    const body = `<g transform="translate(${px.toFixed(2)} ${py.toFixed(2)}) rotate(${ang.toFixed(2)}) scale(${(1 + str).toFixed(3)} ${(1 - str).toFixed(3)}) rotate(${(-ang).toFixed(2)})">${m}</g>`;
    s += body;
    // Avatar follows slightly behind and dissolves into the dot.
    const ua = prog(t, st + 0.03, i1, glide);
    const ax = lerp(avx, MERGE.x, ua);
    const ay = lerp(cy, MERGE.y, ua) - Math.sin(Math.PI * ua) * 90;
    const ad = lerp(AV_D, 30, ua) * (1 - prog(ua, 0.8, 1));
    if (ad > 1) s += student({ cx: ax, cy: ay, d: ad, color: mixColor(color, C.blue, ua) });
  }

  // The merged dot (hand-off to S2 at 2.95 s).
  const mk = prog(t, i1 - 0.06, i1, outCubic);
  if (mk > 0 && t < 3.0) {
    s += `<circle cx="${MERGE.x}" cy="${MERGE.y}" r="${(36 * mk).toFixed(2)}" fill="${C.blue}"/>`;
  }
  return s;
}

export function background(t) {
  return C.indigo;
}
