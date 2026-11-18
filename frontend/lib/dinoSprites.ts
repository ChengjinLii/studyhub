export const DINO_ROWS = 21;
export const DINO_COLS = 20;
export const DINO_DUCK_ROWS = 13;
export const DINO_DUCK_COLS = 28;
export const BIRD_ROWS = 16;
export const BIRD_COLS = 22;

export interface SpanRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LayeredPixelSprite {
  body: SpanRect[];
  cutouts: SpanRect[];
  accents?: SpanRect[];
}

export const clamp = (v: number, lo: number, hi: number): number =>
  v < lo ? lo : v > hi ? hi : v;

export const smoothstep = (t: number): number => t * t * (3 - 2 * t);

/**
 * Compile both horizontal and vertical runs so external staircase corners
 * round smoothly while interior joints stay solidly filled.
 */
export const compileSmoothSprite = (rows: readonly string[]): SpanRect[] => {
  const rects: SpanRect[] = [];
  const rowCount = rows.length;
  const colCount = rowCount > 0 ? rows[0].length : 0;

  for (let r = 0; r < rowCount; r += 1) {
    const row = rows[r];
    let runStart = -1;
    for (let c = 0; c <= colCount; c += 1) {
      const active = c < colCount && row[c] === '#';
      if (active && runStart === -1) {
        runStart = c;
      } else if (!active && runStart !== -1) {
        rects.push({ x: runStart, y: r, w: c - runStart, h: 1 });
        runStart = -1;
      }
    }
  }

  for (let c = 0; c < colCount; c += 1) {
    let runStart = -1;
    for (let r = 0; r <= rowCount; r += 1) {
      const active = r < rowCount && rows[r][c] === '#';
      if (active && runStart === -1) {
        runStart = r;
      } else if (!active && runStart !== -1) {
        const len = r - runStart;
        if (len >= 2) {
          rects.push({ x: c, y: runStart, w: 1, h: len });
        }
        runStart = -1;
      }
    }
  }

  return rects;
};

/**
 * Greedy 2D rectangle merger for crisp fine pixel art (cellScale = 0.5 matches Chrome Dino density).
 */
export const compileCrispRuns = (
  rows: readonly string[],
  targetChar: string,
  cellScale = 0.5
): SpanRect[] => {
  const h = rows.length;
  const w = h > 0 ? rows[0].length : 0;
  let active = new Map<string, SpanRect>();
  const out: SpanRect[] = [];

  for (let r = 0; r < h; r += 1) {
    const row = rows[r];
    const nextActive = new Map<string, SpanRect>();
    let cStart = -1;
    for (let c = 0; c <= w; c += 1) {
      const match = c < w && row[c] === targetChar;
      if (match && cStart === -1) {
        cStart = c;
      } else if (!match && cStart !== -1) {
        const key = `${cStart}:${c}`;
        const prev = active.get(key);
        if (prev) {
          prev.h += cellScale;
          nextActive.set(key, prev);
          active.delete(key);
        } else {
          nextActive.set(key, {
            x: cStart * cellScale,
            y: r * cellScale,
            w: (c - cStart) * cellScale,
            h: cellScale,
          });
        }
        cStart = -1;
      }
    }
    active.forEach((rect) => out.push(rect));
    active = nextActive;
  }
  active.forEach((rect) => out.push(rect));
  return out;
};

/**
 * Compile multi-layer crisp pixel art where '#' is white fill, 'o' is rendered as a #1a1c20 cutout,
 * and 'r' is rendered as a bright red (#ef4444) exam-grading accent over the white base.
 */
export const compileLayeredSprite = (rows: readonly string[], cellScale = 0.5): LayeredPixelSprite => {
  const normalizedBody = rows.map((r) => r.replace(/[or]/g, '#'));
  const accents = compileCrispRuns(rows, 'r', cellScale);
  return {
    body: compileCrispRuns(normalizedBody, '#', cellScale),
    cutouts: compileCrispRuns(rows, 'o', cellScale),
    ...(accents.length > 0 ? { accents } : {}),
  };
};

