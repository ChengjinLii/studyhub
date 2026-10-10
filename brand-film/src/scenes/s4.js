// S4 share (15-20 s), the hero moment: one note is copied out in three waves to rings of classmates.
// Each one who receives a copy lights up. Then the network folds into S5's "users" icon and a soft iris opens.
import { C, FONT_CN, rr, g, text, measure, prog, clamp, lerp, mixColor, spring, snap, glide, outCubic, inCubic, inQuad, inOutSine, outBack, inBack, bezier, rng, num } from '../core.js';
import { student, FACE, heroNote, HERO_NOTE, DATA, FACES_ICON, facesIcon } from '../shared.js';

export const range = [15.0, 20.0];

const HUB = { x: HERO_NOTE.cx, y: HERO_NOTE.cy };
const HUB_S = 0.68;            // the hub settles to this scale so ring 1 has air around it
const RING_D = [96, 84, 74];   // face diameters, rings 1-3
const WAVE_OFF = 0.4;          // angle offset per wave (rad); compose.py pans each copy by the same angle
const ROT = 6;                 // total clockwise drift of the network, degrees
const CYCLE = ['blue', 'teal', 'amber', 'violet', 'sky'];
const CYCLE_OFF = [2, 0, 1];   // chosen so the three faces that become S5's icon already are teal / amber / blue
// Faces that become the S5 "users" icon: `${wave}:${j}` -> index into FACES_ICON.
const ICON = { '1:6': 0, '1:7': 1, '2:9': 2 };
const ICON_C = { x: DATA.iconX, y: DATA.rows[0].y };
const LINE_A_Y = 300;
const LINE_B_Y = 1645;         // ring 3's lowest faces end near y 1545; the line sits below them
const BEND = 0.32;             // copy flight arcs bulge clockwise by this fraction of their length
const PULSE_V = 1700;          // pulse dot speed, px/s
const CIRCLE_D = 96;           // the hub collapses to this circle before the iris opens
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
// Slow drift and breathing from the first wave until the collapse, when the network holds still.
const netRot = (t, q) => (ROT * Math.PI / 180) * inOutSine(prog(t, q.waves[0].t - 0.1, q.collapse[0]));
function breath(t, q) {
  const t0 = q.waves[0].t;
  const amp = 0.012 * prog(t, t0, t0 + 0.7) * (1 - prog(t, q.collapse[0] - 0.3, q.collapse[0]));
  return 1 + amp * Math.sin((2 * Math.PI * (t - t0)) / BREATH_T);
}

function slot(q, w, j, t) {
  const wv = q.waves[w];
  const a = (j / wv.count) * 2 * Math.PI + w * WAVE_OFF + netRot(t, q);
  const R = wv.radius * breath(t, q);
  const d = RING_D[w];
  const sx = Math.sin(a), cy = -Math.cos(a);
  return { a, R, d, x: HUB.x + R * sx, y: HUB.y + R * cy };
}

// Anticipation squash before an event, release into a damped stretch after it.
function kick(t, te, A, pre = 0.14) {
  if (t < te - pre) return 0;
  if (t < te) return -A * inQuad(prog(t, te - pre, te));
  const x = t - te;
  return -A * Math.cos(2 * Math.PI * 3.2 * x) * Math.exp(-6 * x);
}

function hubState(t, q) {
  // After lineA lands the hub settles smaller, ready for the first wave.
  const s = lerp(1, HUB_S, prog(t, q.lineA + 0.06, q.waves[0].t - 0.08, glide)) * breath(t, q);
  let sq = 0;
  q.waves.forEach((wv, i) => { sq += kick(t, wv.t, 0.06 + 0.015 * i); });
  q.pulses.forEach((p) => { sq += kick(t, p, 0.035, 0.1); });
  // A small swell (anticipation) just before the hub collapses.
  const swell = 1 + 0.05 * inOutSine(prog(t, hubCollapse(q)[0] - 0.12, hubCollapse(q)[0]));
  return { w: HERO_NOTE.w * s * swell * (1 - 0.7 * sq), h: HERO_NOTE.h * s * swell * (1 + sq) };
}

