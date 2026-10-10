// Shared drawing pieces used by more than one scene, so hand-offs between scenes match exactly.
import { C, FONT_CN, FONT_EN, rr, g, text, measure, botFace, noteCard, clamp, lerp, num } from './core.js';

// Student avatar colours: brand blue, teal, amber, violet, sky (tint of brand blue).
export const FACE = { blue: C.blue, teal: C.teal, amber: C.amber, violet: C.violet, sky: '#60a5fa', ink: C.ink };

// A student: a coloured circle with the bot's capsule eyes.
export function student({ cx, cy, d, color, look = 0, lookY = 0, blink = 1, happy = 0, o = 1 }) {
  return g(botFace({ cx, cy, d, shape: 0, body: color, look, lookY, blink, happy, eyeScale: 0.92 }), { o });
}

// ---------- "StudyHub · 学汇" lockup ----------
const LOCK = { en: 'StudyHub', sep: ' · ', cn: '学汇' };
export function lockupMetrics(size) {
  const en = measure(LOCK.en, size, 800, FONT_EN);
  const sep = measure(LOCK.sep, size * 0.82, 700, FONT_CN);
  const cn = measure(LOCK.cn, size * 0.82, 700, FONT_CN);
  return { en, sep, cn, w: en + sep + cn };
}

// Draw the lockup centred on cx with baseline y. reveal(i) -> {o, dy} per glyph index for entrance.
export function lockup(cx, y, size, { fill = '#ffffff', cnFill = null, reveal = null } = {}) {
  const m = lockupMetrics(size);
  let x = cx - m.w / 2;
  let s = '';
  let i = 0;
  const put = (str, fam, sz, wt, col) => {
    let pre = '';
    for (const ch of Array.from(str)) {
      const cxp = x + measure(pre, sz, wt, fam);
      pre += ch;
      if (ch === ' ') { i++; continue; }
      const r = reveal ? reveal(i) : { o: 1, dy: 0 };
      i++;
      if (r.o <= 0.001) continue;
      s += text(ch, cxp, y + r.dy, { size: sz, weight: wt, fill: col, family: fam, anchor: 'start', o: r.o });
    }
    x += measure(str, sz, wt, fam);
  };
  put(LOCK.en, FONT_EN, size, 800, fill);
  put(LOCK.sep, FONT_CN, size * 0.82, 700, cnFill ?? fill);
  put(LOCK.cn, FONT_CN, size * 0.82, 700, cnFill ?? fill);
  return s;
}

// ---------- Material card (flat version of MaterialCard.tsx) ----------
// Courses are examples; tags are real presets from frontend/constants/uploadOptions.ts.
// price: paid items show the real '¥x.xx' format in brand blue; the rest show '免费' in green (MaterialCard.tsx).
export const COURSES = [
  { name: '高等数学', tag: '#期末真题', color: C.blue },
  { name: '线性代数', tag: '#日常学习笔记', color: C.teal },
  { name: '概率论', tag: '#期末真题', color: C.amber },
  { name: '大学物理', tag: '#期末速成', color: C.violet, price: '¥5.00' },
  { name: '电路分析', tag: '#一页纸', color: C.teal },
  { name: '信号与系统', tag: '#期末真题', color: C.blue, price: '¥8.00' },
  { name: 'C 语言', tag: '#教材答案', color: C.amber },
  { name: '数据结构', tag: '#期中真题', color: C.blue },
  { name: '大学英语', tag: '#日常学习笔记', color: C.violet },
  { name: '复变函数', tag: '#期末速成', color: C.teal },
  { name: '通信原理', tag: '#一页纸', color: C.amber },
  { name: '计算机网络', tag: '#开卷资料', color: C.blue, price: '¥3.00' },
];

// Grid used at the end of S2 (and the start of S3).
export const GRID = { cols: 3, rows: 4, w: 260, h: 206, gapX: 30, gapY: 40, top: 430 }; // spans x 120..960
export function gridSlot(i) {
  const col = i % GRID.cols;
  const row = Math.floor(i / GRID.cols);
  const totalW = GRID.cols * GRID.w + (GRID.cols - 1) * GRID.gapX;
  const x0 = 540 - totalW / 2 + GRID.w / 2;
  return { cx: x0 + col * (GRID.w + GRID.gapX), cy: GRID.top + GRID.h / 2 + row * (GRID.h + GRID.gapY) };
}