// Fixed 20x18 standing T-Rex torso: continuous forelimb, sealed tail-hip joint, and clean tail taper.
export const DINO_UPPER_ROWS = [
  '..........########..',
  '.........##########.',
  '.........##.#######.',
  '.........##########.',
  '.........##########.',
  '.........#####......',
  '........#########...',
  '........######......',
  '#......########.....',
  '##....#########.....',
  '###..#############..',
  '###############..#..',
  '###############.....',
  '.#############......',
  '..###########.......',
  '...#########........',
  '....#######.........',
  '....######..........',
] as const;

// Startled crash upper torso with open jaw and solid head socket (drawn with X eye in drawDinoEye).
export const DINO_CRASH_UPPER_ROWS = [
  '..........########..',
  '.........##########.',
  '.........##########.',
  '.........##########.',
  '.........##########.',
  '.........####.......',
  '........#########...',
  '........######......',
  '#......########.....',
  '##....#########.....',
  '###..#############..',
  '###############..#..',
  '###############.....',
  '.#############......',
  '..###########.......',
  '...#########........',
  '....#######.........',
  '....######..........',
] as const;

export const DINO_LEGS_BOTH = [
  '....##..##..........',
  '....##..##..........',
  '....###.###.........',
] as const;

const DINO_LEGS_0 = [
  '....##..###.........',
  '....##..............',
  '....###.............',
] as const;

const DINO_LEGS_1 = [
  '....##...##.........',
  '...##....###........',
  '...###..............',
] as const;

const DINO_LEGS_2 = [
  '....###..##.........',
  '.........##.........',
  '.........###........',
] as const;

const DINO_LEGS_3 = [
  '.....##..##.........',
  '.....###..##........',
  '..........###.......',
] as const;

const DINO_LEGS_JUMP = [
  '...###..###.........',
  '...###...###........',
  '....................',
] as const;

// Fixed 28x10 ducking T-Rex torso: continuous forelimb attached to chest (col 20).
export const DINO_DUCK_UPPER = [
  '..................########..',
  '.................##########.',
  '#...............###.#######.',
  '##.............############.',
  '###..######################.',
  '.########################...',
  '..###################.......',
  '...###############..#.......',
  '....#############...........',
  '.....###########............',
] as const;

export const DINO_DUCK_LEGS_A = [
  '......##...###..............',
  '......##....................',
  '......###...................',
] as const;

const DINO_DUCK_LEGS_1 = [
  '......##...##...............',
  '.....##....###..............',
  '.....###....................',
] as const;

const DINO_DUCK_LEGS_B = [
  '......###...##..............',
  '............##..............',
  '............###.............',
] as const;

const DINO_DUCK_LEGS_3 = [
  '.......##..##...............',
  '.......###..##..............',
  '............###.............',
] as const;

// Refined Chrome-grade 0.5x texel pixel-art obstacles & cloud (dino stays intact)

const BIRD_FRAME_A_ROWS = [
  '.....................##.....................',
  '....................####....................',
  '...................######...................',
  '..................########..................',
  '.................##########.................',
  '................############................',
  '..........#####.#############...............',
  '.........######.##############..............',
  '.......########.###############.............',
  '.....######oo##################.............',
  '...########oo###################............',
  '.###############################............',
  '...#####..########################..........',
  '..........##########################........',
  '............###########################.....',
  '..............###########################...',
  '................######################..##..',
  '..................################..........',
  '....................##########..............',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
] as const;

const BIRD_FRAME_B_ROWS = [
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '..........#####.............................',
  '.........######.............................',
  '.......########.............................',
  '.....######oo##.............................',
  '...########oo####...........................',
  '.################...........................',
  '...#####..##########........................',
  '..........####################..............',
  '............########################........',
  '..............###########################...',
  '................##########################..',
  '.................##################.........',
  '..................################..........',
  '..................##############............',
  '...................############.............',
  '...................###########..............',
  '....................#########...............',
  '....................########................',
  '.....................######.................',
  '.....................#####..................',
  '......................####..................',
  '......................###...................',
  '.......................##...................',
  '.......................#....................',
  '............................................',
  '............................................',
] as const;