// The hub note folds into a circle just before the soft iris opens from it (sub-timing of collapse / wipeSoft).
const hubCollapse = (q) => [q.collapse[0] - 0.15, q.wipeSoft[0] - 0.07];

// Where a ray from the hub centre leaves the hub's page (half sizes hw, hh).
function hubExit(a, hw, hh) {
  const sx = Math.abs(Math.sin(a)), cy = Math.abs(Math.cos(a));
  return Math.min(sx > 1e-3 ? hw / sx : 1e9, cy > 1e-3 ? hh / cy : 1e9);
}

// Quadratic arc helpers.
const qb = (p0, p1, p2, s) => (1 - s) * (1 - s) * p0 + 2 * (1 - s) * s * p1 + s * s * p2;
const qd = (p0, p1, p2, s) => 2 * (1 - s) * (p1 - p0) + 2 * s * (p2 - p1);

// A four-point sparkle (concave star), half-size s.
function sparkle(x, y, s, rot, fill) {
  if (s <= 0.3) return '';
  const k = 0.16 * s;
  const d = `M0,${num(-s)}Q${num(k)},${num(-k)} ${num(s)},0Q${num(k)},${num(k)} 0,${num(s)}Q${num(-k)},${num(k)} ${num(-s)},0Q${num(-k)},${num(-k)} 0,${num(-s)}Z`;
  return `<path transform="translate(${num(x)} ${num(y)}) rotate(${num(rot)})" d="${d}" fill="${fill}"/>`;
}

