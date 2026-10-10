// Landscape S4 share (15-20 s), the hero moment, re-composed for 16:9.
// One note is copied out in three waves to elliptical rings of classmates that spread across the width;
// the outer ring runs off every edge of the frame (more people beyond it). Each one who receives a copy lights up.
// Then the network folds into S5's "users" icon (column 0) and a soft iris opens from the hub.
// Timing comes from cues.s4 exactly as in the portrait scene (src/scenes/s4.js); only the geometry is new.
import { C, FONT_CN, rr, g, text, measure, prog, clamp, lerp, mixColor, spring, snap, glide, outCubic, inCubic, inQuad, inOutSine, outBack, inBack, bezier, rng, num } from '../../core.js';
import { FACE } from '../../shared.js';
import { student, heroNoteL, HERO_NOTE_L, DATA_L, FACES_ICON, facesIcon } from '../layout.js';

export const range = [15.0, 20.0];

const HUB = { x: HERO_NOTE_L.cx, y: HERO_NOTE_L.cy };
const HUB_S = 0.62;            // the hub settles to this scale so ring 1 has air around it
// Elliptical orbits (rx > ry) so the network uses the width. Ring 3 is larger than the frame: its faces peek in
// at the four corners and the left/right edges, and the four nearest the headlines sit fully off-frame
// (only their spokes run out under the text), so nothing crowds the title bands. The parametric angle stays j/count*2pi + w*0.4 (+drift) with x = cx + rx*sin(a),
// because audio/compose.py pans each copy's chime by sin of that same angle.
const RINGS = [{ rx: 330, ry: 200 }, { rx: 640, ry: 285 }, { rx: 960, ry: 640 }];
const RING_D = [88, 78, 70];   // face diameters, rings 1-3
const WAVE_OFF = 0.4;          // angle offset per wave (rad); must match compose.py
const ROT = 6;                 // total clockwise drift of the network along its orbits, degrees
const CYCLE = ['blue', 'teal', 'amber', 'violet', 'sky'];
const CYCLE_OFF = [4, 0, 1];   // chosen so the three faces that become S5's icon already are teal / amber / blue
// Faces that become the S5 "users" icon: `${wave}:${j}` -> index into FACES_ICON.
// 1:6 already sits on the icon slot at the collapse; 0:3 comes in from the right, 2:9 drops from the top-left corner.
const ICON = { '1:6': 0, '0:3': 1, '2:9': 2 };
const ICON_C = { x: DATA_L.cols[0].x, y: DATA_L.iconY };
const TXT = 96;                // headline size
const LINE_A_Y = 171;          // baselines: top band and bottom band, centred
const LINE_B_Y = 973;
const KNOCK_PAD = { x: 30, y: 18 };
// Ink halo painted under each headline glyph: the two ring-3 copies that fly off the top edge cross the
// title for ~2 frames, and the halo keeps the white glyphs separate from the white pages behind them.
const GLYPH_HALO = { stroke: C.ink, 'stroke-width': 14, 'stroke-linejoin': 'round', 'paint-order': 'stroke' };
const BEND = 0.3;              // copy flight arcs bulge clockwise by this fraction of their length
const PULSE_V = 2400;          // pulse dot speed, px/s (the far corners are ~900 px out)
const PULSE_LEN = 54;          // pulse streak length
const CIRCLE_D = 78;           // the hub collapses to this circle before the iris opens
const IRIS_R = 1250;           // past the farthest corner (~1101 px from the hub)
const BREATH_T = 2;            // breathing period: one bar at 120 BPM
const endT = (q) => q.wipeSoft[1] - 0.07; // from here the frame is exactly S5's first picture
const LINE_COL = 'rgba(255,255,255,0.16)';
const ORBIT_A = 0.07;          // alpha of the faint orbit each wave leaves behind
const KNOCK = 9;               // gap between a face and the lines that pass it
const LAND_D = 0.72;           // a copy lands as a circle of this fraction of the face diameter
const AMBER = C.amber;
const iris = bezier(0.42, 0, 0.12, 1);
const morph = bezier(0.7, 0, 0.3, 1);