const PAPER_PLANE_A_ROWS = [
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '................................####........',
  '............................########........',
  '........................############........',
  '....................################........',
  '................##################oo..####..',
  '............##################ooo##.........',
  '........##################ooo####...........',
  '....##################ooo#####..............',
  '..################ooo########.....#####.....',
  '##############ooo##############.............',
  '##########ooo####################..###......',
  '######oo###########################.........',
  '....###############################.........',
  '........#########oo############.............',
  '...........######oo#########.....####.......',
  '..............###oo######...................',
  '................#oo####.....................',
  '.................oo##.......................',
  '..................#.........................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
] as const;

const PAPER_PLANE_B_ROWS = [
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '................................####........',
  '............................########........',
  '........................############........',
  '....................################........',
  '................##################oo...####.',
  '............##################ooo##.........',
  '........##################ooo####...........',
  '....##################ooo#####..............',
  '..################ooo########....#####......',
  '##############ooo##############.............',
  '##########ooo####################...###.....',
  '######oo###########################.........',
  '....###############################.........',
  '........#########oo############.............',
  '...........######oo#########....####........',
  '..............###oo######...................',
  '................#oo####.....................',
  '.................oo##.......................',
  '..................#.........................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
] as const;

const UFO_A_ROWS = [
  '............................................',
  '............................................',
  '............................................',
  '..................########..................',
  '................############................',
  '..............####ooo#########..............',
  '.............###oo#############.............',
  '............###o################............',
  '............####################............',
  '...........######################...........',
  '...........#oooooooooooooooooooo#...........',
  '.......##############################.......',
  '....####################################....',
  '..########################################..',
  '.#####oo######oo######oo######oo######oo###.',
  '.#####oo######oo######oo######oo######oo###.',
  '.##########################################.',
  '..########################################..',
  '....####################################....',
  '.......##############################.......',
  '............####################............',
  '..............################..............',
  '............................................',
  '..............####........####..............',
  '............................................',
  '............##................##............',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
] as const;

const UFO_B_ROWS = [
  '............................................',
  '............................................',
  '............................................',
  '..................########..................',
  '................############................',
  '..............####ooo#########..............',
  '.............###oo#############.............',
  '............###o################............',
  '............####################............',
  '...........######################...........',
  '...........#oooooooooooooooooooo#...........',
  '.......##############################.......',
  '....####################################....',
  '..########################################..',
  '.##oo######oo######oo######oo######oo######.',
  '.##oo######oo######oo######oo######oo######.',
  '.##########################################.',
  '..########################################..',
  '....####################################....',
  '.......##############################.......',
  '............####################............',
  '..............################..............',
  '............................................',
  '.................##########.................',
  '............................................',
  '..............####........####..............',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
  '............................................',
] as const;

const CLOUD_ROWS = [
  '..................########..................',
  '................############................',
  '..............################..............',
  '.........########################...........',
  '.......############################.........',
  '.....################################.......',
  '...####################################.....',
  '..######################################....',
  '.#########################################..',
  '###########################################.',
  '############################################',
  '############################################',
  '.##########################################.',
  '..########################################..',
] as const;

const CACTUS_SMALL_ROWS = [
  '........##........',
  '.......####.......',
  '.......####.......',
  '.......####.......',
  '.......#####......',
  '.......####.......',
  '..#....####.......',
  '.###...####.......',
  '.###...####.......',
  '####...####.......',
  '.###...####....#..',
  '.###...####...###.',
  '.###...####...###.',
  '.##########...####',
  '.##########...###.',
  '..#########...###.',
  '...########...###.',
  '.......##########.',
  '.......##########.',
  '.......#########..',
  '.......########...',
  '.......####.......',
  '.......####.......',
  '......#####.......',
  '.......####.......',
  '.......####.......',
  '.......####.......',
  '.......####.......',
  '.......####.......',
  '.......####.......',
] as const;

