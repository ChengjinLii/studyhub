// Landscape (1920x1080) cut: frame size, safe area and the hand-off contracts between its scenes.
// Timing is shared with the portrait film through src/cues.json, so both cuts use the same soundtrack.
import { C, noteCard } from '../core.js';
import { student } from '../shared.js';

export const LW = 1920;
export const LH = 1080;
// Title-safe area for core text, logo and data (player controls sit at the bottom).
export const SAFE = { x0: 120, x1: 1800, y0: 70, y1: 990 };

// S1 -> S2 (3.0 s): every chat bubble implodes into one blue dot (r 36) here; S2's bot face grows from the same point.
export const MERGE_L = { x: 960, y: 420 };

// S2: big face and lockup, then the app header and the 6x2 course grid that S3 inherits at 7.85 s.
export const FACE_BIG_L = { cx: 960, cy: 420, d: 260 };
export const FACE_HEAD_L = { cx: 166, cy: 114, d: 76 }; // with its 4 px ring: y 72..156, inside SAFE
export const LOCK_BIG_L = { y: 700, size: 104 };
export const LOCK_HEAD_L = { left: 224, y: 128, size: 38 };
export const GRID_L = { cols: 6, rows: 2, w: 256, h: 196, gapX: 28, gapY: 36, top: 214 }; // spans x 122..1798
export function gridSlotL(i) {
  const col = i % GRID_L.cols;
  const row = Math.floor(i / GRID_L.cols);
  const totalW = GRID_L.cols * GRID_L.w + (GRID_L.cols - 1) * GRID_L.gapX;
  const x0 = LW / 2 - totalW / 2 + GRID_L.w / 2;
  return { cx: x0 + col * (GRID_L.w + GRID_L.gapX), cy: GRID_L.top + GRID_L.h / 2 + row * (GRID_L.h + GRID_L.gapY) };
}

// S3 -> S4 (15.0 s) and S5 -> S6 (26.0 s): the hero note, upright and centred.
// S3 ends on an ink (#0f172a) field; S5 ends on the soft (#f4f6fb) field.
export const HERO_NOTE_L = { cx: 960, cy: 540, w: 240, h: 312, accent: C.amber, lines: 4 };
export function heroNoteL(state = {}) {
  return noteCard({ ...HERO_NOTE_L, ...state });
}

// S5 data: three columns. S4 must end (20.0 s) with the faces icon already formed at column 0's icon slot.
export const DATA_L = {
  kickerY: 170,
  cols: [{ x: 420 }, { x: 960 }, { x: 1500 }],
  iconY: 400,
  numY: 650,
  unitY: 740,
  footY: 930,
};
// Same three faces as the portrait "users" icon (shared.js FACES_ICON), same offsets and sizes.
export { FACES_ICON, facesIcon } from '../shared.js';

export { student };
