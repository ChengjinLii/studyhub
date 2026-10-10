// Landscape S1 hook (0-3 s, 1920x1080): headline on the left, the group chat as a column on the right.
// Unanswered "求资料" bubbles stack up (old ones pushed up), wait, wind up, then implode into one blue dot:
// each bubble retracts into its sender (tail first, the edge wiping the text), the sender turns into a blue dot,
// and the seven dots are pulled along one swirl into MERGE_L, where they pool into a dot of radius 36.
// Same cues as the portrait scene (src/scenes/s1.js); only the composition and the implode choreography are new.
import { C, FONT_CN, rr, rrPath, g, text, measure, charsReveal, prog, clamp, lerp, mixColor, spring, snap, outCubic, inOutCubic, inOutSine, botFace, blinkAt, num } from '../../core.js';
import { FACE } from '../../shared.js';
import { MERGE_L } from '../layout.js';

export const range = [0, 3.0];

// ---------- Composition ----------
const HEAD = { x: 150, y: 578, size: 104 };        // left-aligned, optically centred on the frame's horizontal axis
const COL = { left: 1080, right: 1780, cy: 540 };  // chat column: others' avatars hug `left`, "me" avatars hug `right`
const AV_D = 80;
const AV_GAP = 20;   // avatar edge to bubble edge
const B_H = 92;
const B_R = 32;
const PITCH = 114;
const FONT = 40;
const PAD = 34;
const BASE = 14.5;   // text baseline below the bubble centre
const SHADOW = 'rgba(15,23,42,0.10)';
const SH = { x: 6, y: 8 };
// Bubble tail (relative to the bubble's top edge and its avatar-side edge), scaled from the portrait tail.
const TAIL = { in: 2, out: 17, tipY: 11, y0: 19, y1: 41 };

// ---------- Implode (M1) ----------
const DOT_R = 36;
const D_SENDER = 64;                       // a collapsed row: one blue dot this wide, at its avatar
const D_ARRIVE = (2 * DOT_R) / Math.sqrt(7); // seven arriving dots pool into one of radius 36 (area kept)
const STAGGER = 0.02;                      // bottom row first ("rewind"), under a frame apart
const COLLAPSE = 0.16;
const PULL_DELAY = 0.06;                   // the dot starts to drift before the bubble has fully retracted
// Arrival: pull time grows with distance; every dot is in by ARRIVE_END, so the pool is exactly r 36 at 2.90,
// the moment S2 starts drawing its own (squashing) dot on top.
const ARRIVE_END = 2.885;
const POOL = 0.015;                        // each arrival blends into the pool over +-POOL s
const arriveAt = (ts, dist) => Math.min(ARRIVE_END, ts + 0.1 + dist / 2600);
const pull = (x) => Math.pow(x, 1.6);      // accelerating suction: arrives fast, no clump at the centre

// Static geometry of bubble i with the stack top at `top`.
function geom(b, i, top) {
  const me = b.face === 'me';
  const bw = measure(b.text, FONT, 500, FONT_CN) + PAD * 2;
  const avx = me ? COL.right - AV_D / 2 : COL.left + AV_D / 2;
  const bLeft = me ? avx - AV_D / 2 - AV_GAP - bw : avx + AV_D / 2 + AV_GAP;
  const dir = me ? 1 : -1; // tail side
  const edge = me ? bLeft + bw : bLeft;
  const cy = top + i * PITCH;
  return { me, bw, avx, bLeft, bcx: bLeft + bw / 2, cy, dir, tipX: edge + dir * TAIL.out, tipY: cy - B_H / 2 + TAIL.tipY };
}

// The stack stays centred on COL.cy: each new bubble enters at the bottom and pushes the older ones up by half a pitch.
function stackTop(t, q) {
  let c = 0;
  for (let i = 1; i < q.bubbles.length; i++) c += prog(t, q.bubbles[i].t - 0.02, q.bubbles[i].t + 0.34, snap);
  return COL.cy - c * PITCH / 2;
}