const CACTUS_TALL_ROWS = [
  '........####........',
  '.......######.......',
  '.......######.......',
  '.......######.......',
  '.......######.......',
  '.......######....#..',
  '.......######...###.',
  '.......######...###.',
  '.......######...####',
  '.......######...###.',
  '.......######...###.',
  '..#....######...###.',
  '.###...######...###.',
  '.###...############.',
  '####...############.',
  '.###...###########..',
  '.###...##########...',
  '.###...######.......',
  '.###...######.......',
  '.############.......',
  '.############.......',
  '..###########.......',
  '...##########.......',
  '.......######.......',
  '.......######.......',
  '.......######.......',
  '.......######.......',
  '......#######.......',
  '.......######.......',
  '.......######.......',
  '.......######.......',
  '.......######.......',
  '.......######.......',
  '.......######.......',
] as const;

const CACTUS_TWIN_ROWS = [
  '......##......................',
  '.....####.....................',
  '.....####.....................',
  '.....####.....................',
  '.....####...#.................',
  '.....####..###................',
  '.....####..###........##......',
  '.#...####..####......####.....',
  '###..####..###.......####.....',
  '###..####..###.......####...#.',
  '###..####..###.......####..###',
  '###..#########.......####..###',
  '###..#########...#...####..###',
  '###..########...###..####..###',
  '############....###..####..###',
  '#########......####..#########',
  '.########.......###..#########',
  '..#######.......###..########.',
  '.....####.......############..',
  '.....####.......#########.....',
  '.....####........########.....',
  '....#####.........#######.....',
  '.....####............####.....',
  '.....####............####.....',
  '.....####............####.....',
  '.....####............####.....',
  '.....####............####.....',
  '.....####............####.....',
] as const;

const CACTUS_TRIPLE_ROWS = [
  '...................##...................',
  '..................####..................',
  '..................####..................',
  '..................####..................',
  '..................#####.................',
  '..................####..................',
  '..................####..................',
  '......#.......##..####..................',
  '.....###......##..####..................',
  '.....###.....###..####..................',
  '.....###......##..####..##........#.....',
  '.....###..##..##..####..##.......###....',
  '.....###..##..##..####..###......###....',
  '.....###..###.########..##.......###....',
  '.##..###..##..########..##.......###..##',
  '.##..###..##...#######..##.......###..##',
  '###..#######....##########.......###..##',
  '.##..#######......########...##..###..##',
  '.##..######.......#######....##..#######',
  '.#########........######....###..#######',
  '.#######..........####.......##..######.',
  '..######..........####.......#########..',
  '...#####..........####.......#######....',
  '.....###..........####........######....',
  '.....###..........####.........#####....',
  '....####.........#####...........###....',
  '.....###..........####...........###....',
  '.....###..........####...........###....',
  '.....###..........####...........###....',
  '.....###..........####...........###....',
  '.....###..........####...........###....',
  '.....###..........####...........###....',
] as const;

export const CAMPUS_EXAM_PAPER_ROWS = [
  '..#################.........',
  '.##################oo.......',
  '.##################oo#......',
  '.##################oo##.....',
  '.###oooooooo#######oo###....',
  '.###oooooooo#######oo####...',
  '.##################ooooooo..',
  '.##################ooooooo..',
  '.###oooooo################..',
  '.###oooooo############rrr#..',
  '.####################rrr##..',
  '.##############rr###rrr###..',
  '.##############rrrrrrr####..',
  '.###############rrrrr#####..',
  '.################rrr######..',
  '.#########################..',
  '.###ooooooooooooooooooo###..',
  '.###ooooooooooooooooooo###..',
  '.#########################..',
  '.#########################..',
  '.#########################..',
  '.###ooooooooooooooooooo###..',
  '.###ooooooooooooooooooo###..',
  '.#########################..',
  '.#########################..',
  '.#########################..',
  '.###ooooooooooooo###rrr###..',
  '.###ooooooooooooo##rrrr###..',
  '.#########################..',
  '.#########################..',
  '.###oooooooo##############..',
  '.###oooooooo##############..',
  '.#########################..',
  '..#######################...',
] as const;

