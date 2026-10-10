// Film entry: composes the scenes for any time t. window.renderFrame(t) is a pure function of t.
import { C, FONT_CN, FONT_EN, resetClipIds } from './core.js';

// ?layout=landscape renders the 1920x1080 cut from src/landscape/scenes; the default is the 1080x1920 portrait film.
const LAYOUT = new URLSearchParams(location.search).get('layout') === 'landscape' ? 'landscape' : 'portrait';
const SIZE = LAYOUT === 'landscape' ? { w: 1920, h: 1080 } : { w: 1080, h: 1920 };
const DIR = LAYOUT === 'landscape' ? './landscape/scenes' : './scenes';
let SCENES = [];
const stage = document.getElementById('stage');
stage.setAttribute('viewBox', `0 0 ${SIZE.w} ${SIZE.h}`);
let cues = null;

async function init() {
  SCENES = await Promise.all(['s1', 's2', 's3', 's4', 's5', 's6'].map((n) => import(`${DIR}/${n}.js`)));
  cues = await (await fetch('./cues.json')).json();
  // Variable fonts load lazily; force every face we use before any measurement.
  const loads = [];
  for (const w of [400, 500, 600, 700, 800, 900]) loads.push(document.fonts.load(`${w} 48px 'Noto Sans SC'`, '学汇资料'));
  for (const w of [600, 700, 800]) loads.push(document.fonts.load(`${w} 48px 'Plus Jakarta Sans'`, 'StudyHub0123456789+'));
  await Promise.all(loads);
  await document.fonts.ready;
  const missing = ["800 48px 'Plus Jakarta Sans'", "900 48px 'Noto Sans SC'"].filter((f) => !document.fonts.check(f, '学汇Study'));
  if (missing.length) throw new Error('fonts not loaded: ' + missing.join(', '));
}

window.renderFrame = (tIn) => {
  const t = Math.min(Math.max(tIn, 0), (cues?.duration ?? 30) - 1e-6);
  resetClipIds();
  let bg = C.indigo;
  for (const sc of SCENES) if (sc.background && t >= sc.range[0] && t < sc.range[1]) bg = sc.background(t, cues);
  let body = `<rect width="${SIZE.w}" height="${SIZE.h}" fill="${bg}"/>`;
  for (const sc of SCENES) {
    if (t >= sc.range[0] && t < sc.range[1]) body += sc.draw(t, cues);
  }
  for (const sc of SCENES) {
    if (sc.overlay && t >= sc.overlay.range[0] && t < sc.overlay.range[1]) body += sc.overlay.draw(t, cues);
  }
  stage.innerHTML = body;
  return true;
};

window.filmLayout = LAYOUT;
window.filmReady = init().then(() => { window.renderFrame(0); return true; });