// ---------- network state ----------
const netRot = (t, q) => (ROT * Math.PI / 180) * inOutSine(prog(t, q.waves[0].t - 0.1, q.collapse[0]));
function breath(t, q) {
  const t0 = q.waves[0].t;
  const amp = 0.012 * prog(t, t0, t0 + 0.7) * (1 - prog(t, q.collapse[0] - 0.3, q.collapse[0]));
  return 1 + amp * Math.sin((2 * Math.PI * (t - t0)) / BREATH_T);
}

// Face slot on its elliptical orbit. (ux, uy) is the unit vector hub -> face and L its distance:
// spokes, flight arcs, landing squash and pulses all follow this real direction, not the parametric angle.
function slot(q, w, j, t) {
  const wv = q.waves[w];
  const a = (j / wv.count) * 2 * Math.PI + w * WAVE_OFF + netRot(t, q);
  const b = breath(t, q);
  const x = HUB.x + RINGS[w].rx * b * Math.sin(a);
  const y = HUB.y - RINGS[w].ry * b * Math.cos(a);
  const L = Math.hypot(x - HUB.x, y - HUB.y);
  return { a, L, ux: (x - HUB.x) / L, uy: (y - HUB.y) / L, d: RING_D[w], x, y };
}

// Anticipation squash before an event, release into a damped stretch after it.
function kick(t, te, A, pre = 0.14) {
  if (t < te - pre) return 0;
  if (t < te) return -A * inQuad(prog(t, te - pre, te));
  const x = t - te;
  return -A * Math.cos(2 * Math.PI * 3.2 * x) * Math.exp(-6 * x);
}

// The hub note folds into a circle just before the soft iris opens from it (sub-timing of collapse / wipeSoft).
const hubCollapse = (q) => [q.collapse[0] - 0.15, q.wipeSoft[0] - 0.07];

function hubState(t, q) {
  const s = lerp(1, HUB_S, prog(t, q.lineA + 0.06, q.waves[0].t - 0.08, glide)) * breath(t, q);
  let sq = 0;
  q.waves.forEach((wv, i) => { sq += kick(t, wv.t, 0.06 + 0.015 * i); });
  q.pulses.forEach((p) => { sq += kick(t, p, 0.035, 0.1); });
  const swell = 1 + 0.05 * inOutSine(prog(t, hubCollapse(q)[0] - 0.12, hubCollapse(q)[0]));
  return { w: HERO_NOTE_L.w * s * swell * (1 - 0.7 * sq), h: HERO_NOTE_L.h * s * swell * (1 + sq) };
}

// Where a ray from the hub centre along (ux, uy) leaves the hub's page (half sizes hw, hh).
function hubExit(ux, uy, hw, hh) {
  const ax = Math.abs(ux), ay = Math.abs(uy);
  return Math.min(ax > 1e-3 ? hw / ax : 1e9, ay > 1e-3 ? hh / ay : 1e9);
}

// Quadratic arc helpers.
const qb = (p0, p1, p2, s) => (1 - s) * (1 - s) * p0 + 2 * (1 - s) * s * p1 + s * s * p2;
const qd = (p0, p1, p2, s) => 2 * (1 - s) * (p1 - p0) + 2 * s * (p2 - p1);
const deg = (r) => (r * 180) / Math.PI;

// A four-point sparkle (concave star), half-size s.
function sparkle(x, y, s, rot, fill) {
  if (s <= 0.3) return '';
  const k = 0.16 * s;
  const d = `M0,${num(-s)}Q${num(k)},${num(-k)} ${num(s)},0Q${num(k)},${num(k)} 0,${num(s)}Q${num(-k)},${num(k)} ${num(-s)},0Q${num(-k)},${num(-k)} 0,${num(-s)}Z`;
  return `<path transform="translate(${num(x)} ${num(y)}) rotate(${num(rot)})" d="${d}" fill="${fill}"/>`;
}