const CAMPUS_COFFEE_A_ROWS = [
  '......##.....##.........',
  '.......##.....##........',
  '.......##.....##........',
  '......##.....##.........',
  '.....##.....##..........',
  '.....##.....##..........',
  '......##.....##.........',
  '........................',
  '....####................',
  '....############........',
  '..################......',
  '.##################.....',
  '..#oooooooooooooo#......',
  '...##############.......',
  '...##############.......',
  '...##################...',
  '...###############..##..',
  '...####oooooooooo#...##.',
  '...##############....##.',
  '...#######oo#####....##.',
  '...######o##o####....##.',
  '...#######oo#####...##..',
  '...####oooooooooo#.##...',
  '....#################...',
  '....############........',
  '....############........',
  '.....##########.........',
  '.....##########.........',
  '......########..........',
  '......########..........',
] as const;

const CAMPUS_COFFEE_B_ROWS = [
  '.......##.....##........',
  '......##.....##.........',
  '.....##.....##..........',
  '.....##.....##..........',
  '......##.....##.........',
  '.......##.....##........',
  '......##.....##.........',
  '........................',
  '....####................',
  '....############........',
  '..################......',
  '.##################.....',
  '..#oooooooooooooo#......',
  '...##############.......',
  '...##############.......',
  '...##################...',
  '...###############..##..',
  '...####oooooooooo#...##.',
  '...##############....##.',
  '...#######oo#####....##.',
  '...######o##o####....##.',
  '...#######oo#####...##..',
  '...####oooooooooo#.##...',
  '....#################...',
  '....############........',
  '....############........',
  '.....##########.........',
  '.....##########.........',
  '......########..........',
  '......########..........',
] as const;

export const SPRITE_DINO_IDLE = compileSmoothSprite([...DINO_UPPER_ROWS, ...DINO_LEGS_BOTH]);
export const SPRITE_DINO_RUN_A = compileSmoothSprite([...DINO_UPPER_ROWS, ...DINO_LEGS_0]);
const SPRITE_DINO_RUN_1 = compileSmoothSprite([...DINO_UPPER_ROWS, ...DINO_LEGS_1]);
export const SPRITE_DINO_RUN_B = compileSmoothSprite([...DINO_UPPER_ROWS, ...DINO_LEGS_2]);
const SPRITE_DINO_RUN_3 = compileSmoothSprite([...DINO_UPPER_ROWS, ...DINO_LEGS_3]);
export const SPRITE_DINO_RUN_FRAMES = [
  SPRITE_DINO_RUN_A,
  SPRITE_DINO_RUN_1,
  SPRITE_DINO_RUN_B,
  SPRITE_DINO_RUN_3,
] as const;
export const SPRITE_DINO_JUMP = compileSmoothSprite([...DINO_UPPER_ROWS, ...DINO_LEGS_JUMP]);
export const SPRITE_DINO_CRASH = compileSmoothSprite([...DINO_CRASH_UPPER_ROWS, ...DINO_LEGS_BOTH]);

export const SPRITE_DINO_DUCK_A = compileSmoothSprite([...DINO_DUCK_UPPER, ...DINO_DUCK_LEGS_A]);
const SPRITE_DINO_DUCK_1 = compileSmoothSprite([...DINO_DUCK_UPPER, ...DINO_DUCK_LEGS_1]);
export const SPRITE_DINO_DUCK_B = compileSmoothSprite([...DINO_DUCK_UPPER, ...DINO_DUCK_LEGS_B]);
const SPRITE_DINO_DUCK_3 = compileSmoothSprite([...DINO_DUCK_UPPER, ...DINO_DUCK_LEGS_3]);
export const SPRITE_DINO_DUCK_FRAMES = [
  SPRITE_DINO_DUCK_A,
  SPRITE_DINO_DUCK_1,
  SPRITE_DINO_DUCK_B,
  SPRITE_DINO_DUCK_3,
] as const;