// Card drawn in a local box (cx, cy, w, h). detail in [0,1] fades the inner content (for morphs).
export function materialCard({ cx, cy, w, h, course, inner = 1, shadow = true, fill = C.paper, r = null }) {
  const R = r ?? Math.min(w, h) * 0.11;
  let s = '';
  if (shadow) s += rr({ cx: cx + 6, cy: cy + 9, w, h, r: R }, 'rgba(15,23,42,0.10)');
  s += rr({ cx, cy, w, h, r: R }, fill);
  if (inner <= 0.01) return s;
  const k = w / GRID.w; // content scales with card width
  const left = cx - w / 2 + 26 * k;
  let c = '';
  // Course colour block (file icon) and title.
  c += rr({ cx: left + 22 * k, cy: cy - h / 2 + 50 * k, w: 44 * k, h: 54 * k, r: 10 * k }, course.color);
  c += rr({ cx: left + 22 * k, cy: cy - h / 2 + 44 * k, w: 22 * k, h: 5 * k, r: 2.5 * k }, 'rgba(255,255,255,0.85)');
  c += rr({ cx: left + 22 * k, cy: cy - h / 2 + 56 * k, w: 22 * k, h: 5 * k, r: 2.5 * k }, 'rgba(255,255,255,0.85)');
  c += text(course.name, left + 60 * k, cy - h / 2 + 62 * k, { size: 32 * k, weight: 800, fill: C.ink, anchor: 'start' });
  // Tag badge (outline style from the site: border #cbd5f5, text #1d4ed8) drawn as a soft fill.
  const tw = measure(course.tag, 22 * k, 600) + 26 * k;
  c += rr({ cx: left + tw / 2, cy: cy + 6 * k, w: tw, h: 38 * k, r: 19 * k }, '#e8eefc');
  c += text(course.tag, left + 13 * k, cy + 14 * k, { size: 22 * k, weight: 600, fill: C.blueDeep, anchor: 'start' });
  // Meta line: price and rating capsules.
  c += text(priceLabel(course), left, cy + h / 2 - 30 * k, { size: 24 * k, weight: 700, fill: priceColor(course), anchor: 'start' });
  c += rr({ cx: cx + w / 2 - 26 * k - 40 * k, cy: cy + h / 2 - 38 * k, w: 80 * k, h: 10 * k, r: 5 * k }, C.line);
  return s + g(c, { o: clamp(inner) });
}

export const priceLabel = (course) => course.price ?? '免费';
export const priceColor = (course) => (course.price ? C.blue : C.green);

// Small download-tray icon built from capsules (used in S3 and S5).
export function downloadIcon(cx, cy, size, color, o = 1) {
  const u = size / 100;
  let s = '';
  s += rr({ cx, cy: cy - 14 * u, w: 16 * u, h: 56 * u, r: 8 * u }, color);
  s += g(rr({ cx: cx - 14 * u, cy: cy + 4 * u, w: 16 * u, h: 40 * u, r: 8 * u }, color), { rot: -45, ox: cx - 14 * u, oy: cy + 4 * u });
  s += g(rr({ cx: cx + 14 * u, cy: cy + 4 * u, w: 16 * u, h: 40 * u, r: 8 * u }, color), { rot: 45, ox: cx + 14 * u, oy: cy + 4 * u });
  s += rr({ cx, cy: cy + 40 * u, w: 84 * u, h: 16 * u, r: 8 * u }, color);
  return g(s, { o });
}

export { num };

// ---------- Hand-off contracts between scenes (see cues.json "handoffs") ----------
// S3 -> S4 (15.0 s) and S5 -> S6 (26.0 s): the hero note sits here, upright, fully drawn.
// S3 ends on an ink (#0f172a) field; S5 ends on the soft (#f4f6fb) field.
export const HERO_NOTE = { cx: 540, cy: 960, w: 300, h: 390, accent: C.amber, lines: 4 };
export function heroNote(state = {}) {
  return noteCard({ ...HERO_NOTE, ...state });
}

// S5 data layout. S4 must end (20.0 s) with the faces icon of row 1 already formed at DATA.rows[0].
export const DATA = {
  kickerY: 330,
  iconX: 232,
  textX: 352,
  rows: [{ y: 650 }, { y: 950 }, { y: 1250 }],
  footY: 1480,
};
// Three student faces in a tight cluster: the "users" icon.
export const FACES_ICON = [
  { dx: -40, dy: 18, d: 78, color: C.teal },
  { dx: 40, dy: 18, d: 78, color: C.amber },
  { dx: 0, dy: -30, d: 86, color: C.blue },
];
export function facesIcon(cx, cy, k = 1, { happy = 1 } = {}) {
  let s = '';
  for (const f of FACES_ICON) s += student({ cx: cx + f.dx * k, cy: cy + f.dy * k, d: f.d * k, color: f.color, happy });
  return s;
}