// Tail triangle on the `dir` edge of a bubble box; k 1 = full tail, 0 = retracted into the edge.
function tail(cx, cy, w, h, dir, k, s, fill) {
  if (k <= 0.01) return '';
  const ex = cx + dir * w / 2;
  const top = cy - h / 2;
  const bx = ex - dir * TAIL.in * s, by = top + (TAIL.y0 + TAIL.y1) / 2 * s;
  const P = (x, y) => `${num(lerp(bx, x, k))},${num(lerp(by, y, k))}`;
  return `<path d="M${P(ex - dir * TAIL.in * s, top + TAIL.y0 * s)} L${P(ex + dir * TAIL.out * s, top + TAIL.tipY * s)} L${P(ex - dir * TAIL.in * s, top + TAIL.y1 * s)} Z" fill="${fill}"/>`;
}

// Quadratic arc from p0 into MERGE_L. Every path bows the same way (left normal of its chord): one swirl into the drain.
function arc(p0, bend) {
  const M = MERGE_L;
  const dx = M.x - p0.x, dy = M.y - p0.y;
  const L = Math.hypot(dx, dy) || 1;
  const c = { x: p0.x + dx * 0.5 + (dy / L) * L * bend, y: p0.y + dy * 0.5 + (-dx / L) * L * bend };
  return (u) => {
    const a = (1 - u) * (1 - u), b = 2 * (1 - u) * u, d = u * u;
    const vx = 2 * (1 - u) * (c.x - p0.x) + 2 * u * (M.x - c.x);
    const vy = 2 * (1 - u) * (c.y - p0.y) + 2 * u * (M.y - c.y);
    return { x: a * p0.x + b * c.x + d * M.x, y: a * p0.y + b * c.y + d * M.y, ang: Math.atan2(vy, vx) * 180 / Math.PI };
  };
}

// Place local content at (x, y), stretched by k along the direction of travel (thinner across it).
function along(content, x, y, ang, k) {
  if (Math.abs(k) < 1e-3) return `<g transform="translate(${num(x)} ${num(y)})">${content}</g>`;
  return `<g transform="translate(${num(x)} ${num(y)}) rotate(${ang.toFixed(2)}) scale(${(1 + k).toFixed(4)} ${(1 - k * 0.8).toFixed(4)}) rotate(${(-ang).toFixed(2)})">${content}</g>`;
}