const BIRD_LAYERED_A = compileLayeredSprite(BIRD_FRAME_A_ROWS);
const BIRD_LAYERED_B = compileLayeredSprite(BIRD_FRAME_B_ROWS);
export const SPRITE_BIRD_A = BIRD_LAYERED_A.body;
export const SPRITE_BIRD_B = BIRD_LAYERED_B.body;

const PAPER_PLANE_LAYERED_A = compileLayeredSprite(PAPER_PLANE_A_ROWS);
const PAPER_PLANE_LAYERED_B = compileLayeredSprite(PAPER_PLANE_B_ROWS);
const UFO_LAYERED_A = compileLayeredSprite(UFO_A_ROWS);
const UFO_LAYERED_B = compileLayeredSprite(UFO_B_ROWS);
const SPRITE_CLOUD = compileCrispRuns(CLOUD_ROWS, '#', 0.5);

const GROUND_SPRITE_SMALL = compileLayeredSprite(CACTUS_SMALL_ROWS);
const GROUND_SPRITE_TALL = compileLayeredSprite(CACTUS_TALL_ROWS);
const GROUND_SPRITE_TWIN = compileLayeredSprite(CACTUS_TWIN_ROWS);
const GROUND_SPRITE_TRIPLE = compileLayeredSprite(CACTUS_TRIPLE_ROWS);
const GROUND_SPRITE_PAPER = compileLayeredSprite(CAMPUS_EXAM_PAPER_ROWS);
const GROUND_SPRITE_COFFEE_A = compileLayeredSprite(CAMPUS_COFFEE_A_ROWS);
const GROUND_SPRITE_COFFEE_B = compileLayeredSprite(CAMPUS_COFFEE_B_ROWS);

export type CactusKind = 'small' | 'tall' | 'twin' | 'triple' | 'paper' | 'coffee';
export type AirObstacleKind = 'bird' | 'paper_plane' | 'ufo';

export const AIR_VARIANTS: readonly AirObstacleKind[] = ['bird', 'paper_plane', 'ufo'] as const;

export interface CactusSpec {
  kind: CactusKind;
  w: number;
  h: number;
  frames: readonly LayeredPixelSprite[];
}

export const CACTUS_VARIANTS: readonly CactusSpec[] = [
  { kind: 'small', w: 9, h: 15, frames: [GROUND_SPRITE_SMALL] },
  { kind: 'tall', w: 10, h: 17, frames: [GROUND_SPRITE_TALL] },
  { kind: 'twin', w: 15, h: 14, frames: [GROUND_SPRITE_TWIN] },
  { kind: 'triple', w: 20, h: 16, frames: [GROUND_SPRITE_TRIPLE] },
  { kind: 'paper', w: 14, h: 17, frames: [GROUND_SPRITE_PAPER] },
  { kind: 'coffee', w: 12, h: 15, frames: [GROUND_SPRITE_COFFEE_A, GROUND_SPRITE_COFFEE_B] },
] as const;

// Chrome 97 / Android WebView safe rounded rect (avoids ctx.roundRect & ctx.ellipse)
export const appendRoundRectPath = (
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  rawR: number
) => {
  if (w <= 0 || h <= 0) return;
  const r = Math.max(0, Math.min(rawR, w * 0.5, h * 0.5));
  if (r <= 0.05) {
    ctx.rect(x, y, w, h);
    return;
  }
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
};

export const drawSmoothSprite = (
  ctx: CanvasRenderingContext2D,
  spans: readonly SpanRect[],
  originX: number,
  originY: number,
  px: number
) => {
  const radius = 0.42 * px;
  ctx.beginPath();
  for (let i = 0; i < spans.length; i += 1) {
    const s = spans[i];
    appendRoundRectPath(ctx, originX + s.x * px, originY + s.y * px, s.w * px, s.h * px, radius);
  }
  ctx.fill();
};