// Per-glyph reveal with a colour per glyph and a quick exit. Also returns the line's mean glyph opacity,
// which drives the knockout plate behind it.
function charsRevealFills(str, cx, y, t, t0, { size, weight, fills, stagger, dur, rise, out }) {
  const chars = Array.from(str);
  const total = measure(str, size, weight, FONT_CN);
  const x0 = cx - total / 2;
  let s = '';
  let prefix = '';
  let vis = 0;
  for (let i = 0; i < chars.length; i++) {
    const x = x0 + measure(prefix, size, weight, FONT_CN);
    prefix += chars[i];
    const k = prog(t, t0 + i * stagger, t0 + i * stagger + dur, snap);
    let o = clamp(k * 1.6);
    let dy = (1 - k) * size * rise;
    const ko = prog(t, out.t0 + i * out.stagger, out.t0 + i * out.stagger + out.dur, inQuad);
    o *= 1 - ko;
    dy -= ko * size * out.rise;
    vis += o;
    if (o <= 0.001) continue;
    s += text(chars[i], x, y + dy, { size, weight, fill: fills(i), anchor: 'start', o, extra: GLYPH_HALO });
  }
  return { svg: s, vis: vis / chars.length, w: total };
}

// Ink plate behind a headline so spokes, orbits and pulses stop short of the glyphs.
function knockout(cx, y, w, size, o) {
  if (o <= 0.001) return '';
  const top = y - size * 0.9 - KNOCK_PAD.y, bot = y + size * 0.14 + KNOCK_PAD.y;
  return rr({ cx, cy: (top + bot) / 2, w: w + KNOCK_PAD.x * 2, h: bot - top, r: 24 }, C.ink, { opacity: o < 1 ? o : undefined });
}

function faceColor(w, j) {
  return FACE[CYCLE[(j + CYCLE_OFF[w]) % CYCLE.length]];
}

// Collapse order: faces farthest from the icon leave first.
const gatherCache = new WeakMap();
function gatherPlan(q) {
  if (gatherCache.has(q)) return gatherCache.get(q);
  const list = [];
  q.waves.forEach((wv, w) => {
    for (let j = 0; j < wv.count; j++) {
      if (ICON[`${w}:${j}`] !== undefined) continue;
      const S = slot(q, w, j, q.collapse[0]);
      list.push({ key: `${w}:${j}`, dist: Math.hypot(S.x - ICON_C.x, S.y - ICON_C.y) });
    }
  });
  list.sort((a, b) => b.dist - a.dist);
  const plan = {};
  list.forEach((it, i) => { plan[it.key] = i / (list.length - 1); });
  gatherCache.set(q, plan);
  return plan;
}

// Pulse hops for one face: the hop lift and squash at time t (continues into the collapse, blended out there).
function hopAt(t, q, exitR, rEnd) {
  let dy = 0, sx = 1, sy = 1, glint = 0;
  for (const p of q.pulses) {
    const tHit = p + (rEnd - exitR) / PULSE_V;
    const x = t - tHit;
    if (x < 0 || x >= 0.3) continue;
    if (x < 0.2) {
      const k = Math.sin((Math.PI * x) / 0.2);
      dy -= 16 * k;
      sy *= 1 + 0.07 * k; sx *= 1 - 0.05 * k;
    } else {
      const k = Math.sin((Math.PI * (x - 0.2)) / 0.1);
      sy *= 1 - 0.08 * k; sx *= 1 + 0.06 * k;
    }
    glint = Math.max(glint, outBack(clamp(x / 0.12), 2.4) * (1 - inCubic(prog(x, 0.14, 0.3))));
  }
  return { dy, sx, sy, glint };
}

