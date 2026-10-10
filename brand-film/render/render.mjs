// Deterministic frame renderer for the StudyHub brand film.
// Every frame is a pure function of t = frame / FPS (see src/film.js renderFrame).
//
// Usage:
//   node render/render.mjs --out out/frames                 # all 900 frames, 1080x1920 PNG
//   node render/render.mjs --from 0 --to 3 --out out/clip   # seconds [from, to)
//   node render/render.mjs --scale 0.5 --format jpeg --out out/preview
//   node render/render.mjs --times 1.2,4.5,16 --out keyframes   # stills named t_01.20.png
//   node render/render.mjs --blur 4 --out out/frames             # 4 sub-frames per frame (180-degree shutter), averaged by build.sh
//   node render/render.mjs --layout landscape --times 5 --out out/l   # the 1920x1080 cut
import puppeteer from 'puppeteer-core';
import { mkdirSync, writeFileSync, existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import http from 'node:http';
import path from 'node:path';

const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FPS = 30;
const DURATION = 30;
let W = 1080;
let H = 1920;

function parseArgs(argv) {
  const a = { from: 0, to: DURATION, scale: 1, out: 'out/frames', workers: 4, format: 'png', times: null, blur: 1, layout: 'portrait' };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[i + 1];
    if (k === '--from') { a.from = Number(v); i++; }
    else if (k === '--to') { a.to = Number(v); i++; }
    else if (k === '--scale') { a.scale = Number(v); i++; }
    else if (k === '--out') { a.out = v; i++; }
    else if (k === '--workers') { a.workers = Number(v); i++; }
    else if (k === '--format') { a.format = v; i++; }
    else if (k === '--times') { a.times = v.split(',').map(Number); i++; }
    else if (k === '--blur') { a.blur = Math.max(1, Math.round(Number(v))); i++; }
    else if (k === '--layout') { a.layout = v; i++; }
    else throw new Error(`unknown argument ${k}`);
  }
  return a;
}

const args = parseArgs(process.argv.slice(2));
if (!['portrait', 'landscape'].includes(args.layout)) throw new Error(`--layout must be portrait or landscape, got ${args.layout}`);
if (args.layout === 'landscape') { W = 1920; H = 1080; }
const outDir = path.resolve(ROOT, args.out);
mkdirSync(outDir, { recursive: true });
if (!existsSync(CHROME)) throw new Error(`Chrome not found at ${CHROME}; set CHROME_PATH`);

// Job list: either explicit still times or a frame range.
let jobs;
if (args.times) {
  jobs = args.times.map((t) => ({ t, file: `t_${t.toFixed(2).padStart(5, '0')}.${args.format === 'jpeg' ? 'jpg' : 'png'}` }));
  // Two times that round to the same name would overwrite each other in parallel workers (Codex review P1).
  const seen = new Map();
  for (const j of jobs) {
    if (seen.has(j.file) && seen.get(j.file) !== j.t) throw new Error(`still times ${seen.get(j.file)} and ${j.t} map to the same file name ${j.file}`);
    seen.set(j.file, j.t);
  }
  jobs = jobs.filter((j, i) => jobs.findIndex((k) => k.file === j.file) === i);
} else {
  // Sub-frame k of frame f sits at f/FPS + (k - (B-1)/2) * shutter/(FPS*B): a 180-degree shutter centred on the frame time.
  // cues.json "blur.off" lists windows (e.g. full-frame iris wipes) rendered crisp: shutter 0 -> identical sub-frames.
  const cues = JSON.parse(readFileSync(path.join(ROOT, 'src', 'cues.json'), 'utf8'));
  const SHUTTER = cues.blur?.shutter ?? 0.5;
  const OFF = cues.blur?.off ?? [];
  const shutterAt = (t) => (OFF.some(([a, b]) => t >= a - 0.5 / FPS && t < b + 0.5 / FPS) ? 0 : SHUTTER);
  const B = args.blur;
  const f0 = Math.round(args.from * FPS);
  const f1 = Math.round(args.to * FPS);
  jobs = [];
  for (let f = f0; f < f1; f++) {
    for (let k = 0; k < B; k++) {
      const dt = B > 1 ? (k - (B - 1) / 2) * shutterAt(f / FPS) / (FPS * B) : 0;
      jobs.push({ t: f / FPS + dt, file: `f_${String(f * B + k).padStart(6, '0')}.${args.format === 'jpeg' ? 'jpg' : 'png'}` });
    }
  }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--hide-scrollbars', '--force-color-profile=srgb', '--font-render-hinting=none', '--disable-lcd-text'],
});

// Serve the project over loopback HTTP so ES modules, fetch() and @font-face work without file:// quirks.
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.json': 'application/json', '.ttf': 'font/ttf', '.otf': 'font/otf', '.png': 'image/png', '.svg': 'image/svg+xml' };
const server = http.createServer((req, res) => {
  let rel;
  try { rel = decodeURIComponent(new URL(req.url, 'http://x').pathname); } catch { res.writeHead(400); res.end(); return; }
  if (rel === '/favicon.ico') { res.writeHead(204); res.end(); return; }
  const file = path.normalize(path.join(ROOT, rel));
  if (!file.startsWith(ROOT + path.sep) || !existsSync(file)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const pageUrl = `http://127.0.0.1:${server.address().port}/src/film.html?layout=${args.layout}`;
const vw = Math.round(W * args.scale);
const vh = Math.round(H * args.scale);

async function openPage() {
  const page = await browser.newPage();
  page.on('pageerror', (e) => { console.error('pageerror:', e.message); process.exitCode = 1; });
  // A console error (e.g. an invalid SVG attribute) fails the render instead of passing silently (Opus review P2-3).
  page.on('console', (m) => {
    if (m.type() === 'error') { console.error('console error:', m.text()); process.exitCode = 1; }
    else if (m.type() === 'warning') console.error('console warning:', m.text());
  });
  await page.setViewport({ width: vw, height: vh, deviceScaleFactor: 1 });
  await page.goto(pageUrl, { waitUntil: 'load' });
  await page.evaluate(() => window.filmReady);
  const got = await page.evaluate(() => window.filmLayout);
  if (got !== args.layout) throw new Error(`page layout ${got} != requested ${args.layout}`);
  return page;
}

const nWorkers = Math.max(1, Math.min(args.workers, jobs.length));
const pages = await Promise.all(Array.from({ length: nWorkers }, openPage));
const t0 = performance.now();
let done = 0;

await Promise.all(pages.map(async (page, w) => {
  for (let j = w; j < jobs.length; j += nWorkers) {
    const { t, file } = jobs[j];
    await page.evaluate((tt) => window.renderFrame(tt), t);
    const buf = await page.screenshot({ type: args.format, ...(args.format === 'jpeg' ? { quality: 92 } : {}) });
    writeFileSync(path.join(outDir, file), buf);
    done++;
    if (done % 60 === 0) process.stderr.write(`  ${done}/${jobs.length} frames\n`);
  }
}));

const secs = (performance.now() - t0) / 1000;
console.log(`rendered ${jobs.length} frame(s) at ${vw}x${vh} in ${secs.toFixed(1)} s (${(jobs.length / secs).toFixed(1)} fps) -> ${outDir}`);
await browser.close();
server.close();