export const drawCrispSpans = (
  ctx: CanvasRenderingContext2D,
  spans: readonly SpanRect[],
  originX: number,
  originY: number,
  px: number,
  seamPad = 0
) => {
  ctx.beginPath();
  for (let i = 0; i < spans.length; i += 1) {
    const s = spans[i];
    ctx.rect(
      originX + s.x * px - seamPad,
      originY + s.y * px - seamPad,
      s.w * px + seamPad * 2,
      s.h * px + seamPad * 2
    );
  }
  ctx.fill();
};

export const drawLayeredSprite = (
  ctx: CanvasRenderingContext2D,
  sprite: LayeredPixelSprite,
  originX: number,
  originY: number,
  px: number,
  cutoutColor = '#1a1c20'
) => {
  ctx.fillStyle = '#ffffff';
  drawCrispSpans(ctx, sprite.body, originX, originY, px, 0.015 * px);
  if (sprite.cutouts.length > 0) {
    ctx.fillStyle = cutoutColor;
    drawCrispSpans(ctx, sprite.cutouts, originX, originY, px, 0);
  }
  if (sprite.accents && sprite.accents.length > 0) {
    ctx.fillStyle = '#ef4444';
    drawCrispSpans(ctx, sprite.accents, originX, originY, px, 0);
  }
  ctx.fillStyle = '#ffffff';
};

export const drawCactusVector = (
  ctx: CanvasRenderingContext2D,
  kind: CactusKind,
  x: number,
  y: number,
  px: number,
  altFrame = false
) => {
  const spec = CACTUS_VARIANTS.find((item) => item.kind === kind) ?? CACTUS_VARIANTS[0];
  const frame = spec.frames.length > 1 && altFrame ? spec.frames[1] : spec.frames[0];
  drawLayeredSprite(ctx, frame, x, y, px);
};

export const drawAirObstacle = (
  ctx: CanvasRenderingContext2D,
  variantIndex: number,
  altFrame: boolean,
  x: number,
  y: number,
  px: number
) => {
  const kind = AIR_VARIANTS[((variantIndex % AIR_VARIANTS.length) + AIR_VARIANTS.length) % AIR_VARIANTS.length];
  if (kind === 'paper_plane') {
    drawLayeredSprite(ctx, altFrame ? PAPER_PLANE_LAYERED_B : PAPER_PLANE_LAYERED_A, x, y, px);
    return;
  }
  if (kind === 'ufo') {
    drawLayeredSprite(ctx, altFrame ? UFO_LAYERED_B : UFO_LAYERED_A, x, y, px);
    return;
  }
  drawLayeredSprite(ctx, altFrame ? BIRD_LAYERED_B : BIRD_LAYERED_A, x, y, px);
};

export const drawCloudVector = (
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  px: number
) => {
  drawCrispSpans(ctx, SPRITE_CLOUD, x, y, px, 0.015 * px);
};

export const drawDinoEye = (
  ctx: CanvasRenderingContext2D,
  originX: number,
  originY: number,
  px: number,
  options: { crashed?: boolean; blinking?: boolean; ducking?: boolean }
) => {
  const { crashed = false, blinking = false, ducking = false } = options;
  if (crashed) {
    // Crisp startled eye socket + white sclera + dark dizzy X eye
    ctx.fillStyle = '#1a1c20';
    ctx.beginPath();
    appendRoundRectPath(ctx, originX + 10.5 * px, originY + 1.3 * px, 2.8 * px, 2.8 * px, 0.5 * px);
    ctx.fill();

    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    appendRoundRectPath(ctx, originX + 10.9 * px, originY + 1.7 * px, 2.0 * px, 2.0 * px, 0.35 * px);
    ctx.fill();

    ctx.save();
    ctx.strokeStyle = '#1a1c20';
    ctx.lineWidth = Math.max(1, 0.48 * px);
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(originX + 11.15 * px, originY + 1.95 * px);
    ctx.lineTo(originX + 12.65 * px, originY + 3.45 * px);
    ctx.moveTo(originX + 12.65 * px, originY + 1.95 * px);
    ctx.lineTo(originX + 11.15 * px, originY + 3.45 * px);
    ctx.stroke();
    ctx.restore();
    return;
  }

  if (blinking) return;

  const eyeX = ducking ? originX + 19.0 * px : originX + 11.0 * px;
  const eyeY = originY + 2.0 * px;
  ctx.fillStyle = '#1a1c20';
  ctx.beginPath();
  appendRoundRectPath(ctx, eyeX, eyeY, 1.15 * px, 1.15 * px, 0.35 * px);
  ctx.fill();
};