export function draw(t, cues) {
  const q = cues.s4;
  // Last frames: exactly S5's opening picture (the soft field comes from background()).
  if (t >= endT(q)) return facesIcon(DATA_L.cols[0].x, DATA_L.iconY, 1, { happy: 1 });

  const [c0] = q.collapse;
  const [w0] = q.wipeSoft;
  const plan = gatherPlan(q);
  let lines = '', dots = '', rings = '', halos = '', pings = '', faces = '', glints = '', copies = '', late = '';
  const icon = ['', '', ''];

  const hs = hubState(t, q);
  const [hc0, hc1] = hubCollapse(q);
  const kc = prog(t, hc0, hc1, morph);
  const hubW = lerp(hs.w, CIRCLE_D, kc), hubH = lerp(hs.h, CIRCLE_D, kc);
  const hw = hubW / 2, hh = hubH / 2;

  // Ripple rings: each wave sends a thin ellipse out to its orbit; it stays as a faint orbit, then folds back in.
  const ringOut = prog(t, hc0, hc1 - 0.03, inCubic);
  q.waves.forEach((wv, w) => {
    const k = prog(t, wv.t, wv.t + 0.6, outCubic);
    if (k <= 0 || ringOut >= 1) return;
    const r0 = Math.max(hw, hh) * 0.9;
    const b = breath(t, q) * (1 - ringOut);
    const rx = lerp(r0, RINGS[w].rx * b, k), ry = lerp(r0, RINGS[w].ry * b, k);
    const a = lerp(0.24, ORBIT_A, k) * (1 - ringOut);
    rings += `<ellipse cx="${HUB.x}" cy="${HUB.y}" rx="${num(rx)}" ry="${num(ry)}" fill="none" stroke="rgba(255,255,255,${num(a)})" stroke-width="2"/>`;
  });

  q.waves.forEach((wv, w) => {
    for (let j = 0; j < wv.count; j++) {
      const dep = wv.t + j * q.copyStagger;
      if (t < dep) continue;
      const arr = dep + q.flight;
      const hap = arr + q.happyDelay;
      const key = `${w}:${j}`;
      const iconIdx = ICON[key];
      const R = rng(1000 + w * 97 + j * 13);
      const phase = R();
      const S = slot(q, w, j, t);
      const d = S.d;
      const color = faceColor(w, j);
      const tilt = (j % 2 ? 1 : -1) * (7 + R() * 6);
      const glintA = (-30 - R() * 40) * (Math.PI / 180);
      const wMini = d * 0.52, hMini = d * 0.68;

      // --- connection line: grows with the copy, retracts into the hub at the collapse ---
      const exitR = hubExit(S.ux, S.uy, hw, hh);
      let lineR;
      if (t < arr) {
        const u = (t - dep) / q.flight;
        lineR = lerp(0, S.L - d * 0.3, outCubic(clamp(u * 1.05)));
      } else lineR = S.L - d * 0.3;
      lineR *= 1 - prog(t, hc0 + 0.06 * (1 - S.L / 1000), hc1 - 0.02, inCubic);
      if (lineR > exitR - 4) {
        const x1 = HUB.x + S.ux * (exitR - 6), y1 = HUB.y + S.uy * (exitR - 6);
        const x2 = HUB.x + S.ux * lineR, y2 = HUB.y + S.uy * lineR;
        lines += `<line x1="${num(x1)}" y1="${num(y1)}" x2="${num(x2)}" y2="${num(y2)}" stroke="${LINE_COL}" stroke-width="3" stroke-linecap="round"/>`;
      }

      // --- the copy in flight: hub-sized page -> mini page -> circle in the face colour (rr family) ---
      if (t < arr) {
        const u = (t - dep) / q.flight;
        const h0 = hubState(dep, q);
        const e = outBack(clamp(u / 0.72), 1.2);
        const L = S.L;
        const px = (HUB.x + S.x) / 2 - BEND * L * S.uy;
        const py = (HUB.y + S.y) / 2 + BEND * L * S.ux;
        const x = qb(HUB.x, px, S.x, e), y = qb(HUB.y, py, S.y, e);
        const vx = qd(HUB.x, px, S.x, clamp(e)), vy = qd(HUB.y, py, S.y, clamp(e));
        const ang = deg(Math.atan2(vy, vx));
        const ks = outCubic(clamp(u / 0.5));
        const km = morph(prog(u, 0.62, 1));
        const cw = lerp(lerp(h0.w, wMini, ks), d * LAND_D, km), ch = lerp(lerp(h0.h, hMini, ks), d * LAND_D, km);
        const cr = lerp(cw * 0.09, (d * LAND_D) / 2, km);
        const rot = tilt * ks * (1 - km) + 26 * Math.sin(Math.PI * u);
        const str = 0.13 * Math.sin(Math.PI * clamp(u / 0.6));
        const note = noteBody(0, 0, cw, ch, cr, mixColor(C.paper, color, km), 1 - prog(km, 0, 0.6), rot);
        copies += `<g transform="translate(${num(x)} ${num(y)}) rotate(${num(ang)}) scale(${num(1 + str)} ${num(1 - str)}) rotate(${num(-ang)})">${note}</g>`;
        continue;
      }

      // --- arrived: the circle springs to full size and opens its eyes; they turn happy; a glint flashes ---
      const kf = lerp(LAND_D, 1, spring(t - arr, 2.4, 0.45));
      const eyes = lerp(0.06, 1, prog(t, arr, arr + 0.08, outCubic));
      const xl = t - arr;
      const land = Math.sin(Math.min(1, xl / 0.26) * Math.PI) * Math.exp(-6 * xl);
      const happy = prog(t, hap, hap + 0.1);
      const bob = 2.5 * Math.sin(2 * Math.PI * (t * 0.9 + phase)) * prog(t, arr + 0.3, arr + 0.8) * (1 - prog(t, c0 - 0.2, c0));
      // Pulse hops: a dot runs out along the spoke; the face hops when it lands.
      const r0 = exitR - 6;
      const rEnd = S.L - d / 2;
      for (const p of q.pulses) {
        const tHit = p + (rEnd - r0) / PULSE_V;
        if (t >= p && t < tHit) {
          const rd = r0 + (t - p) * PULSE_V;
          const len = Math.min(PULSE_LEN, rd - r0 + 9);
          const mid = rd - len / 2 + 4.5;
          const dx = HUB.x + S.ux * mid, dy = HUB.y + S.uy * mid;
          dots += g(rr({ cx: dx, cy: dy, w: 9, h: len, r: 4.5 }, AMBER), { rot: deg(Math.atan2(S.ux, -S.uy)), ox: dx, oy: dy });
        }
      }
      const hop = hopAt(t, q, r0, rEnd);
      const fx0 = S.x, fy0 = S.y + bob + hop.dy;

      // Glint: flashes when the eyes turn happy, and again on each pulse hop.
      if (t < hc0 + 0.12) {
        const g1 = prog(t, hap, hap + 0.6);
        let sc = 0;
        if (g1 > 0 && g1 < 1) sc = outBack(prog(t, hap, hap + 0.2), 2.4) * (1 - inCubic(prog(t, hap + 0.28, hap + 0.6)));
        sc = Math.max(sc, hop.glint) * (1 - prog(t, hc0, hc0 + 0.12, inQuad));
        if (sc > 0.01) {
          const gx = fx0 + Math.cos(glintA) * d * 0.66, gy = fy0 + Math.sin(glintA) * d * 0.66;
          glints += sparkle(gx, gy, d * 0.17 * sc, 90 * g1 + 45 * hop.glint, AMBER);
        }
      }
      // "Lights up": a thin amber ring pings out from the face as the eyes turn happy.
      const kp = prog(t, hap, hap + 0.4, outCubic);
      if (kp > 0 && kp < 1) {
        pings += `<circle cx="${num(fx0)}" cy="${num(fy0)}" r="${num(d / 2 + 4 + 26 * kp)}" fill="none" stroke="${AMBER}" stroke-opacity="${num(0.85 * (1 - kp))}" stroke-width="${num(lerp(4, 1.5, kp))}"/>`;
      }
      // Knockout disc in the background colour, so spokes and orbits stop short of the face.
      const halo = lerp(KNOCK, 0, prog(t, hc1 - 0.08, hc1));
      if (halo > 0.5 && t < c0 + 0.05) halos += `<circle cx="${num(fx0)}" cy="${num(fy0)}" r="${num((d * kf) / 2 + halo)}" fill="${C.ink}"/>`;

      const radialDeg = deg(Math.atan2(S.uy, S.ux));
      if (iconIdx !== undefined) {
        // Becomes part of S5's users icon: an arc to its slot, growing or shrinking to the icon size.
        const f = FACES_ICON[iconIdx];
        const P = slot(q, w, j, c0);
        const tx = ICON_C.x + f.dx, ty = ICON_C.y + f.dy;
        const u = prog(t, c0 + 0.02, c0 + 0.37);
        const e = outBack(u, 1.3);
        const L = Math.hypot(tx - P.x, ty - P.y);
        const nx = -(ty - P.y) / (L || 1), ny = (tx - P.x) / (L || 1);
        const cx2 = (P.x + tx) / 2 + nx * L * 0.25, cy2 = (P.y + ty) / 2 + ny * L * 0.25;
        let fx = fx0, fy = fy0;
        if (u > 0) {
          fx = qb(P.x, cx2, tx, e); fy = qb(P.y, cy2, ty, e) + hop.dy * (1 - u);
        }
        const dd = lerp(d, f.d, e);
        let faceSvg = landed(student({ cx: fx, cy: fy, d: dd * kf, color, happy, blink: eyes }), fx, fy, radialDeg, land);
        const st = 0.1 * Math.sin(Math.PI * u);
        faceSvg = g(faceSvg, { sx: lerp(hop.sx, 1, u) * (1 + st), sy: lerp(hop.sy, 1, u) * (1 - st), ox: fx, oy: fy + dd / 2 });
        if (t >= c0) icon[iconIdx] = faceSvg; else faces += faceSvg;
        continue;
      }

      if (t < c0) {
        faces += g(landed(student({ cx: fx0, cy: fy0, d: d * kf, color, happy, blink: eyes }), fx0, fy0, radialDeg, land), { sx: hop.sx, sy: hop.sy, ox: fx0, oy: fy0 + d / 2 });
        continue;
      }
      // Gather: a sweep from the far side toward the icon; each face drifts in on a shared vortex arc and shrinks away.
      // A hop still in the air at the collapse is carried in and blended out, so nothing jumps.
      const rank = plan[key];
      const gs = c0 + 0.17 * rank;
      const u = prog(t, gs, gs + 0.26);
      if (u >= 1) continue;
      const e = inBack(u, 1.2);
      const P = slot(q, w, j, c0);
      const dist = Math.hypot(ICON_C.x - P.x, ICON_C.y - P.y);
      const f = clamp(0.3 + 170 / dist);
      const Tx = lerp(P.x, ICON_C.x, f), Ty = lerp(P.y, ICON_C.y, f);
      const L = dist * f;
      const nx = -(Ty - P.y) / L, ny = (Tx - P.x) / L;
      const cx2 = (P.x + Tx) / 2 + nx * L * 0.22, cy2 = (P.y + Ty) / 2 + ny * L * 0.22;
      const x = qb(P.x, cx2, Tx, e), y = qb(P.y, cy2, Ty, e) + hop.dy * (1 - u);
      const vx = qd(P.x, cx2, Tx, clamp(e)), vy = qd(P.y, cy2, Ty, clamp(e));
      const ang = deg(Math.atan2(vy, vx));
      const dd = d * (1 + 0.1 * Math.sin(Math.PI * clamp(u / 0.35))) * (1 - inQuad(prog(u, 0.15, 1)));
      const str = 0.14 * Math.sin(Math.PI * prog(u, 0.3, 1));
      if (dd > 0.5) {
        const hsx = lerp(hop.sx, 1, u), hsy = lerp(hop.sy, 1, u);
        late += `<g transform="translate(${num(x)} ${num(y)}) rotate(${num(ang)}) scale(${num(1 + str)} ${num(1 - str)}) rotate(${num(-ang)}) scale(${num(hsx)} ${num(hsy)})">${student({ cx: 0, cy: 0, d: dd, color, happy })}</g>`;
      }
    }
  });

  // --- the hub: note -> circle (collapse) -> squash -> soft iris (M10) ---
  let hub = '';
  let irisSvg = '';
  if (kc <= 0) {
    hub = heroNoteL({ w: hs.w, h: hs.h });
  } else if (t < hc1) {
    const r = lerp(hs.w * 0.09, CIRCLE_D / 2, kc);
    const fill = mixColor(C.paper, C.bg, kc);
    hub = noteBody(HUB.x, HUB.y, hubW, hubH, r, fill, 1 - prog(kc, 0, 0.55), 10 * Math.sin(Math.PI * kc));
  } else if (t < w0) {
    // Anticipation: the circle squashes before it bursts (echo of S2's blue dot).
    const k = prog(t, hc1, w0, inQuad);
    hub = `<ellipse cx="${HUB.x}" cy="${HUB.y}" rx="${num((CIRCLE_D / 2) * (1 + 0.1 * k))}" ry="${num((CIRCLE_D / 2) * (1 - 0.1 * k))}" fill="${C.bg}"/>`;
  } else {
    const ki = prog(t, w0, q.wipeSoft[1], iris);
    const rad = lerp(CIRCLE_D / 2, IRIS_R, ki);
    const sq = 0.1 * (1 - prog(t, w0, w0 + 0.12, outCubic));
    irisSvg = `<ellipse cx="${HUB.x}" cy="${HUB.y}" rx="${num(rad * (1 + sq))}" ry="${num(rad * (1 - sq))}" fill="${C.bg}"/>`;
  }

  // --- text: top band and bottom band, centred on the hub ---
  const textOut = { t0: q.textOut, stagger: 0.012, dur: 0.22, rise: 0.5 };
  const A = charsRevealFills(q.lineAText, HUB.x, LINE_A_Y, t, q.lineA, {
    size: TXT, weight: 900, fills: () => '#ffffff', stagger: 0.045, dur: 0.45, rise: 0.5, out: textOut,
  });
  const amberIdx = new Set([2, 3, 4]); // 更多人
  const B = charsRevealFills(q.lineBText, HUB.x, LINE_B_Y, t, q.lineB, {
    size: TXT, weight: 900, fills: (i) => (amberIdx.has(i) ? AMBER : '#ffffff'), stagger: 0.045, dur: 0.45, rise: 0.5, out: textOut,
  });
  const plates = knockout(HUB.x, LINE_A_Y, A.w, TXT, A.vis) + knockout(HUB.x, LINE_B_Y, B.w, TXT, B.vis);

  // Copies slide out from behind the hub, so the hub stays clean while a wave leaves.
  return rings + lines + dots + plates + halos + pings + faces + glints + copies + hub + A.svg + B.svg + irisSvg + late + icon.join('');
}