export function draw(t, cues) {
  const q = cues.s1;
  const n = q.bubbles.length;
  const [a0, a1] = q.anticipate;
  const i0 = q.implode[0];
  let s = '';

  // ---------- Headline: per-glyph pop in; the "？" keeps asking while nobody answers; rise out. ----------
  const head = q.headline;
  const body = head.slice(0, -1);
  const qm = head.slice(-1);
  const nb = Array.from(body).length;
  const hOpts = { size: HEAD.size, weight: 900, fill: C.ink, anchor: 'start', stagger: 0.035, dur: 0.45, rise: 0.55 };
  const hOut = { stagger: 0.018, dur: 0.28, rise: 0.6 };
  s += charsReveal(body, HEAD.x, HEAD.y, t, q.headlineIn, { ...hOpts, out: { ...hOut, t0: q.headlineOut } });
  const qx = HEAD.x + measure(body, HEAD.size, 900, FONT_CN);
  // The question mark tilts right, then left (pivot at its foot) in the waiting beat.
  const tilt = Math.sin(prog(t, 1.55, 2.25, inOutSine) * Math.PI * 2) * 9 * Math.sin(prog(t, 1.55, 2.25) * Math.PI);
  s += g(charsReveal(qm, qx, HEAD.y, t, q.headlineIn + nb * 0.035, { ...hOpts, out: { ...hOut, t0: q.headlineOut + nb * hOut.stagger } }),
    { rot: tilt, ox: qx + HEAD.size * 0.22, oy: HEAD.y });

  // ---------- Chat column ----------
  const top = stackTop(t, q);
  const fTop = COL.cy - (n - 1) * PITCH / 2; // stack top once every bubble is in
  const ant = prog(t, a0, a1, outCubic) * (1 - prog(t, i0, i0 + 0.14, inOutSine));
  const grow = 1 + 0.05 * ant; // anticipation: swell 5% ...
  let pooled = 0;              // arrivals so far (smoothed), for the merge dot's area
  const travellers = [];

  for (let i = 0; i < n; i++) {
    const b = q.bubbles[i];
    const lt = t - b.t;
    const rank = n - 1 - i;
    const st = i0 + rank * STAGGER;
    const ts = st + PULL_DELAY;
    const G = geom(b, i, top);
    const te = arriveAt(ts, Math.hypot(G.avx - MERGE_L.x, (fTop + i * PITCH) - MERGE_L.y));
    pooled += prog(t, te - POOL, te + POOL);
    if (lt < -0.07 || t >= te) continue;

    const color = G.me ? C.ink : FACE[b.face];
    const bFill = G.me ? C.blue : C.paper;
    const tFill = G.me ? '#ffffff' : C.ink;
    const seed = (i * 0.37 + 0.11) % 1;

    // Waiting beat: soft bob, the others glance around ("anyone?"), "me" watches the others; two blinks only.
    const bob = Math.sin((t * 2.2 + seed * 2) * Math.PI) * 3 * prog(t, 1.2, 1.6);
    const look = G.me ? -0.7 : Math.sin(t * 5.5 + seed * 9) * 0.9 * prog(t, 1.35, 1.7);
    const lookY = G.me ? -0.2 : -0.35 * prog(t, 1.35, 1.7);
    const blink = i === 1 ? blinkAt(t, 1.78) : i === 5 ? blinkAt(t, 2.08) : 1;

    // ... and lean away from the merge point before being pulled in.
    const lx = G.bcx - MERGE_L.x, ly = G.cy - MERGE_L.y, lL = Math.hypot(lx, ly) || 1;
    const ox = (lx / lL) * 12 * ant, oy = (ly / lL) * 12 * ant + bob;

    // Rest geometry at time t (absolute), with the swell applied about the tail tip.
    const T = { x: G.tipX + ox, y: G.tipY + oy };
    const sc = (x, y) => ({ x: T.x + (x + ox - T.x) * grow, y: T.y + (y + oy - T.y) * grow });
    const bc = sc(G.bcx, G.cy);
    const A = { x: G.avx + ox, y: G.cy + oy };

    const c = prog(t, st, st + COLLAPSE);
    if (c <= 0) {
      // Entrance: the avatar pops two frames early; the bubble springs out of its tail, uniform while it emerges,
      // then a little jelly around full size (about 10% taller than wide on the overshoot, so the overshoot never
      // pushes text out of SAFE).
      const kAv = clamp(spring(lt + 0.07, 2.6, 0.45), 0, 1.3);
      const kB = clamp(spring(lt, 2.4, 0.42), 0, 1.3);
      const jelly = -0.35 * (kB - 1) * clamp((kB - 0.7) / 0.25);
      s += g(botFace({ cx: A.x, cy: A.y, d: AV_D, shape: 0, body: color, look, lookY, blink, eyeScale: 0.92 }), { s: kAv * grow, ox: A.x, oy: A.y });
      const w = G.bw * grow, h = B_H * grow, r = B_R * grow;
      let bb = rr({ cx: bc.x + SH.x, cy: bc.y + SH.y, w, h, r }, SHADOW);
      bb += tail(bc.x, bc.y, w, h, G.dir, 1, grow, bFill);
      bb += rr({ cx: bc.x, cy: bc.y, w, h, r }, bFill);
      const tp = sc(G.bLeft + PAD, G.cy + BASE);
      bb += text(b.text, tp.x, tp.y, { size: FONT * grow, weight: 500, fill: tFill, anchor: 'start' });
      s += g(bb, { sx: kB * (1 + jelly), sy: kB * (1 - jelly), ox: T.x, oy: T.y });
      continue;
    }

    // ---------- Morph M1, part 1: the bubble retracts into its sender (card -> capsule -> circle). ----------
    // Local coordinates centred on the avatar, so the whole row can ride the swirl as one piece.
    const cn = outCubic(c), cf = inOutCubic(c);
    const restL = bc.x - G.bw * grow / 2 - A.x, restR = bc.x + G.bw * grow / 2 - A.x;
    const near = G.me ? restR : restL, far = G.me ? restL : restR;
    const dIn = D_SENDER - 12;                         // the bubble ends as a circle hidden behind its sender
    const nearX = lerp(near, G.dir * dIn / 2, cn);     // the tail edge slides in under the avatar first
    const farX = lerp(far, -G.dir * dIn / 2, cf);      // the far edge sweeps across the text
    const h = lerp(B_H * grow, dIn, cf);
    const w = Math.max(h, Math.abs(farX - nearX));
    const cx = (nearX + farX) / 2;
    const cy = lerp(bc.y - A.y, 0, cf);
    const r = (Math.min(w, h) / 2) * lerp(B_R / (B_H / 2), 1, clamp(c / 0.35));
    const fill = mixColor(bFill, C.blue, prog(c, 0.25, 0.75));
    let m = '';
    if (c < 1) {
      const shK = 1 - prog(c, 0, 0.35);
      if (shK > 0) m += rr({ cx: cx + SH.x * shK, cy: cy + SH.y * shK, w, h, r }, SHADOW);
      m += tail(cx, cy, w, h, G.dir, 1 - prog(c, 0, 0.3, outCubic), grow, fill);
      m += rr({ cx, cy, w, h, r }, fill);
      const to = 1 - prog(c, 0.0, 0.3); // text fades before the far edge sweeps across it (landscape review N3)
      if (to > 0.01) {
        const id = `s1Lc${i}`;
        const tp = sc(G.bLeft + PAD, G.cy + BASE);
        m += `<defs><clipPath id="${id}"><path d="${rrPath(cx, cy, w, h, r)}"/></clipPath></defs>`;
        m += `<g clip-path="url(#${id})">${text(b.text, tp.x - A.x, tp.y - A.y, { size: FONT * grow, weight: 500, fill: tFill, anchor: 'start', o: to })}</g>`;
      }
      // The sender, on top: gulps the bubble (squash along the row), turns brand blue, eyes close up.
      const d = lerp(AV_D * grow, D_SENDER, cn);
      const gulp = Math.sin(Math.PI * prog(c, 0.55, 1));
      // The blue pours in from the bubble side: a disc tangent to that edge grows across the face, so the old colour
      // leaves as a shrinking crescent (never a ring that would read as an outline). Base disc dropped once covered.
      const iris = prog(c, 0.25, 0.8, inOutSine);
      let face = iris < 0.98 ? rr({ cx: 0, cy: 0, w: d, h: d, r: d / 2 }, color) : '';
      if (iris > 0) {
        const ri = iris < 0.98 ? iris * (d / 2 + 0.6) : d / 2;
        face += rr({ cx: -G.dir * (d / 2 + 0.6 - ri), cy: 0, w: ri * 2, h: ri * 2, r: ri }, C.blue);
      }
      face += botFace({ cx: 0, cy: 0, d, shape: 0, body: 'none', look: look * (1 - c), lookY: lookY * (1 - c), blink, eyeScale: 0.92 * (1 - prog(c, 0.2, 0.65, inOutSine)) });
      m += g(face, { sx: 1 + 0.1 * gulp, sy: 1 - 0.08 * gulp });
    } else {
      m += rr({ cx: 0, cy: 0, w: D_SENDER, h: D_SENDER, r: D_SENDER / 2 }, C.blue);
    }

    // ---------- Morph M1, part 2: the row, now a dot, is pulled along the swirl, shrinking and stretching. ----------
    const u = prog(t, ts, te);
    const tr = pull(u);
    const p = arc(A, 0.28 + 0.04 * (i % 3))(tr);
    const shrink = lerp(1, D_ARRIVE / D_SENDER, prog(u, 0.2, 1, inOutSine));
    const str = 0.14 * Math.sin((Math.PI / 2) * u) * c;
    const piece = shrink < 1 ? g(m, { s: shrink }) : m;
    travellers.push({ rank, svg: along(piece, p.x, p.y, p.ang, str) });
  }
  // Rows that started first (bottom) fly over the later ones.
  travellers.sort((A, B) => B.rank - A.rank);
  for (const tv of travellers) s += tv.svg;

  // ---------- The merge dot: the arriving dots pool into it (area adds up); exactly r 36 from 2.90 s on. ----------
  // Hand-off to S2: one blue dot, r 36, at MERGE_L from cues.s1.merge (2.95) until 3.0.
  const rPool = DOT_R * Math.sqrt(Math.min(n, pooled) / n);
  if (rPool > 0.3) s += `<circle cx="${MERGE_L.x}" cy="${MERGE_L.y}" r="${num(t >= q.merge ? DOT_R : rPool)}" fill="${C.blue}"/>`;
  return s;
}

export function background() {
  return C.indigo;
}