export const DINO_HANDOFF_EVENT = 'studyhub:dino-handoff';

export interface SplashHandoffObstacle {
  kind: 'cactus' | 'bird';
  viewportX: number;
  variantIndex: number;
  altitudeFactor: number;
}

export interface SplashDinoHandoffPayload {
  obstacles: SplashHandoffObstacle[];
  legToggle: boolean;
  blinkRemaining: number;
  timestamp: number;
  speed: number;
  strideProgress: number;
}

let pendingSplashHandoff: SplashDinoHandoffPayload | null = null;

export const publishSplashDinoHandoff = (payload: SplashDinoHandoffPayload) => {
  pendingSplashHandoff = {
    obstacles: payload.obstacles.map((item) => ({ ...item })),
    legToggle: payload.legToggle,
    blinkRemaining: payload.blinkRemaining,
    timestamp: payload.timestamp,
    speed: payload.speed,
    strideProgress: payload.strideProgress,
  };
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(DINO_HANDOFF_EVENT, { detail: pendingSplashHandoff }));
  }
};

export const consumeSplashDinoHandoff = (): SplashDinoHandoffPayload | null => {
  const payload = pendingSplashHandoff;
  pendingSplashHandoff = null;
  return payload;
};

export interface DinoViewportLayout {
  dinoX: number;
  pixelSize: number;
  baseSpeed: number;
  jumpVy: number;
  gravity: number;
}

/**
 * Computes consistent resting placement and scale for the home dino across both
 * OpeningSplash (dock target) and PortalDinoHorizon (runway).
 * Places the dino cleanly to the left of the centered search box on desktop/tablet.
 */
export const getDinoViewportLayout = (
  cssWidth: number,
  vw: number,
  vh: number
): DinoViewportLayout => {
  if (vw <= 768) {
    const compactMobile = vh <= 680;
    return {
      dinoX: 24,
      pixelSize: compactMobile ? 1.22 : 1.42,
      baseSpeed: compactMobile ? 134 : 148,
      jumpVy: compactMobile ? -274 : -300,
      gravity: compactMobile ? 1120 : 1160,
    };
  }

  const searchWidth =
    vw <= 900
      ? Math.min(cssWidth - 48, 480)
      : vw <= 1024
        ? Math.min(cssWidth - 48, 520)
        : Math.min(cssWidth - 48, 680);
  const searchLeft = (cssWidth - searchWidth) / 2;
  const gapFromSearch = vw <= 1024 ? 92 : 124;
  const dinoX = Math.round(clamp(searchLeft - gapFromSearch, 36, Math.max(36, searchLeft - 72)));

  if (vh <= 650) {
    return {
      dinoX,
      pixelSize: 1.52,
      baseSpeed: 158,
      jumpVy: -310,
      gravity: 1220,
    };
  }

  if (vh <= 820) {
    return {
      dinoX,
      pixelSize: 1.78,
      baseSpeed: 180,
      jumpVy: -342,
      gravity: 1280,
    };
  }

  return {
    dinoX,
    pixelSize: 2.08,
    baseSpeed: 204,
    jumpVy: -376,
    gravity: 1360,
  };
};