// Per-glyph reveal with a colour per glyph (core charsReveal takes one fill), and a quicker exit
// so the lines are gone before the soft iris reaches them.
function charsRevealFills(str, cx, y, t, t0, { size, weight, fills, stagger, dur, rise, out }) {
  const chars = Array.from(str);
  const total = measure(str, size, weight, FONT_CN);
  const x0 = cx - total / 2;
  let s = '';
  let prefix = '';
  for (let i = 0; i < chars.length; i++) {
    const x = x0 + measure(prefix, size, weight, FONT_CN);
    prefix += chars[i];
    const k = prog(t, t0 + i * stagger, t0 + i * stagger + dur, snap);
    let o = clamp(k * 1.6);
    let dy = (1 - k) * size * rise;
    const ko = prog(t, out.t0 + i * out.stagger, out.t0 + i * out.stagger + out.dur, inQuad);
    o *= 1 - ko;
    dy -= ko * size * out.rise;
    if (o <= 0.001) continue;
    s += text(chars[i], x, y + dy, { size, weight, fill: fills(i), anchor: 'start', o });
  }
  return s;
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

export function draw(t, cues) {
  const q = cues.s4;
  // Last frames: exactly S5's opening picture (the soft field comes from background()).
  if (t >= endT(q)) return facesIcon(DATA.iconX, DATA.rows[0].y, 1, { happy: 1 });

  const [c0] = q.collapse;
  const [w0] = q.wipeSoft;
  const plan = gatherPlan(q);
  let lines = '', dots = '', rings = '', halos = '', pings = '', faces = '', glints = '', copies = '', late = '', icon = ['', '', ''];

  const hs = hubState(t, q);
  const [hc0, hc1] = hubCollapse(q);
  const kc = prog(t, hc0, hc1, morph);
  const hubW = lerp(hs.w, CIRCLE_D, kc), hubH = lerp(hs.h, CIRCLE_D, kc);
  const hw = hubW / 2, hh = hubH / 2;

  // Ripple rings: each wave sends a thin ring out to its radius; it stays as a faint orbit, then folds back in.
  const ringOut = prog(t, hc0, hc1 - 0.03, inCubic);
  q.waves.forEach((wv) => {
    const k = prog(t, wv.t, wv.t + 0.6, outCubic);
    if (k <= 0 || ringOut >= 1) return;
    const r = lerp(Math.max(hw, hh) * 0.9, wv.radius * breath(t, q), k) * (1 - ringOut);
    const a = lerp(0.24, ORBIT_A, k) * (1 - ringOut);
    rings += `<circle cx="${HUB.x}" cy="${HUB.y}" r="${num(r)}" fill="none" stroke="rgba(255,255,255,${num(a)})" stroke-width="2"/>`;
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
      const exitR = hubExit(S.a, hw, hh);
      let lineR;
      if (t < arr) {
        const u = (t - dep) / q.flight;
        lineR = lerp(0, S.R - d * 0.3, outCubic(clamp(u * 1.05)));
      } else lineR = S.R - d * 0.3;
      lineR *= 1 - prog(t, hc0 + 0.06 * (1 - S.R / 560), hc1 - 0.02, inCubic);
      if (lineR > exitR - 4) {
        const x1 = HUB.x + Math.sin(S.a) * (exitR - 6), y1 = HUB.y - Math.cos(S.a) * (exitR - 6);
        const x2 = HUB.x + Math.sin(S.a) * lineR, y2 = HUB.y - Math.cos(S.a) * lineR;
        lines += `<line x1="${num(x1)}" y1="${num(y1)}" x2="${num(x2)}" y2="${num(y2)}" stroke="${LINE_COL}" stroke-width="3" stroke-linecap="round"/>`;
      }

      // --- the copy in flight: hub-sized page -> mini page -> circle in the face colour (rr family) ---
      if (t < arr) {
        const u = (t - dep) / q.flight;
        const h0 = hubState(dep, q);
        const e = outBack(clamp(u / 0.72), 1.2);
        const L = S.R;
        const px = (HUB.x + S.x) / 2 + BEND * L * Math.cos(S.a);
        const py = (HUB.y + S.y) / 2 + BEND * L * Math.sin(S.a);
        const x = qb(HUB.x, px, S.x, e), y = qb(HUB.y, py, S.y, e);
        const vx = qd(HUB.x, px, S.x, clamp(e)), vy = qd(HUB.y, py, S.y, clamp(e));
        const ang = (Math.atan2(vy, vx) * 180) / Math.PI;
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
      let fx = S.x, fy = S.y, fsx = 1, fsy = 1;
      const bob = 2.5 * Math.sin(2 * Math.PI * (t * 0.9 + phase)) * prog(t, arr + 0.3, arr + 0.8) * (1 - prog(t, c0 - 0.2, c0));
      fy += bob;
      // Pulse hops: a dot runs out along the spoke; the face hops when it lands.
      let hopGlint = 0;
      for (const p of q.pulses) {
        const r0 = exitR - 6;
        const rEnd = S.R - d / 2;
        const tHit = p + (rEnd - r0) / PULSE_V;
        if (t >= p && t < tHit) {
          const rd = r0 + (t - p) * PULSE_V;
          const len = Math.min(38, rd - r0 + 9);
          const mid = rd - len / 2 + 4.5;
          const dx = HUB.x + Math.sin(S.a) * mid, dy = HUB.y - Math.cos(S.a) * mid;
          dots += g(rr({ cx: dx, cy: dy, w: 9, h: len, r: 4.5 }, AMBER), { rot: (S.a * 180) / Math.PI, ox: dx, oy: dy });
        }
        const x = t - tHit;
        if (x >= 0 && x < 0.3) {
          if (x < 0.2) {
            const k = Math.sin((Math.PI * x) / 0.2);
            fy -= 16 * k;
            fsy *= 1 + 0.07 * k; fsx *= 1 - 0.05 * k;
          } else {
            const k = Math.sin((Math.PI * (x - 0.2)) / 0.1);
            fsy *= 1 - 0.08 * k; fsx *= 1 + 0.06 * k;
          }
          hopGlint = Math.max(hopGlint, outBack(clamp(x / 0.12), 2.4) * (1 - inCubic(prog(x, 0.14, 0.3))));
        }
      }

      // Glint: flashes when the eyes turn happy, and again on each pulse hop.
      if (t < hc0 + 0.12) {
        const g1 = prog(t, hap, hap + 0.6);
        let sc = 0;
        if (g1 > 0 && g1 < 1) sc = outBack(prog(t, hap, hap + 0.2), 2.4) * (1 - inCubic(prog(t, hap + 0.28, hap + 0.6)));
        sc = Math.max(sc, hopGlint) * (1 - prog(t, hc0, hc0 + 0.12, inQuad));
        if (sc > 0.01) {
          const gx = fx + Math.cos(glintA) * d * 0.66, gy = fy + Math.sin(glintA) * d * 0.66;
          glints += sparkle(gx, gy, d * 0.17 * sc, 90 * g1 + 45 * hopGlint, AMBER);
        }
      }
      // "Lights up": a thin amber ring pings out from the face as the eyes turn happy.
      const kp = prog(t, hap, hap + 0.4, outCubic);
      if (kp > 0 && kp < 1) {
        pings += `<circle cx="${num(fx)}" cy="${num(fy)}" r="${num(d / 2 + 4 + 26 * kp)}" fill="none" stroke="${AMBER}" stroke-opacity="${num(0.85 * (1 - kp))}" stroke-width="${num(lerp(4, 1.5, kp))}"/>`;
      }
      // Knockout disc in the background colour, so spokes and orbits stop short of the face.
      const halo = lerp(KNOCK, 0, prog(t, hc1 - 0.08, hc1));
      if (halo > 0.5) halos += `<circle cx="${num(fx)}" cy="${num(fy)}" r="${num((d * kf) / 2 + halo)}" fill="${C.ink}"/>`;

      let faceSvg;
      if (iconIdx !== undefined) {
        // Becomes part of S5's users icon.
        const f = FACES_ICON[iconIdx];
        const P = slot(q, w, j, c0);
        const tx = ICON_C.x + f.dx, ty = ICON_C.y + f.dy;
        const u = prog(t, c0 + 0.02, c0 + 0.37);
        const e = outBack(u, 1.3);
        const L = Math.hypot(tx - P.x, ty - P.y);
        const nx = -(ty - P.y) / (L || 1), ny = (tx - P.x) / (L || 1);
        const cx2 = (P.x + tx) / 2 + nx * L * 0.25, cy2 = (P.y + ty) / 2 + ny * L * 0.25;
        if (u > 0) {
          fx = qb(P.x, cx2, tx, e); fy = qb(P.y, cy2, ty, e);
        }
        const dd = lerp(d, f.d, e);
        faceSvg = landed(student({ cx: fx, cy: fy, d: dd * kf, color, happy, blink: eyes }), fx, fy, S.a, land);
        const st = 0.1 * Math.sin(Math.PI * u);
        faceSvg = g(faceSvg, { sx: (fsx) * (1 + st), sy: fsy * (1 - st), ox: fx, oy: fy + dd / 2 });
        if (t >= c0) icon[iconIdx] = faceSvg; else faces += faceSvg;
        continue;
      }

      if (t < c0) {
        faces += g(landed(student({ cx: fx, cy: fy, d: d * kf, color, happy, blink: eyes }), fx, fy, S.a, land), { sx: fsx, sy: fsy, ox: fx, oy: fy + d / 2 });
        continue;
      }
      // Gather: a sweep from the far side toward the icon; each face drifts in on a shared vortex arc and shrinks away.
      const rank = plan[key];
      const g0 = c0 + 0.17 * rank;
      const u = prog(t, g0, g0 + 0.26);
      if (u >= 1) continue;
      const e = inBack(u, 1.2);
      const P = slot(q, w, j, c0);
      const dist = Math.hypot(ICON_C.x - P.x, ICON_C.y - P.y);
      const f = clamp(0.3 + 170 / dist);
      const Tx = lerp(P.x, ICON_C.x, f), Ty = lerp(P.y, ICON_C.y, f);
      const L = dist * f;
      const nx = -(Ty - P.y) / L, ny = (Tx - P.x) / L;
      const cx2 = (P.x + Tx) / 2 + nx * L * 0.22, cy2 = (P.y + Ty) / 2 + ny * L * 0.22;
      const x = qb(P.x, cx2, Tx, e), y = qb(P.y, cy2, Ty, e);
      const vx = qd(P.x, cx2, Tx, clamp(e)), vy = qd(P.y, cy2, Ty, clamp(e));
      const ang = (Math.atan2(vy, vx) * 180) / Math.PI;
      const dd = d * (1 + 0.1 * Math.sin(Math.PI * clamp(u / 0.35))) * (1 - inQuad(prog(u, 0.15, 1)));
      const str = 0.14 * Math.sin(Math.PI * prog(u, 0.3, 1));
      if (dd > 0.5) {
        late += `<g transform="translate(${num(x)} ${num(y)}) rotate(${num(ang)}) scale(${num(1 + str)} ${num(1 - str)}) rotate(${num(-ang)})">${student({ cx: 0, cy: 0, d: dd, color, happy })}</g>`;
      }
    }
  });

  // --- the hub: note -> circle (collapse) -> squash -> soft iris (M10) ---
  let hub = '';
  let irisSvg = '';
  if (kc <= 0) {
    hub = heroNote({ w: hs.w, h: hs.h });
  } else if (t < hc1) {
    const r = lerp(hs.w * 0.09, CIRCLE_D / 2, kc);
    const fill = mixColor(C.paper, C.bg, kc);
    hub = noteBody(HUB.x, HUB.y, hubW, hubH, r, fill, 1 - prog(kc, 0, 0.55), 10 * Math.sin(Math.PI * kc));
  } else if (t < w0) {
    // Anticipation: the circle squashes before it bursts (echo of S2's blue dot).
    const k = prog(t, hc1, w0, inQuad);
    hub = `<ellipse cx="${HUB.x}" cy="${HUB.y}" rx="${num((CIRCLE_D / 2) * (1 + 0.1 * k))}" ry="${num((CIRCLE_D / 2) * (1 - 0.1 * k))}" fill="${C.bg}"/>`;
  } else {
    // Release, then the iris grows past the farthest corner (~1101 px from the hub).
    const ki = prog(t, w0, q.wipeSoft[1], iris);
    const rad = lerp(CIRCLE_D / 2, 1250, ki);
    const sq = 0.1 * (1 - prog(t, w0, w0 + 0.12, outCubic));
    irisSvg = `<ellipse cx="${HUB.x}" cy="${HUB.y}" rx="${num(rad * (1 + sq))}" ry="${num(rad * (1 - sq))}" fill="${C.bg}"/>`;
  }

  // --- text ---
  let txt = '';
  const textOut = { t0: q.textOut, stagger: 0.012, dur: 0.22, rise: 0.5 };
  txt += charsRevealFills(q.lineAText, 540, LINE_A_Y, t, q.lineA, {
    size: 88, weight: 900, fills: () => '#ffffff', stagger: 0.045, dur: 0.45, rise: 0.5, out: textOut,
  });
  const amberIdx = new Set([2, 3, 4]); // 更多人
  txt += charsRevealFills(q.lineBText, 540, LINE_B_Y, t, q.lineB, {
    size: 88, weight: 900, fills: (i) => (amberIdx.has(i) ? AMBER : '#ffffff'), stagger: 0.045, dur: 0.45, rise: 0.5, out: textOut,
  });

  // Copies slide out from behind the hub, so the hub stays clean while a wave leaves.
  return rings + lines + dots + halos + pings + faces + glints + copies + hub + txt + irisSvg + late + icon.join('');
}

// Landing squash along the arrival direction (radial, angle a).
function landed(svg, x, y, a, land) {
  if (Math.abs(land) < 0.002) return svg;
  const ang = (a * 180) / Math.PI - 90; // screen angle of the outward radial
  const k = 0.12 * land;
  return `<g transform="translate(${num(x)} ${num(y)}) rotate(${num(ang)}) scale(${num(1 - k)} ${num(1 + k * 0.8)}) rotate(${num(-ang)}) translate(${num(-x)} ${num(-y)})">${svg}</g>`;
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