// Landing squash along the arrival direction (screen angle of the outward radial, degrees).
function landed(svg, x, y, angDeg, land) {
  if (Math.abs(land) < 0.002) return svg;
  const k = 0.12 * land;
  return `<g transform="translate(${num(x)} ${num(y)}) rotate(${num(angDeg)}) scale(${num(1 - k)} ${num(1 + k * 0.8)}) rotate(${num(-angDeg)}) translate(${num(-x)} ${num(-y)})">${svg}</g>`;
}

// The note drawn like noteCard() but with an explicit radius, fill and inner-content fade (for the collapse morph).
function noteBody(cx, cy, w, h, r, fill, inner, tilt) {
  if (w <= 1) return '';
  let s = rr({ cx, cy, w, h, r }, fill);
  if (inner > 0.01) {
    const pad = w * 0.16;
    const left = cx - w / 2 + pad;
    const hw = (w - pad * 2) * 0.55 * inner;
    const lh = Math.max(4, w * 0.075);
    s += rr({ cx: left + hw / 2, cy: cy - h / 2 + pad + lh / 2, w: hw, h: lh, r: lh / 2 }, AMBER);
    const gap = (h - pad * 2 - lh) / 4.5;
    for (let i = 0; i < 4; i++) {
      const k = clamp(inner * 4 - i);
      const lw = (w - pad * 2) * (i === 3 ? 0.6 : i % 2 ? 0.86 : 1) * k;
      const ly = cy - h / 2 + pad + lh + gap * (i + 1);
      const thick = Math.max(3, w * 0.05);
      if (lw > 0.5) s += rr({ cx: left + lw / 2, cy: ly, w: lw, h: thick, r: thick / 2 }, '#d6deea');
    }
  }
  return tilt ? g(s, { rot: tilt, ox: cx, oy: cy }) : s;
}

export function background(t, cues) {
  return t >= endT(cues.s4) ? C.bg : C.ink;
}
