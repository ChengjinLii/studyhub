import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { computeHomeRevealTail, easeHomeRevealProgress } from '../../lib/homeDiscovery';
import {
  AIR_VARIANTS,
  CACTUS_VARIANTS,
  CAMPUS_EXAM_PAPER_ROWS,
  DINO_DUCK_LEGS_A,
  DINO_DUCK_UPPER,
  DINO_LEGS_BOTH,
  DINO_UPPER_ROWS,
  getDinoViewportLayout,
} from '../../lib/dinoSprites';
import {
  clearQuickUploadFiles,
  consumeQuickUploadFiles,
  peekQuickUploadFiles,
  stageQuickUploadFiles,
} from '../../lib/quickUploadHandoff';

const readSource = (relativePath: string) =>
  readFileSync(join(process.cwd(), relativePath), 'utf8');

const minimalVariantSource = () => {
  const card = readSource('components/MaterialCard.tsx');
  return card.slice(card.indexOf("if (variant === 'minimal')"), card.indexOf("if (variant === 'list')"));
};

describe('brand wordmark', () => {
  it('shows only "StudyHub" in the navbar and the Zhipu-style 学汇 | StudyHub lockup in the footer', () => {
    const navbar = readSource('components/NavBar.tsx');
    const app = readSource('pages/_app.tsx');
    const footerBrand = app.slice(app.indexOf('footerStyles.brandRow'), app.indexOf('footerStyles.navGrid'));

    expect(navbar).not.toContain('学汇');
    expect(footerBrand).toContain('brandMarkSvg');
    expect(footerBrand).toContain('brandZhSvg');
    expect(footerBrand).toContain('brandDivider');
    expect(footerBrand).toContain('brandWordmarkSvg');
    expect(footerBrand).toContain('学汇');
    expect(footerBrand).toContain('StudyHub');
  });

  // Owner request (2026-11-16): the search-portal and splash use the vectorized no-logo StudyHub SVG
  // with silver-grey "H" (#b8b8ba), the navbar keeps its BrandLogo + wordmark font, and the footer
  // renders the Zhipu-style [Mark] 学汇 | StudyHub vector lockup.
  it('renders the vectorized StudyHub wordmark SVG across splash, portal, and footer while preserving navbar', () => {
    expect(readSource('styles/AnimateHeader.module.css')).toContain(
      'font-family: var(--font-wordmark), var(--font-stack);',
    );
    const app = readSource('pages/_app.tsx');
    const navbar = readSource('components/NavBar.tsx');
    const brandFont = readSource('lib/brandFont.ts');
    const wordmarkModule = readSource('lib/studyhubWordmark.ts');
    const wordmarkSvg = readSource('public/brand/studyhub-wordmark.svg');
    const footerCss = readSource('styles/SiteFooter.module.css');
    const portalCss = readSource('styles/HomePortal.module.css');
    const splashCss = readSource('styles/OpeningSplash.module.css');
    const portalTsx = readSource('components/home/HomePortal.tsx');
    const splashTsx = readSource('components/OpeningSplash.tsx');

    expect(app).toContain('brandFont.variable');
    expect(app).toContain('wordmarkFont.variable');
    expect(app).toContain('STUDYHUB_RIBBON_MARK_PATHS');
    expect(app).toContain('STUDYHUB_ZH_LOGOTYPE_PATHS');
    expect(app).toContain('STUDYHUB_WORDMARK_GLYPHS');
    expect(navbar).toContain('<BrandLogo');
    expect(brandFont).toContain('instrument-sans-latin-wght-normal.woff2');
    expect(brandFont).toContain("display: 'block'");

    expect(wordmarkModule).toContain("STUDYHUB_WORDMARK_VIEWBOX = '0 0 844 160'");
    expect(wordmarkModule).toContain("STUDYHUB_WORDMARK_H_COLOR = '#b8b8ba'");
    expect(wordmarkModule).toContain("STUDYHUB_RIBBON_MARK_VIEWBOX = '236 278 572 518'");
    expect(wordmarkModule).toContain("STUDYHUB_ZH_LOGOTYPE_VIEWBOX = '0 0 386 157'");
    expect(wordmarkSvg).toContain('viewBox="0 0 844 160"');
    expect(wordmarkSvg).toContain('fill="#ffffff"');
    expect(wordmarkSvg).toContain('fill="#b8b8ba"');

    expect(footerCss).toContain('brandMarkSvg');
    expect(footerCss).toContain('brandZhSvg');
    expect(footerCss).toContain('brandDivider');
    expect(footerCss).toContain('brandWordmarkSvg');

    expect(portalTsx).toContain('STUDYHUB_WORDMARK_GLYPHS');
    expect(portalTsx).toContain('STUDYHUB_WORDMARK_VIEWBOX');
    expect(portalTsx).not.toContain('<BrandLogo');
    expect(splashTsx).toContain('STUDYHUB_WORDMARK_GLYPHS');
    expect(splashTsx).toContain('STUDYHUB_WORDMARK_VIEWBOX');
    expect(splashTsx).not.toContain('<BrandLogo');

    for (const token of [
      '--wordmark-width: clamp(256px, 31vw, 340px);',
      'padding: 18px 20px 8px;',
      'aspect-ratio: 844 / 160;',
    ]) {
      expect(portalCss).toContain(token);
      expect(splashCss).toContain(token);
    }
  });

  it('keeps the splash slide off the stage so the dock transform still applies', () => {
    const css = readSource('styles/OpeningSplash.module.css');
    const stageRule = css.slice(css.indexOf('.stage {'), css.indexOf('}', css.indexOf('.stage {')));

    expect(stageRule).not.toContain('animation');
    expect(css).toContain('.lockup {');
    expect(css).toContain('splashLetter');
  });
});

describe('opening splash trigger', () => {
  it('plays on every full load of the home page and has no once-per-session gate', () => {
    const splash = readSource('components/OpeningSplash.tsx');

    expect(splash).not.toContain('sessionStorage');
    expect(splash).toContain("window.location.pathname === '/'");
  });
});

// The phone list keeps the minimal card; the desktop list uses the classic card of main.
describe('minimal material cards', () => {
  // Owner choice (2026-11-14): the card of the first design, with no description and no detail card.
  it('shows the facts of the first design on the card, with no description or detail card', () => {
    const minimal = minimalVariantSource();
    const css = readSource('styles/HomeMinimal.module.css');

    expect(minimal).toContain('material-card__overlay-link');
    expect(minimal).toContain('minStyles.cardMeta');
    expect(minimal).toContain('发布者：');
    expect(minimal).toContain('评分：');
    expect(minimal).toContain('minStyles.cardChip');
    expect(minimal).not.toContain('版权');
    expect(minimal).not.toContain('description');
    expect(minimal).not.toContain('cardDetail');
    expect(css).not.toContain('.cardDetail');
    expect(css).not.toContain('.cardDesc');
  });

  it('has no selection checkbox and no batch bar on the home list', () => {
    const library = readSource('components/home/HomeMaterialLibrary.tsx');
    const home = readSource('pages/index.tsx');
    const css = readSource('styles/HomeMinimal.module.css');

    expect(minimalVariantSource()).not.toContain('selectable');
    expect(library).not.toContain('selectable');
    expect(library).not.toContain('批量分享');
    expect(home).not.toContain('handleBatchShare');
    expect(css).not.toContain('.rowCheck');
    expect(css).not.toContain('.batchInline');
  });

  it('lays the cards out three per row at most, and one per row on a phone', () => {
    const css = readSource('styles/HomeMinimal.module.css');
    const list = css.slice(css.indexOf('.minimalList {'), css.indexOf('}', css.indexOf('.minimalList {')));
    const phone = css.slice(css.lastIndexOf('@media (max-width: 640px)'));

    // One third of the row is the smallest column, so a fourth column never fits.
    expect(list).toContain('repeat(auto-fill, minmax(max(220px, calc((100% - 36px) / 3)), 1fr))');
    expect(phone).toContain('.minimalList {\n    grid-template-columns: minmax(0, 1fr);');
  });

  it('makes the card taller than wide, except on a phone', () => {
    const css = readSource('styles/HomeMinimal.module.css');
    const start = css.indexOf('.minimalCard {');
    const card = css.slice(start, css.indexOf('}', start));
    const phone = css.slice(css.lastIndexOf('@media (max-width: 640px)'));

    const ratio = card.match(/aspect-ratio: (\d+) \/ (\d+);/);
    expect(ratio).not.toBeNull();
    expect(Number(ratio![1])).toBeLessThan(Number(ratio![2]));
    expect(card).toContain('align-self: stretch;');
    expect(phone).toContain('.minimalCard {\n    aspect-ratio: auto;');
  });

  it('shows two rows of tags at most', () => {
    const css = readSource('styles/HomeMinimal.module.css');
    const tags = css.slice(css.indexOf('.cardTags {'), css.indexOf('}', css.indexOf('.cardTags {')));

    expect(minimalVariantSource()).toContain('minStyles.cardTag');
    expect(tags).toContain('max-height: 63px;');
    expect(tags).toContain('overflow: hidden;');
  });

  // The global rule outranks a single module class, so the card box must live there.
  it('draws the card box in the global rule that outranks the module class', () => {
    const globals = readSource('styles/globals.css');
    const start = globals.indexOf('.home-page .material-card.minimal-variant {');
    const box = globals.slice(start, globals.indexOf('}', start));

    expect(box).toContain('flex-direction: column;');
    expect(box).toContain('border: 1px solid var(--sh-surface-line);');
    expect(box).toContain('border-radius: 14px;');
    expect(box).toContain('box-shadow: var(--sh-card-shadow);');
    expect(globals).not.toContain('.minimal-variant.selected');
  });

  // Owner feedback (2026-11-14): no coloured letter mark and no avatar on a card. The tags are
  // outlined pills, as on the first design; only the count chips have a grey fill.
  it('has no letter mark and no avatar, and gives no tag or price a fill', () => {
    const minimal = minimalVariantSource();
    const css = readSource('styles/HomeMinimal.module.css');
    const rule = (selector: string) => css.slice(css.indexOf(selector), css.indexOf('}', css.indexOf(selector)));

    expect(minimal).not.toContain('data-tint');
    expect(minimal).not.toContain('cardMark');
    expect(minimal).not.toContain('cardAvatar');
    expect(css).not.toContain('.cardMark');
    expect(css).not.toContain('.cardAvatar');
    expect(css).not.toContain('data-tint');
    expect(rule('.cardTag {')).toContain('border: 1px solid var(--sh-accent-line);');
    expect(rule('.cardTag {')).not.toMatch(/background|box-shadow/);
    for (const selector of ['.cardPrice {', '.cardPriceFree {', '.cardBadge {']) {
      expect(rule(selector)).not.toMatch(/background|border|box-shadow/);
    }
  });

});

// Owner request (2026-11-14): under the first screen the home page shows the classic cards of
// the main branch, one under the other, with no side column.
describe('home content under the first screen', () => {
  it('stacks the material card, the leaderboard card and the support card', () => {
    const home = readSource('pages/index.tsx');
    const content = home.slice(home.indexOf('id="home-content"'));

    expect(home).not.toContain('home-side-column');
    expect(home).not.toContain('home-main-columns');
    expect(home).not.toContain('<aside');
    expect(content.indexOf('<HomeMaterialLibrary')).toBeGreaterThan(-1);
    expect(content.indexOf('<HomeMaterialLibrary')).toBeLessThan(content.indexOf('<HomeLeaderboard'));
    expect(content.indexOf('<HomeLeaderboard')).toBeLessThan(content.indexOf('className="card support-card"'));
  });

  it('draws the material list and the leaderboard in the classic cards', () => {
    const library = readSource('components/home/HomeMaterialLibrary.tsx');
    const leaderboard = readSource('components/home/HomeLeaderboard.tsx');

    expect(library).toContain('className="card materials-library-card"');
    expect(library).toContain('className="materials-list materials-grid"');
    expect(library).toContain('<PaginationBar');
    expect(library).not.toContain('variant="minimal"');
    expect(leaderboard).toContain('card leaderboard-card');
    expect(leaderboard).toContain('className="leaderboard-list"');
  });

  it('keeps no side-column layout rule in the global styles', () => {
    const globals = readSource('styles/globals.css');

    expect(globals).not.toContain('.home-main-columns');
    expect(globals).not.toContain('.home-side-column');
    expect(globals).not.toContain('.home-page .material-sort-control');
    expect(globals).not.toContain('.home-page .pagination-button');
  });
});

describe('home search area', () => {
  it('has a plain white background, with no gradient wash', () => {
    const globals = readSource('styles/globals.css');
    const start = globals.indexOf('.container.page-grid.home-page {');
    const rule = globals.slice(start, globals.indexOf('}', start));
    const groundStart = globals.indexOf('html:has(.home-page),');
    const ground = globals.slice(groundStart, globals.indexOf('}', groundStart));

    // Owner feedback (2026-11-14): the whole page is white, with no grey ground under it.
    expect(ground).toContain('background: #ffffff;');
    expect(globals).not.toContain('--sh-ground');
    expect(rule).toContain('background: #ffffff;');
    expect(rule).not.toContain('gradient');
    expect(globals).not.toContain('--sh-accent-wash');
    expect(globals).not.toContain('--sh-cool-wash');
  });

  it('shows no quick tags above the search box', () => {
    expect(readSource('components/home/HomeFilterCard.tsx')).not.toContain('quickTag');
    expect(readSource('styles/HomeMinimal.module.css')).not.toContain('.quickTag');
    expect(readSource('pages/index.tsx')).not.toContain('onQuickTagSelect');
  });
});

// Owner request (2026-11-14): the first screen is a search portal in the manner of a
// search-engine home page.
describe('home search portal', () => {
  it('sets the vectorized StudyHub wordmark SVG over the search box, as the landing place of the splash', () => {
    const portal = readSource('components/home/HomePortal.tsx');
    const splash = readSource('components/OpeningSplash.tsx');
    const lockup = portal.indexOf('data-splash-target=""');

    expect(lockup).toBeGreaterThan(-1);
    expect(portal).not.toContain('<BrandLogo');
    expect(portal.indexOf('styles.wordmarkSvg', lockup)).toBeLessThan(portal.indexOf('styles.search'));
    expect(splash).toContain('[data-splash-target]');
  });

  it('shows three columns under the search box, five rows in view, with the user count first', () => {
    const portal = readSource('components/home/HomePortal.tsx');

    expect(portal).toContain('export const PORTAL_ROW_COUNT = 5;');
    expect(portal).toContain('count > PORTAL_ROW_COUNT ?');
    for (const title of ['热门资料', '热门学科']) {
      expect(portal).toContain(`>${title}</h2>`);
    }
    expect(portal).toMatch(/<h2 id="portal-overview-title" className=\{styles\.overviewTitle\}>\s*平台概览\s*<\/h2>/);
    expect(portal.indexOf('{stats.users}')).toBeGreaterThan(-1);
    expect(portal.indexOf('{stats.users}')).toBeLessThan(portal.indexOf('{stats.materials}'));
  });

  it('puts the search button in the box, right of the filter trigger', () => {
    const form = readSource('components/home/HomeFilterCard.tsx');
    const pill = form.slice(form.indexOf('data-search-pill=""'), form.indexOf('{showAdvanced ? ('));
    const actions = form.slice(form.indexOf('minStyles.searchActions'));

    expect(pill.indexOf('minStyles.filterTrigger')).toBeGreaterThan(-1);
    expect(pill.indexOf('type="submit"')).toBeGreaterThan(pill.indexOf('minStyles.filterTrigger'));
    expect(actions).not.toContain('type="submit"');
  });

  it('offers a quick-upload dropzone on the left and a prominent upload CTA on the right under the search box', () => {
    const form = readSource('components/home/HomeFilterCard.tsx');
    const actions = form.slice(form.indexOf('minStyles.searchActions'));

    expect(actions).not.toContain('href="/join"');
    expect(actions).not.toContain('关于我们');
    expect(actions).toContain('data-quick-dropzone=""');
    expect(actions).toContain('拖拽资料快捷投稿');
    expect(actions).toContain('href="/upload"');
    expect(actions).toContain('我要投稿');
    expect(actions).toContain('minStyles.searchActionPrimary');
    expect(actions.indexOf('data-quick-dropzone=""')).toBeLessThan(actions.indexOf('我要投稿'));
  });

  it('closes the first screen with a centered scroll cue', () => {
    const portal = readSource('components/home/HomePortal.tsx');
    const strip = portal.slice(portal.indexOf('styles.strip}'));

    expect(strip).toContain('向下滚动');
    expect(strip).toContain('onClick={onScrollDown}');
    expect(portal).not.toContain("document.getElementById('home-content')");
    expect(readSource('pages/index.tsx')).toContain('id="home-content"');
  });

  it('wires the scroll cue to open the content and then glide to it', () => {
    const home = readSource('pages/index.tsx');
    const start = home.indexOf('const scrollToContent = useCallback(');
    const body = home.slice(start, home.indexOf('}, [revealContent]);', start));

    expect(home).toContain('onScrollDown={scrollToContent}');
    expect(body.indexOf("revealContent('rise');")).toBeGreaterThan(-1);
    expect(body.indexOf("revealContent('rise');")).toBeLessThan(body.indexOf('glideToHomeContent();'));
  });

  it('fills the viewport under the navbar on both desktop and phone', () => {
    const css = readSource('styles/HomePortal.module.css');
    const start = css.indexOf('.portal {');
    const rule = css.slice(start, css.indexOf('}', start));
    const phoneStart = css.indexOf('@media (max-width: 768px) {');
    const phoneBlock = css.slice(phoneStart);

    expect(rule).toContain('min-height: calc(100svh - 64px);');
    expect(phoneBlock).toContain('min-height: calc(100svh - 58px - 66px');
    expect(phoneBlock).not.toContain('.portal {\n    display: none;');
  });

  // Owner request (2026-11-14): the header stays; its logo is gone on the home page, because
  // the logo stands over the search box, and the navigation is centred.
  it('hides the navbar brand on the home page and centres the navigation', () => {
    const css = readSource('styles/AnimateHeader.module.css');
    const start = css.indexOf(':global(body:has([data-home-portal])) .brandWrap {');
    const rule = css.slice(start, css.indexOf('}', start));

    expect(start).toBeGreaterThan(-1);
    expect(rule).toContain('display: none;');
    expect(css).toContain(':global(body:has([data-home-portal])) .nav {');
  });

  it('keeps the home header, portal strip and footer aligned to the classic 1180px width', () => {
    for (const file of [
      'styles/AnimateHeader.module.css',
      'styles/SiteFooter.module.css',
      'styles/HomePortal.module.css',
    ]) {
      const source = readSource(file);
      expect(source).not.toContain('1320px');
      expect(source).not.toContain(':global(body:has(.home-page))');
    }

    const portal = readSource('styles/HomePortal.module.css');
    const start = portal.indexOf('.stripInner {');
    const stripInner = portal.slice(start, portal.indexOf('}', start));
    expect(stripInner).toContain('max-width: 1180px;');
  });
});

// Owner request (2026-11-14): StudyHub bot rests left of the search box, some way from it, and
// does not move when the page scrolls.
describe('StudyHub bot default place', () => {
  it('rests left of the search box and ignores the page scroll', () => {
    const bot = readSource('components/FloatingSidebar.tsx');

    expect(bot).toContain("const POS_STORAGE_KEY = 'floating-sidebar-pos-v2';");
    expect(bot).toContain("const HAT_STORAGE_KEY = 'studyhub-bot-hat-v2';");
    expect(bot).toContain('window.localStorage.removeItem(LEGACY_HAT_STORAGE_KEY);');
    expect(bot).toContain("useState<BotHat>('none')");
    expect(bot).toContain('const SEARCH_ANCHOR_GAP = 236;');
    expect(bot).toContain('[data-search-pill]');
    expect(bot).toContain('rect.top + window.scrollY');
    expect(bot).not.toContain("addEventListener('scroll', follow");
    expect(bot).not.toContain('restsInCorner');
  });
});

describe('phone overview stats', () => {
  it('leaves no design switcher on the page', () => {
    const home = readSource('pages/index.tsx');

    expect(home).not.toContain('lookSwitch');
    expect(home).not.toContain('data-card');
    expect(readSource('styles/HomeMinimal.module.css')).not.toContain('TEMP');
  });

  it('keeps the four small tiles in one row on narrow screens', () => {
    const css = readSource('styles/HomeMinimal.module.css');
    const strip = css.slice(css.indexOf('.statsStrip {'), css.indexOf('}', css.indexOf('.statsStrip {')));

    expect(strip).toContain('grid-template-columns: repeat(4,');
    expect(strip).not.toMatch(/background|box-shadow/);
  });

  it('keeps the compact markup of the four tiles on the phone', () => {
    const source = readSource('components/home/MobileHomeSections.tsx');
    const strip = source.slice(source.indexOf('minStyles.statsStrip'), source.indexOf('</dl>'));

    expect(strip).toContain('<dd>{stat.value}</dd>');
    expect(strip).not.toContain('<strong');
    expect(strip).not.toContain('fontSize');
  });

  it('leaves no style of the removed side-column overview', () => {
    const css = readSource('styles/HomeMinimal.module.css');

    for (const selector of ['.statsHero', '.heroSplit', '.heroRows', '.statsSide', '.heroMotif']) {
      expect(css).not.toContain(selector);
    }
  });
});

// Owner request (2026-11-14): the two rank columns hold ten rows and show five; the reader turns
// them like a wheel.
describe('portal wheel lists', () => {
  const portal = () => readSource('components/home/HomePortal.tsx');
  const css = () => readSource('styles/HomePortal.module.css');
  const rule = (selector: string) => {
    const source = css();
    return source.slice(source.indexOf(selector), source.indexOf('}', source.indexOf(selector)));
  };

  it('exports a wheel limit of ten rows, with the visible count still five', () => {
    expect(portal()).toContain('export const PORTAL_WHEEL_LIMIT = 10;');
    expect(portal()).toContain('export const PORTAL_ROW_COUNT = 5;');
    expect(portal()).toContain('popularItems.slice(0, PORTAL_WHEEL_LIMIT)');
    expect(portal()).toContain('subjectRanks.slice(0, PORTAL_WHEEL_LIMIT)');
  });

  it('turns both rank lists into wheels that mark their edge on scroll', () => {
    const source = portal();

    expect(source.match(/className=\{styles\.wheelRows\}/g)).toHaveLength(2);
    expect(source.match(/data-edge=\{wheelEdge\(/g)).toHaveLength(2);
    expect(source.match(/onScroll=\{\(event\) => markWheel\(event\.currentTarget\)\}/g)).toHaveLength(2);
  });

  it('gives the wheel a fixed height that scrolls', () => {
    const wheel = rule('.wheelRows {');

    expect(wheel).toMatch(/height: \d+px;/);
    expect(wheel).toContain('overflow-y: auto;');
  });

  it('snaps the rows to the top of the wheel', () => {
    expect(rule('.wheelRows {')).toContain('scroll-snap-type: y mandatory;');
    expect(rule('.wheelRows .row {')).toContain('scroll-snap-align: start;');
  });
});

describe('portal overview column', () => {
  it('is set apart from the rank columns by a rule at its left', () => {
    const portal = readSource('components/home/HomePortal.tsx');
    const css = readSource('styles/HomePortal.module.css');
    const start = css.indexOf('.overview {');
    const overview = css.slice(start, css.indexOf('}', start));

    expect(portal).toContain('className={`${styles.column} ${styles.overview}`}');
    expect(overview).toContain('border-left:');
  });

  it('shows the user count in the lead, before the four other figures', () => {
    const portal = readSource('components/home/HomePortal.tsx');
    const lead = portal.indexOf('className={styles.overviewLead}');
    const rows = portal.indexOf('<dl className={styles.overviewRows}>');

    expect(lead).toBeGreaterThan(-1);
    expect(portal.indexOf('<strong>{stats.users}</strong>')).toBeGreaterThan(lead);
    expect(portal.indexOf('<strong>{stats.users}</strong>')).toBeLessThan(rows);
    for (const label of ['已上架资料', '免费资料', '累计下载', '收录学科']) {
      expect(portal.indexOf(`<dt>${label}</dt>`)).toBeGreaterThan(rows);
    }
  });
});

// Owner request (2026-11-14): on desktop the content under the first screen stays closed until
// the reader scrolls.
describe('home content hidden until scroll', () => {
  const home = () => readSource('pages/index.tsx');
  const globals = () => {
    const css = readSource('styles/globals.css');
    const start = css.indexOf('.container.page-grid.home-page[data-revealed');
    return css.slice(start, css.indexOf('@keyframes home-content-open'));
  };

  it('marks the main element with its reveal state', () => {
    expect(home()).toContain("data-revealed={contentRevealed ? 'true' : 'false'}");
    expect(home()).toMatch(/<main\s+id="home-content"/);
  });

  it('seeds the state from a module-level flag that survives a return to the page', () => {
    expect(home()).toContain('let homeContentOpened = false;');
    expect(home()).toContain('useState(() => homeContentOpened)');
    expect(home()).toContain('homeContentOpened = true;');
  });

  it('listens to scroll, sets the reveal progress and opens at the reveal distance', () => {
    const source = home();
    const start = source.indexOf("window.addEventListener('scroll', onScroll");

    expect(source).toContain('const HOME_REVEAL_DISTANCE = 280;');
    expect(start).toBeGreaterThan(-1);
    expect(source).toContain('window.scrollY / HOME_REVEAL_DISTANCE');
    expect(source).toContain("setProperty('--home-reveal'");
    expect(source.indexOf("revealContent('rise');", source.indexOf('const onScroll'))).toBeGreaterThan(-1);
    expect(source.indexOf("revealContent('rise');", source.indexOf('const onScroll'))).toBeLessThan(start);
  });

  it('lengthens and cushions the final stretch of the scroll progress curve', () => {
    expect(easeHomeRevealProgress(0)).toBe(0);
    expect(easeHomeRevealProgress(1)).toBe(1);
    expect(easeHomeRevealProgress(0.45)).toBeGreaterThan(0.65);
    expect(easeHomeRevealProgress(0.9)).toBeLessThan(1);
    expect(computeHomeRevealTail(0.5)).toBe(0);
    expect(computeHomeRevealTail(1)).toBe(1);
  });

  it('opens the content before a scroll to the materials', () => {
    const source = home();
    const start = source.indexOf('const scrollToMaterials = useCallback(');
    const body = source.slice(start, source.indexOf('}, [revealContent]);', start));

    expect(body.indexOf('revealContent();')).toBeGreaterThan(-1);
    expect(body.indexOf('revealContent();')).toBeLessThan(body.indexOf('scrollIntoView'));
  });

  it('opens the content before a jump to the leaderboard', () => {
    const source = home();
    const start = source.indexOf('const handleJumpToLeaderboard = useCallback(');
    const body = source.slice(start, source.indexOf('}, [revealContent]);', start));

    expect(body.indexOf('revealContent();')).toBeGreaterThan(-1);
    expect(body.indexOf('revealContent();')).toBeLessThan(body.indexOf('scrollIntoView'));
  });

  it('opens the content before a filter scrolls to the materials', () => {
    const source = home();

    expect(source).toContain("if (options?.scrollTarget === 'materials') revealContent();");
    expect(source.indexOf("if (options?.scrollTarget === 'materials') revealContent();")).toBeLessThan(
      source.indexOf('materialsRef.current?.scrollIntoView({ behavior')
    );
  });

  it('hides the cards of a closed page on desktop and keeps a short run to scroll', () => {
    const css = globals();

    expect(css).toMatch(/\[data-revealed='false'\] \{[^}]*min-height: \d+px;/);
    expect(css).toMatch(/\[data-revealed='false'\] > \* \{\s*display: none;/);
  });

  it('hides the site footer while the content is closed, and marks the footer', () => {
    expect(globals()).toMatch(/\[data-revealed='false'\]\) \[data-site-footer\] \{\s*display: none;/);
    expect(readSource('pages/_app.tsx')).toContain('data-site-footer=""');
  });

  it('raises the cards when the content opens, and stops that for reduced motion', () => {
    const css = readSource('styles/globals.css');
    const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce) {\n  .container.page-grid.home-page[data-revealed'));

    expect(globals()).toMatch(
      /\[data-revealed='true'\]\[data-reveal-motion='rise'\] > \.home-desktop-library[\s\S]*animation: home-content-open /
    );
    expect(css).toContain('@keyframes home-content-open');
    expect(reduced).toMatch(/\[data-revealed='true'\] > \* \{\s*animation: none !important;/);
  });

  it('raises the cards only when a scroll opens the content, not on a jump to a section', () => {
    const source = readSource('pages/index.tsx');
    expect(source).toContain("const revealContent = useCallback((motion: HomeRevealMotion = 'none') => {");
    expect(source).toContain("content?.setAttribute('data-reveal-motion', motion);");
    expect(source).toContain('data-reveal-motion={revealMotion}');
    const start = source.indexOf('const scrollToMaterials = useCallback(');
    const body = source.slice(start, source.indexOf('}, [revealContent]);', start));
    expect(body).toContain('revealContent();');
    expect(body).not.toContain("revealContent('rise')");
    // No rule gives the cards a motion without the 'rise' mark.
    expect(globals()).not.toMatch(/\[data-revealed='true'\] > \.[a-z-]+[^{]*\{\s*animation: home-content-open/);
  });

  it('fills the line on the strip with the reveal progress', () => {
    const css = readSource('styles/HomePortal.module.css');
    const start = css.indexOf('.strip::before {');
    const rule = css.slice(start, css.indexOf('}', start));
    const afterStart = css.indexOf('.strip::after {');
    const afterRule = css.slice(afterStart, css.indexOf('}', afterStart));

    expect(start).toBeGreaterThan(-1);
    expect(afterStart).toBeGreaterThan(start);
    expect(rule).toContain('var(--home-reveal');
    expect(rule).toContain('var(--home-reveal-tail');
    expect(rule).toContain('linear-gradient(');
    expect(rule).toContain('border-radius: 0 999px 999px 0;');
    expect(afterRule).toContain('var(--home-reveal');
    expect(css).toContain('data-home-reveal-complete');
    expect(css).toContain('@keyframes stripCompleteFade');
  });
});

// Owner request (2026-11-15): the splash is a dark intro. A black screen shows a white lockup;
// each part shows as an outline and then fills; at the dock a white surface opens from the centre
// and the lockup lands on the lockup of the home page at scale 1. The whole splash is 2.7 s at most.
describe('opening splash: dark intro and landing', () => {
  const splash = () => readSource('components/OpeningSplash.tsx');
  const css = () => readSource('styles/OpeningSplash.module.css');
  const cssRule = (source: string, selector: string) => {
    const start = source.indexOf(selector);
    expect(start, `missing ${selector}`).toBeGreaterThan(-1);
    return source.slice(start, source.indexOf('}', start));
  };
  const constant = (name: string) => {
    const match = splash().match(new RegExp(`const ${name} = (\\d+);`));
    expect(match, `missing constant ${name}`).not.toBeNull();
    return Number(match![1]);
  };

  it('has one theme, with no light or dark switch', () => {
    const source = splash();

    expect(source).not.toContain('detectTheme');
    expect(source).not.toContain('prefers-color-scheme');
    expect(source).not.toContain('overlayLight');
    expect(source).not.toContain('overlayDark');
  });

  it('is in the server markup of the home page', () => {
    const source = splash();

    expect(source).toContain("const loadsOnHome = useRouter().pathname === '/';");
    expect(source).toContain("useState<SplashPhase>(loadsOnHome ? 'intro' : 'hidden')");
  });

  it('starts the travel on a click and does not cut the splash off', () => {
    const source = splash();

    expect(source).toContain('onClick={skipToDock}');
    expect(source).not.toContain('onClick={finishSplash}');
  });

  it('lands on the home lockup at scale 1, and only when the target is in clear view', () => {
    const source = splash();
    const start = source.indexOf('const computeDock = useCallback');
    const body = source.slice(start, source.indexOf('}, []);', start));
    const hero = body.slice(0, body.indexOf('// Elsewhere'));

    expect(hero).toContain('NAVBAR_HEIGHT');
    expect(hero).toContain('heroRect.top >= minHeroTop');
    expect(hero).toContain('heroRect.bottom <= window.innerHeight');
    expect(hero).toMatch(/scale\(1\)`, onHero: true/);
  });

  it('draws an outline span before a fill span for each letter', () => {
    const source = splash();

    expect(source.indexOf('styles.letterOutline')).toBeGreaterThan(-1);
    expect(source.indexOf('styles.letterOutline')).toBeLessThan(source.indexOf('styles.letterFill'));
  });

  it('takes 2.7 s or less from the start to the end', () => {
    const total = constant('DOCK_DELAY_MS') + constant('DOCK_TRAVEL_MS') + constant('DOCK_SETTLE_MS');

    expect(total).toBeLessThanOrEqual(2700);
  });

  it('keeps the page from scrolling under the splash', () => {
    const source = splash();

    expect(source).toContain("window.addEventListener('wheel', blockScroll, { passive: false });");
    expect(source).toContain("window.addEventListener('touchmove', blockScroll, { passive: false });");
  });

  it('rises a #1a1c20 dark curtain with corner dino over a #ffffff backdrop and docks with spring cushion', () => {
    const source = css();
    const tsx = splash();

    expect(cssRule(source, '.backdrop {')).toContain('background: #ffffff;');
    expect(cssRule(source, '.curtain {')).toContain('background: #1a1c20;');
    expect(cssRule(source, '.stage {')).toContain('mix-blend-mode: difference;');
    expect(cssRule(source, '.overlay {')).toContain('isolation: isolate;');
    expect(tsx).toContain('data-splash-curtain=""');
    expect(tsx).toContain('data-splash-dino=""');
    expect(tsx).toContain('appleSpringEase');
  });

  it('has the same travel time in the stylesheet and in the component', () => {
    const cssTravel = css().match(/--splash-travel: (\d+)ms;/);

    expect(cssTravel).not.toBeNull();
    expect(Number(cssTravel![1])).toBe(constant('DOCK_TRAVEL_MS'));
  });

  it('shows each glyph as a traced SVG outline that fills upward with a specular glint and no BrandLogo', () => {
    const source = css();
    const tsx = splash();
    const outline = cssRule(source, '.letterOutline {');
    const fill = cssRule(source, '.letterFill {');
    const sheen = cssRule(source, '.wordmarkSheen {');

    expect(tsx).not.toContain('<BrandLogo');
    expect(tsx).toContain('styles.horizonBeam');
    expect(tsx).toContain('styles.wordmarkSheen');
    expect(outline).toContain('stroke-dasharray:');
    expect(outline).toContain('stroke-dashoffset:');
    expect(outline).toContain('animation: splashLetterTrace');
    expect(fill).toContain('animation: splashLetterFill');
    expect(sheen).toContain('animation: splashSheenSweep');
    expect(source).toContain('@keyframes splashLetterTrace');
    expect(source).toContain('@keyframes splashLetterFill');
    expect(source).toContain('@keyframes splashSheenSweep');
  });

  it('shows no splash for reduced motion, and removes a splash that no script ended', () => {
    const source = css();
    const reduced = source.slice(source.indexOf('@media (prefers-reduced-motion: reduce)'));

    expect(reduced).toMatch(/\.overlay \{\s*display: none;/);
    expect(cssRule(source, '@keyframes splashFailsafe {')).toContain('visibility: hidden;');
    expect(cssRule(source, '.overlay {')).toContain('animation: splashFailsafe');
  });

  it('hides the home lockup, the search box, the columns and the strip only while the splash plays or docks', () => {
    const portal = readSource('styles/HomePortal.module.css');
    const hiddenRule = (selector: string) => {
      const start = portal.indexOf(`:global(html[data-splash-state='docking']) ${selector} {`);
      expect(start, `no docking rule for ${selector}`).toBeGreaterThan(-1);
      return { start, text: portal.slice(start, portal.indexOf('}', start)) };
    };

    expect(portal).not.toContain(':not([data-splash-state');
    expect(portal).toContain(":global(html[data-splash-state='playing']) .lockup");
    expect(hiddenRule('.lockup').text).toContain('visibility: hidden;');

    // The shared rule hides the three parts in both states.
    const shared = portal.slice(
      portal.indexOf(":global(html[data-splash-state='playing']) .search,"),
      portal.indexOf('}', portal.indexOf(":global(html[data-splash-state='docking']) .strip {"))
    );
    for (const state of ['playing', 'docking']) {
      for (const part of ['search', 'columns', 'strip']) {
        expect(shared).toContain(`:global(html[data-splash-state='${state}']) .${part}`);
      }
    }
    expect(shared).toContain('opacity: 0;');
    // Only the columns move; the search box stays where it is.
    expect(shared).not.toContain('transform');
    const columnsMove = hiddenRule('.columns');
    expect(columnsMove.text).toContain('transform: translate3d(');
  });

  it('hides the navbar links and the right cluster while the splash plays or docks', () => {
    const header = readSource('styles/AnimateHeader.module.css');

    for (const part of ['.rightCluster', '.nav']) {
      const start = header.indexOf(`:global(html[data-splash-state='playing']) ${part},`);
      expect(start, `no rule for ${part}`).toBeGreaterThan(-1);
      const rule = header.slice(start, header.indexOf('}', start));
      expect(rule).toContain(`:global(html[data-splash-state='docking']) ${part} {`);
      expect(rule).toContain('opacity: 0;');
    }
  });

  it('hides the StudyHub bot while the splash plays or docks', () => {
    const globals = readSource('styles/globals.css');
    const start = globals.indexOf("html[data-splash-state='playing'] .floating-sidebar,");
    const rule = globals.slice(start, globals.indexOf('}', start));

    expect(start).toBeGreaterThan(-1);
    expect(rule).toContain("html[data-splash-state='docking'] .floating-sidebar {");
    expect(rule).toContain('opacity: 0;');
  });
});

describe('portal overview column: type and rows', () => {
  const portal = () => readSource('components/home/HomePortal.tsx');
  const css = () => readSource('styles/HomePortal.module.css');
  const rule = (selector: string) => {
    const source = css();
    const start = source.indexOf(selector);
    expect(start, `missing ${selector}`).toBeGreaterThan(-1);
    return source.slice(start, source.indexOf('}', start));
  };

  it('sets the user count and the figures in the Jost variable font with unified editorial weight', () => {
    const leadNum = rule('.overviewLead strong {');
    const rowNum = rule('.overviewRows dd {');

    expect(leadNum).toContain('font-family: var(--font-brand)');
    expect(leadNum).toContain('font-weight: 560;');
    expect(leadNum).toContain('font-variant-numeric: tabular-nums;');
    expect(rowNum).toContain('font-family: var(--font-brand)');
    expect(rowNum).toContain('font-weight: 540;');
    expect(rowNum).toContain('font-variant-numeric: tabular-nums;');
    expect(css()).not.toContain('rotate(18deg)');
  });

  it('aligns all three headers with quiet actions and omits free tags or percentage pills', () => {
    const source = portal();
    const popularCol = source.slice(
      source.indexOf('aria-labelledby="portal-popular-title"'),
      source.indexOf('aria-labelledby="portal-subjects-title"')
    );
    const subjectCol = source.slice(
      source.indexOf('aria-labelledby="portal-subjects-title"'),
      source.indexOf('className={`${styles.column} ${styles.overview}`}')
    );
    const overviewSection = source.slice(
      source.indexOf('className={`${styles.column} ${styles.overview}`}'),
      source.indexOf('<div className={styles.strip}>')
    );

    expect(source).toContain('全部资料');
    expect(source).toContain('全部学科');
    expect(source).toContain('贡献榜');
    expect(popularCol).toContain('↓ {formatNumber(item.downloadCount ?? 0)}');
    expect(popularCol.replace('暂无热门资料', '')).not.toContain('免费');
    expect(subjectCol).toContain('{formatNumber(subject.materialCount)} 份');
    expect(subjectCol).toContain('↓ {formatNumber(subject.downloadCount)}');
    expect(overviewSection).toContain('<div className={styles.columnHead}>');
    expect(overviewSection).not.toContain('免费占比');
    expect(overviewSection).not.toContain('overviewShare');
    expect(overviewSection).not.toContain('overviewMeter');
    expect(overviewSection).not.toContain('overviewTag');
  });

  it('uses unified slate-navy editorial accents, pill row hover, and clean 2x2 overview rows', () => {
    const headAccent = rule('.columnHead::after {');
    const firstRank = rule('.rankFirst {');
    const rowHover = rule('.row:hover {');
    const overviewRule = rule('.overview {');
    const matrixRule = rule('.overviewRows {');
    const cellRule = rule('.overviewRows > div {');

    expect(headAccent).toContain('#24344d');
    expect(firstRank).toContain('#24344d');
    expect(rowHover).toContain('background: #f4f6fa;');
    expect(overviewRule).not.toMatch(/background|box-shadow|border-radius/);
    expect(matrixRule).not.toMatch(/background|box-shadow/);
    expect(matrixRule).toContain('grid-template-columns: repeat(2, minmax(0, 1fr));');
    expect(cellRule).toContain('border-top: 1px solid #f1f3f7;');
    expect(cellRule).toContain('flex-direction: column;');
  });

  it('sizes and separates the three editorial columns cleanly', () => {
    const columnsRule = rule('\n.columns {\n  width:');

    expect(columnsRule).toContain('width: min(100%, 1200px);');
    expect(columnsRule).toContain('grid-template-columns: repeat(3, minmax(0, 1fr));');
    expect(columnsRule).toContain('gap: 0 32px;');
  });
});

// Finding of the final e2e check (2026-11-15): the search portal is hidden at phone width, so
// the phone home page had lost the discovery card and the cooperation card. Owner decision:
// put both back at phone width before the push.
describe('phone home page: discovery and cooperation cards', () => {
  const index = () => readSource('pages/index.tsx');

  it('mounts both cards in phone-only wrappers, the discovery card before the leaderboard', () => {
    const source = index();
    const discovery = source.indexOf('data-home-phone-discovery=""');
    const cooperation = source.indexOf('data-home-phone-cooperation=""');
    const leaderboard = source.indexOf('<HomeLeaderboard');

    expect(discovery).toBeGreaterThan(-1);
    expect(cooperation).toBeGreaterThan(-1);
    expect(discovery).toBeLessThan(leaderboard);
    expect(cooperation).toBeGreaterThan(leaderboard);
    expect(source.slice(discovery - 60, discovery)).toContain('className={minStyles.phoneOnly}');
    expect(source.slice(cooperation - 60, cooperation)).toContain('className={minStyles.phoneOnly}');
    expect(source.slice(discovery, leaderboard)).toContain('<HomeDiscoveryCard');
    expect(source.slice(cooperation, cooperation + 160)).toContain('<HomeCooperationCard');
  });

  it('keeps the phone-only wrappers scoped cleanly for revealed phone content', () => {
    const minimal = readSource('styles/HomeMinimal.module.css');
    const base = minimal.indexOf('\n.phoneOnly {');
    const phone = minimal.indexOf('@media (max-width: 768px) {\n  .phoneOnly {');

    expect(base).toBeGreaterThan(-1);
    expect(minimal.slice(base, minimal.indexOf('}', base))).toContain('display: none;');
    expect(phone).toBeGreaterThan(base);
    expect(minimal.slice(phone, minimal.indexOf('}', phone))).toContain('display: none;');
  });

  it('keeps each list of the discovery card short', () => {
    expect(readSource('components/home/HomeRequestPanels.tsx')).toContain('const SIDEBAR_LIST_LIMIT = 5;');
  });
});

describe('search pill styling, portal spacing, and home UI polish', () => {
  it('upgrades the search pill, increases spacing below it, and shifts advancedPanel accordingly', () => {
    const minimal = readSource('styles/HomeMinimal.module.css');
    const portal = readSource('styles/HomePortal.module.css');
    const getRule = (source: string, selector: string) => {
      const start = source.indexOf(selector);
      expect(start, `missing ${selector}`).toBeGreaterThan(-1);
      return source.slice(start, source.indexOf('}', start));
    };

    const pillRule = getRule(minimal, '\n.searchPill {');
    expect(pillRule).toContain('height: 56px;');
    expect(pillRule).toContain('border: 2px solid #c4ccd9;');
    expect(pillRule).toContain('padding: 0 7px 0 21px;');
    expect(getRule(minimal, '\n.searchActions {')).toContain('margin-top: 30px;');
    expect(getRule(minimal, '\n.advancedPanel {')).toContain('top: 166px;');
    expect(getRule(portal, '\n.search {')).toContain('margin-top: 18px;');
    expect(getRule(portal, '\n.columns {\n  width:')).toContain('margin-top: 44px;');
  });

  it('styles the navbar GitHub star in golden yellow with hover twinkle effects and live visibility refresh', () => {
    const navbar = readSource('components/NavBar.tsx');
    const headerCss = readSource('styles/AnimateHeader.module.css');
    const start = headerCss.indexOf('\n.githubStarIcon {');
    expect(start).toBeGreaterThan(-1);
    const starRule = headerCss.slice(start, headerCss.indexOf('}', start));

    expect(navbar).toContain('githubStarIcon');
    expect(navbar).toContain('visibilitychange');
    expect(navbar).toContain('STARS_CACHE_TTL_MS');
    expect(starRule).toContain('color: #f5a623;');
    expect(headerCss).toContain('@keyframes githubStarTwinkle');
    expect(headerCss).toContain('@keyframes githubSparkleTop');
  });

  it('renders the search submit control as a compact 38px midnight slate-navy 3D glass orb with outer halo', () => {
    const form = readSource('components/home/HomeFilterCard.tsx');
    const minimal = readSource('styles/HomeMinimal.module.css');
    const cssRule = (selector: string) => {
      const start = minimal.indexOf(`\n${selector}`);
      expect(start, `missing ${selector}`).toBeGreaterThan(-1);
      return minimal.slice(start, minimal.indexOf('}', start));
    };
    const goRule = cssRule('.searchGo {');
    const auraRule = cssRule('.searchGoAura {');
    const ringRule = cssRule('.searchGoRing {');
    const glassRule = cssRule('.searchGoGlass {');
    const pill = form.slice(form.indexOf('data-search-pill=""'), form.indexOf('{showAdvanced ? ('));

    expect(pill).toContain('width="21"');
    expect(pill).toContain('type="submit"');
    expect(pill).toContain('aria-label="搜索资料"');
    expect(pill).toContain('searchGoAura');
    expect(pill).toContain('searchGoRing');
    expect(pill).toContain('searchGoSheen');
    expect(pill).toContain('searchGoGlass');
    expect(pill).not.toContain('searchGoCore');
    expect(pill).toContain('searchGoArrowPrimary');
    expect(pill).toContain('searchGoArrowClone');
    expect(pill).not.toContain('<span>搜索</span>');
    expect(goRule).toContain('width: 38px;');
    expect(goRule).toContain('height: 38px;');
    expect(goRule).toContain('border-radius: 50%;');
    expect(goRule).toContain('-webkit-appearance: none;');
    expect(auraRule).toContain('inset: -3.5px;');
    expect(ringRule).toContain('clip-path: circle(50% at 50% 50%);');
    expect(glassRule).toContain('inset: 1.75px;');
    expect(glassRule).toContain('clip-path: circle(50% at 50% 50%);');
    expect(glassRule).toContain('backdrop-filter:');
    expect(minimal).not.toContain('searchGoCore');
    expect(minimal).toContain('conic-gradient(');
    expect(minimal).toContain('#3b5988');
    expect(minimal).toContain('#1e3a5f');
    expect(minimal).toContain('#0f172a');
    expect(minimal).toContain('@keyframes liquidMetalSpin');
  });

  it('renders the global site footer with 6 columns (credits and 硅基工友 with agent logos, without 浏览), contact email, compressed QR cards, bottom-left ICP, and bottom-right team copyright', () => {
    const app = readSource('pages/_app.tsx');
    const footerCss = readSource('styles/SiteFooter.module.css');
    const agentLogoSrc = readSource('components/FooterAgentLogo.tsx');
    const footerMarkup = app.slice(app.indexOf('data-site-footer=""'), app.indexOf('</footer>'));

    expect(footerMarkup).toContain('footerStyles.navGrid');
    expect(footerMarkup).toContain('footerStyles.colItem');
    expect(footerMarkup).toContain('footerStyles.agentItem');
    expect(footerMarkup).toContain('footerStyles.agentLogo');
    expect(footerMarkup).toContain('footerStyles.contactCol');
    expect(footerMarkup).toContain('footerStyles.qrGroup');
    expect(footerMarkup).toContain('footerStyles.qrBox');
    expect(footerMarkup).not.toContain('contribChip');
    expect(footerMarkup).not.toContain('Open Campus');
    expect(footerMarkup).not.toContain('brandBadge');
    expect(footerMarkup).toContain('footerStyles.socialRow');
    expect(footerMarkup).toContain('footerStyles.socialBtn');
    expect(footerMarkup).not.toContain('footerStyles.searchForm');
    expect(footerMarkup.indexOf('核心贡献者')).toBeLessThan(footerMarkup.indexOf('特别鸣谢'));
    expect(footerMarkup.indexOf('特别鸣谢')).toBeLessThan(footerMarkup.indexOf('>社区<'));
    expect(footerMarkup).not.toContain('>浏览<');
    expect(footerMarkup.indexOf('>社区<')).toBeLessThan(footerMarkup.indexOf('>支持<'));
    expect(footerMarkup.indexOf('>支持<')).toBeLessThan(footerMarkup.indexOf('硅基工友'));
    expect(footerMarkup.indexOf('硅基工友')).toBeLessThan(footerMarkup.indexOf('>联系方式<'));
    expect(footerMarkup.indexOf('季文君')).toBeGreaterThan(footerMarkup.indexOf('特别鸣谢'));
    expect(footerMarkup.indexOf('林俊宇')).toBeGreaterThan(footerMarkup.indexOf('季文君'));
    expect(footerMarkup.indexOf('硅基工友')).toBeGreaterThan(footerMarkup.indexOf('隐私与协议'));
    expect(footerMarkup.indexOf('kind="claude"')).toBeGreaterThan(footerMarkup.indexOf('硅基工友'));
    expect(footerMarkup.indexOf('Claude Code')).toBeGreaterThan(footerMarkup.indexOf('kind="claude"'));
    expect(footerMarkup.indexOf('kind="codex"')).toBeGreaterThan(footerMarkup.indexOf('Claude Code'));
    expect(footerMarkup.indexOf('Codex')).toBeGreaterThan(footerMarkup.indexOf('kind="codex"'));
    expect(footerMarkup.indexOf('kind="antigravity"')).toBeGreaterThan(footerMarkup.indexOf('Codex'));
    expect(footerMarkup.indexOf('Antigravity')).toBeGreaterThan(footerMarkup.indexOf('kind="antigravity"'));
    expect(footerMarkup.indexOf('>联系方式<')).toBeGreaterThan(footerMarkup.indexOf('Antigravity'));
    expect(agentLogoSrc).toContain('#D97757');
    expect(agentLogoSrc).toContain('fillRule="evenodd"');
    expect(agentLogoSrc).toContain('sh-ag-clip');
    expect(agentLogoSrc).not.toContain('<img');
    expect(footerMarkup).not.toContain('联系邮箱：');
    expect(footerMarkup).toContain('mailto:chengjinli@std.uestc.edu.cn');
    expect(footerMarkup).toContain('/wechat/qq-group-qr.webp');
    expect(footerMarkup).toContain('官方 QQ 群');
    expect(footerMarkup).toContain('/wechat/wechat-qr.png');
    expect(footerMarkup).toContain('StudyHub 公众号');
    expect(footerMarkup).toContain('loading="lazy"');
    expect(footerMarkup.indexOf('footerStyles.bottomBar')).toBeLessThan(footerMarkup.indexOf('浙ICP备2025212695号'));
    expect(footerMarkup.indexOf('浙ICP备2025212695号')).toBeLessThan(footerMarkup.indexOf('Copyright © 2026 StudyHub开发团队'));
    expect(footerCss).toContain('.contactCol');
    expect(footerCss).toContain('.qrBox');
    expect(footerCss).toContain('.colItem');
    expect(footerCss).toContain('clamp(80px, 8.5vw, 128px)');
    expect(footerCss).toContain('justify-content: space-between;');
    expect(footerCss).not.toContain('.contribChip');
    expect(footerCss).toContain('.socialBtn');
  });

  it('keeps the top-right auth status minimal in neutral black and gray with truncated username beside logout', () => {
    const navbar = readSource('components/NavBar.tsx');
    const headerCss = readSource('styles/AnimateHeader.module.css');
    const app = readSource('pages/_app.tsx');
    const faviconSvg = readSource('public/favicon.svg');
    const authCss = headerCss.slice(
      headerCss.indexOf('\n.authActions {'),
      headerCss.indexOf('@media (max-width: 1080px)')
    );

    expect(navbar).toContain('truncateUserName');
    expect(navbar).toContain('title={displayName}');
    expect(navbar).toContain('styles.userPill');
    expect(navbar).toContain('styles.userName');
    expect(navbar).toContain('styles.logoutButton');
    expect(navbar).toContain('styles.guestPill');
    expect(navbar).toContain('styles.loginButton');
    expect(navbar).not.toContain('userAvatar');
    expect(navbar).not.toContain('guestCapsule');
    expect(authCss).toContain('#18181b');
    expect(authCss).toContain('#f4f4f5');
    expect(authCss).toContain('#e4e4e7');
    expect(authCss).toContain('text-overflow: ellipsis;');
    expect(authCss).not.toContain('animation');
    expect(app).toContain('/favicon.svg?v=3');
    expect(app).toContain('/favicon.png?v=3');
    expect(app).toContain('/favicon.ico?v=3');
    expect(faviconSvg).toContain('fill="#18191c"');
    expect(faviconSvg).toContain('stroke="#ffffff"');
    expect(faviconSvg).toContain('fill="#ffffff"');
    expect(faviconSvg).toContain('M434 278');
  });

  it('lowers the jet-black irregular canopy around search + bot and expands OpeningSplash as a swirling Taiji circle', () => {
    const canopy = readSource('lib/portalCanopy.ts');
    const portal = readSource('components/home/HomePortal.tsx');
    const portalCss = readSource('styles/HomePortal.module.css');
    const minimalCss = readSource('styles/HomeMinimal.module.css');
    const navbar = readSource('components/NavBar.tsx');
    const headerCss = readSource('styles/AnimateHeader.module.css');
    const splash = readSource('components/OpeningSplash.tsx');
    const splashCss = readSource('styles/OpeningSplash.module.css');

    const canopyRule = portalCss.slice(portalCss.indexOf('\n.canopy {'), portalCss.indexOf('\n.canopyUpper {'));
    const canopyWaveRule = portalCss.slice(portalCss.indexOf('\n.canopyWave {'), portalCss.indexOf('\n.canopyRimGlow {'));
    const wordmarkSvgRule = portalCss.slice(portalCss.indexOf('\n.wordmarkSvg {'), portalCss.indexOf('\n.glyphWhite {'));
    const glyphWhiteRule = portalCss.slice(portalCss.indexOf('\n.glyphWhite {'), portalCss.indexOf('\n.glyphSilver {'));
    const glyphSilverRule = portalCss.slice(portalCss.indexOf('\n.glyphSilver {'), portalCss.indexOf('\n/* While the opening splash'));
    const githubNav = navbar.slice(navbar.indexOf('styles.githubNavLink'), navbar.indexOf('</nav>'));

    expect(canopy).toContain('PORTAL_CANOPY_CENTER_Y = 678');
    expect(canopy).toContain("PORTAL_CANOPY_RIM_PATH = 'M 0,678 L 1440,678'");
    expect(canopy).not.toContain(' C ');
    expect(canopy).toContain('PORTAL_CANOPY_RIM_PATH');
    expect(portal).toContain('data-portal-canopy=""');
    expect(portal).toContain('data-portal-canopy-wave=""');
    expect(portal).toContain('fill="#1a1c20"');
    expect(portal).toContain('portal-canopy-rim');
    expect(portalCss).toContain('background: #1a1c20;');
    expect(canopyRule).toContain('bottom: -200px;');
    expect(canopyWaveRule).toContain('height: 736px;');
    expect(wordmarkSvgRule).toContain('aspect-ratio: 844 / 160;');
    expect(glyphWhiteRule).toContain('fill: #ffffff;');
    expect(glyphSilverRule).toContain('fill: #b8b8ba;');
    expect(minimalCss).toContain(':global([data-home-portal]) .searchPill {');
    expect(minimalCss).toContain(':global([data-home-portal]) .searchActions {');

    expect(navbar).toContain('data-scrolled={scrolledPastCanopy');
    expect(navbar).toContain('window.innerWidth <= 768 ? 58 : 64');
    expect(navbar).toContain('rect.bottom <= headerHeight');
    expect(githubNav).not.toContain('StudyHub');
    expect(headerCss).toContain(":global(body:has([data-home-portal])) .header:not([data-scrolled='true']) {");

    expect(splash).toContain('styles.overlayHeroDocking');
    expect(splash).toContain('data-splash-curtain=""');
    expect(splash).toContain('data-splash-dino=""');
    expect(splash).toContain('getDinoViewportLayout');
    expect(splash).toContain('applePopUpEase');
    expect(splash).toContain('appleSpringEase');
    expect(splash).not.toContain('WarpStreak');
    expect(splash).not.toContain('BlastSpark');
    expect(splash).not.toContain('prismGhostCyan');
    expect(splash).not.toContain('taijiCircleRim');
    expect(splashCss).toContain('background: #1a1c20;');
    expect(splashCss).not.toContain('@keyframes splashLockupDetonate');
    expect(splashCss).not.toContain('rotate(-180deg)');
  });

  it('places a static embossed white-porcelain 1st-anniversary seal beside the search actions as a right-side counterweight', () => {
    const portal = readSource('components/home/HomePortal.tsx');
    const portalCss = readSource('styles/HomePortal.module.css');
    const annivSection = portal.slice(
      portal.indexOf('data-portal-anniversary=""') - 120,
      portal.indexOf('className={styles.columns}')
    );

    expect(portal).toContain('className={styles.portalMid}');
    expect(portal).toContain('data-portal-anniversary=""');
    expect(annivSection).toContain('<div');
    expect(annivSection).not.toContain('href="/');
    expect(annivSection).not.toContain('<a');
    expect(annivSection).not.toContain('<Link');
    expect(annivSection).not.toContain('<button');
    expect(annivSection).not.toContain('onClick');
    expect(annivSection).toContain('portal-anniv-arc-top');
    expect(annivSection).toContain('portal-anniv-arc-bot');
    expect(annivSection).toContain('STUDYHUB · ANNIV');
    expect(annivSection).toContain('2025 — 2026');
    expect(annivSection).toContain('1st');
    expect(annivSection).toContain('一周年纪念');
    expect(annivSection).toContain('2025.11 – 2026.11');
    expect(annivSection).not.toContain('1ST ANNIVERSARY');
    expect(annivSection).not.toContain('纪念志');
    const annivSealRule = portalCss.slice(
      portalCss.indexOf('\n.annivSeal {'),
      portalCss.indexOf('\n.annivSealSvg {')
    );

    expect(portalCss).toContain('.portalMid {');
    expect(portalCss).toContain('.annivBadge {');
    expect(portalCss).toContain('.annivSeal {');
    expect(annivSection).toContain('stroke="#d4b36a"');
    expect(annivSealRule).not.toContain('border:');
    expect(annivSealRule).not.toContain('box-shadow:');
    expect(portalCss).toContain('cursor: default;');
    expect(portalCss).toContain('user-select: none;');
    expect(portalCss).not.toContain('.annivBadge:hover');
    expect(portalCss).toContain(":global(html[data-splash-state='playing']) .annivBadge");
    expect(portalCss).toContain(":global(html[data-splash-state='docking']) .annivBadge");
  });

  it('defaults StudyHub Bot eye gaze rightward on initial refresh and when entering the home page', () => {
    const bot = readSource('components/FloatingSidebar.tsx');
    const globals = readSource('styles/globals.css');

    expect(bot).toContain('const EYE_MAX_OFFSET = 5;');
    expect(bot).toContain('const DEFAULT_EYE_OFFSET: EyeOffset = { x: EYE_MAX_OFFSET, y: 0 };');
    expect(bot).toContain('useState<EyeOffset>(DEFAULT_EYE_OFFSET)');
    expect(bot).toContain('isSplashCoveringBot()');
    expect(bot).toContain("router.pathname === '/' && prevPathnameRef.current !== '/'");
    expect(globals).toContain('var(--eye-x, 5px)');
  });

  it('renders the dark-ground white-rimmed favicon and Zhipu-style footer brand lockup ([Mark] 学汇 | StudyHub)', () => {
    const faviconSvg = readSource('public/favicon.svg');
    const wordmarks = readSource('lib/studyhubWordmark.ts');
    const app = readSource('pages/_app.tsx');
    const footerCss = readSource('styles/SiteFooter.module.css');

    expect(faviconSvg).toContain('fill="#18191c" stroke="#ffffff"');
    expect(faviconSvg).toContain('fill="#ffffff"');
    expect(wordmarks).toContain('STUDYHUB_RIBBON_MARK_PATHS');
    expect(wordmarks).toContain('STUDYHUB_ZH_LOGOTYPE_PATHS');
    expect(app).toContain('footerStyles.brandMarkSvg');
    expect(app).toContain('footerStyles.brandZhSvg');
    expect(app).toContain('footerStyles.brandDivider');
    expect(app).toContain('footerStyles.brandWordmarkSvg');
    expect(app).toContain('>学汇<');
    expect(app).toContain('>StudyHub<');
    expect(wordmarks).toContain("STUDYHUB_ZH_LOGOTYPE_VIEWBOX = '0 0 386 157'");
    expect(footerCss).toContain('.brandDivider {');
    expect(footerCss).toContain('aspect-ratio: 386 / 157;');
    const markRule = footerCss.slice(
      footerCss.indexOf('\n.brandMarkSvg {'),
      footerCss.indexOf('}', footerCss.indexOf('\n.brandMarkSvg {'))
    );
    expect(markRule).toContain('height: 20px;');
    const mobile480 = footerCss.slice(footerCss.indexOf('@media (max-width: 480px)'));
    expect(mobile480).toContain('.brandMarkSvg {\n    height: 17px;');
  });

  it('keeps the HomePortal as the first screen on phones and compact displays while closing content below until scroll', () => {
    const portalTsx = readSource('components/home/HomePortal.tsx');
    const portalCss = readSource('styles/HomePortal.module.css');
    const splashCss = readSource('styles/OpeningSplash.module.css');
    const indexTsx = readSource('pages/index.tsx');
    const globalsCss = readSource('styles/globals.css');

    expect(portalTsx).toContain('data-portal-mobile-tabs=""');
    expect(portalCss).toContain('@media (min-width: 769px) and (max-height: 820px)');
    expect(portalCss).toContain('@media (min-width: 769px) and (max-height: 650px)');
    expect(portalCss).toContain('min-height: calc(100svh - 58px - 66px');
    expect(splashCss).not.toContain('.taijiRotor,\n  .taijiCircleRim,\n  .stageCrispWrap {\n    display: none;');
    expect(indexTsx).not.toContain('if (window.innerWidth <= HOME_PHONE_MAX_WIDTH) {\n      if (!contentRevealed) revealContent();');
    expect(globalsCss).toContain('.home-page .home-desktop-library {\n    display: grid;');
    expect(globalsCss).toContain('grid-template-columns: repeat(2, minmax(0, 1fr));');
  });

  it('eliminates splash H dock flicker, mobile splash guide lines, mobile search orb clipping glitches, and keeps mobile overview always visible', () => {
    const splashTsx = readSource('components/OpeningSplash.tsx');
    const splashCss = readSource('styles/OpeningSplash.module.css');
    const portalTsx = readSource('components/home/HomePortal.tsx');
    const portalCss = readSource('styles/HomePortal.module.css');
    const minimalCss = readSource('styles/HomeMinimal.module.css');

    expect(splashTsx).toContain('y={-16}');
    expect(splashTsx).toContain('splash-wordmark-sheen-clip');
    expect(splashTsx).toContain("glyph.tone !== 'silver'");
    expect(splashTsx).toContain("type: 'spring'");

    expect(splashCss).toContain('.overlayHeroDocking .glyphFillSilver {\n  fill: #b8b8ba;\n  transition: fill 280ms ease;\n}');
    expect(splashCss).toContain('.overlayHeroDocking .stage {\n  z-index: 5;\n  mix-blend-mode: normal;');
    expect(splashCss).toContain('transition: fill 240ms ease 180ms;');
    expect(splashCss).not.toContain('48px 48px');
    expect(splashCss).not.toContain('.stageCrisp');
    const splashMobile = splashCss.slice(splashCss.indexOf('@media (max-width: 768px) {'));
    expect(splashMobile).toContain('.horizonBeam,\n  .letterCrest {\n    display: none;\n  }');
    expect(splashMobile).toContain('splashLetterTraceMobile');
    expect(splashMobile).toContain('clip-path: none;');
    expect(splashMobile).toContain('mix-blend-mode: normal;');

    expect(portalTsx).not.toContain('portal-canopy-grid');
    expect(portalTsx).toContain("useState<'materials' | 'subjects'>('materials')");
    const portalOverviewStart = portalTsx.indexOf('aria-labelledby="portal-overview-title"');
    expect(portalTsx.slice(portalOverviewStart - 120, portalOverviewStart + 50)).not.toContain('data-mobile-active');

    const portalMobile = portalCss.slice(portalCss.indexOf('@media (max-width: 768px) {'));
    expect(portalMobile).toContain('height: 368px;');
    expect(portalMobile).toContain('.overview .columnHead {\n    display: flex;');
    expect(portalMobile).toContain('grid-template-columns: minmax(0, 1.28fr) minmax(0, 0.8fr);');
    expect(portalMobile).toContain('grid-column: 2;');
    expect(portalMobile).toContain('grid-row: 1 / span 2;');
    expect(portalMobile).toContain('grid-template-columns: minmax(0, 1.12fr) minmax(0, 0.88fr);');

    const minimalMobile = minimalCss.slice(minimalCss.indexOf('@media (max-width: 768px) {\n  :global([data-home-portal]) .searchPill'));
    expect(minimalMobile).toContain('width: 36px;');
    expect(minimalMobile).toContain('backdrop-filter: none;');
  });

  it('integrates a full Chrome-Dino game left of the search box with auto-pilot and click-edge manual/death mode', () => {
    const portalTsx = readSource('components/home/HomePortal.tsx');
    const portalCss = readSource('styles/HomePortal.module.css');
    const minimalCss = readSource('styles/HomeMinimal.module.css');
    const dinoTsx = readSource('components/home/PortalDinoHorizon.tsx');
    const dinoCss = readSource('styles/PortalDinoHorizon.module.css');
    const dinoSprites = readSource('lib/dinoSprites.ts');
    const splashTsx = readSource('components/OpeningSplash.tsx');

    expect(portalTsx).toContain('<PortalDinoHorizon />');
    expect(dinoTsx).toContain('data-portal-dino-horizon=""');
    expect(dinoTsx).toContain('aria-hidden="true"');
    expect(dinoTsx).toContain("fillStyle = '#ffffff'");
    expect(dinoTsx).toContain('SPRITE_BIRD_A');
    expect(dinoTsx).toContain('SPRITE_DINO_CRASH');
    expect(dinoTsx).toContain('SPRITE_DINO_DUCK_A');
    expect(dinoTsx).toContain('GAME OVER');
    expect(dinoTsx).toContain('prefers-reduced-motion: reduce');
    expect(dinoTsx).toContain('pointerdown');
    expect(dinoTsx).toContain('autoCrashTimer');
    expect(dinoTsx).toContain('idealApexLead');
    expect(dinoSprites).not.toContain('.roundRect(');
    expect(dinoSprites).not.toContain('.ellipse(');

    expect(dinoCss).toContain('pointer-events: none;');
    expect(dinoCss).toContain('bottom: 44px;');
    expect(dinoCss).toContain('bottom: 15px;');
    expect(dinoCss).toContain("html[data-splash-state='playing']");

    expect(portalCss).toContain('bottom: -200px;');
    expect(portalCss).toContain('bottom: -167px;');
    expect(portalCss).toContain('top: 164px;');
    expect(minimalCss).toContain('margin-top: 98px;');
    expect(minimalCss).toContain('top: 194px;');
    expect(splashTsx).toContain('waveHeight - 200');
  });

  it('keeps home canvases and styles compatible with Chrome 97 / Android WebView (no roundRect, ellipse, unguarded :has, or bare svh)', () => {
    const dinoTsx = readSource('components/home/PortalDinoHorizon.tsx');
    const splashTsx = readSource('components/OpeningSplash.tsx');
    const navbarTsx = readSource('components/NavBar.tsx');
    const headerCss = readSource('styles/AnimateHeader.module.css');
    const portalCss = readSource('styles/HomePortal.module.css');

    expect(dinoTsx).not.toContain('.roundRect(');
    expect(dinoTsx).not.toContain('.ellipse(');
    expect(splashTsx).not.toContain('.roundRect(');
    expect(splashTsx).not.toContain('.ellipse(');

    expect(navbarTsx).toContain('data-home-portal-header');
    expect(headerCss).toContain(".header[data-home-portal-header='true']:not([data-scrolled='true']) {");

    expect(portalCss).toContain('padding: clamp(4px, 1.2vh, 12px) 16px 10px;');
    expect(portalCss).toContain('margin-top: clamp(12px, 2vh, 22px);');
    expect(portalCss).toContain('padding-top: clamp(8px, 1.4vh, 14px);');
  });

  it('guarantees jump physics cleanly clear every cactus variant including triple cacti across all viewports', () => {
    const viewports = [
      { w: 1440, h: 900 },
      { w: 1280, h: 760 },
      { w: 1024, h: 600 },
      { w: 390, h: 844 },
      { w: 360, h: 640 },
    ];
    for (const vp of viewports) {
      const layout = getDinoViewportLayout(vp.w, vp.w, vp.h);
      const px = layout.pixelSize;
      for (const spec of CACTUS_VARIANTS) {
        let winningStarts = 0;
        for (let lead = 4; lead <= 110; lead += 2) {
          let obsX = layout.dinoX + 13 * px + lead;
          let dinoY = 0;
          let dinoVy = layout.jumpVy;
          let hit = false;
          const dt = 1 / 60;
          for (let step = 0; step < 90; step += 1) {
            obsX -= layout.baseSpeed * dt;
            dinoY += dinoVy * dt;
            dinoVy += layout.gravity * dt;
            if (dinoY >= 0) {
              dinoY = 0;
              dinoVy = 0;
            }
            const dL = layout.dinoX + 5 * px;
            const dR = layout.dinoX + 13 * px;
            const dB = dinoY - 2 * px;
            const dT = dinoY - 18 * px;
            const oL = obsX + 2 * px;
            const oR = obsX + (spec.w - 2) * px;
            const oT = -(spec.h - 2) * px;
            const oB = 0;
            if (dR > oL && dL < oR && dB > oT && dT < oB) {
              hit = true;
              break;
            }
            if (obsX + spec.w * px < dL) break;
          }
          if (!hit) winningStarts += 1;
        }
        expect(winningStarts, `${vp.w}x${vp.h} ${spec.kind}`).toBeGreaterThanOrEqual(8);
      }
    }
  });

  it('boots the opening-splash dino canvas pre-hydration in _document.tsx so cold uncached loads never miss the dino', () => {
    const docTsx = readSource('pages/_document.tsx');
    const splashTsx = readSource('components/OpeningSplash.tsx');

    expect(docTsx).toContain('__studyhubSplashBoot');
    expect(docTsx).toContain("querySelector('[data-splash-dino]')");
    expect(docTsx).toContain('SPLASH_DINO_BOOT_SCRIPT');
    expect(docTsx).not.toContain('.roundRect(');
    expect(splashTsx).toContain('__studyhubSplashBoot');
    expect(splashTsx).toContain('boot.stop()');
  });

  it('keeps the pixel dino forelimb attached (single connected component) and includes campus & aerial easter eggs', () => {
    const countComponents = (rows: readonly string[]) => {
      const h = rows.length;
      const w = rows[0].length;
      const pts = new Set<string>();
      for (let r = 0; r < h; r += 1) {
        for (let c = 0; c < w; c += 1) {
          if (rows[r][c] === '#' || rows[r][c] === 'o') pts.add(`${r}:${c}`);
        }
      }
      const seen = new Set<string>();
      let components = 0;
      for (const start of Array.from(pts)) {
        if (seen.has(start)) continue;
        components += 1;
        const queue = [start];
        seen.add(start);
        while (queue.length > 0) {
          const cur = queue.shift()!;
          const [r, c] = cur.split(':').map(Number);
          for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
            const k = `${r + dr}:${c + dc}`;
            if (pts.has(k) && !seen.has(k)) {
              seen.add(k);
              queue.push(k);
            }
          }
        }
      }
      return components;
    };

    expect(countComponents([...DINO_UPPER_ROWS, ...DINO_LEGS_BOTH])).toBe(1);
    expect(countComponents([...DINO_DUCK_UPPER, ...DINO_DUCK_LEGS_A])).toBe(1);
    expect(CACTUS_VARIANTS.map((c) => c.kind)).toEqual([
      'small',
      'tall',
      'twin',
      'triple',
      'paper',
      'coffee',
    ]);
    expect(CAMPUS_EXAM_PAPER_ROWS.length).toBe(34);
    for (const row of CAMPUS_EXAM_PAPER_ROWS) {
      expect(row.length).toBe(28);
    }
    expect(CACTUS_VARIANTS[4].frames[0].body.length).toBeGreaterThan(0);
    expect(CACTUS_VARIANTS[4].frames[0].cutouts.length).toBeGreaterThan(0);
    expect((CACTUS_VARIANTS[4].frames[0].accents ?? []).length).toBeGreaterThan(0);
    expect(AIR_VARIANTS).toEqual(['bird', 'paper_plane', 'ufo']);
  });

  it('supports Dino game focus mode clearing surrounding portal chrome and header/bot distractions', () => {
    const dinoTsx = readSource('components/home/PortalDinoHorizon.tsx');
    const portalCss = readSource('styles/HomePortal.module.css');
    const headerCss = readSource('styles/AnimateHeader.module.css');
    const globalsCss = readSource('styles/globals.css');

    expect(dinoTsx).toContain('data-dino-focus-toggle=""');
    expect(dinoTsx).toContain('退出全屏');
    expect(dinoTsx).toContain('空格 / ↑ / W / 点击屏幕跳跃');
    expect(dinoTsx).toContain('dataset.dinoFocus');
    expect(dinoTsx).toContain("event.key === 'Escape'");
    expect(dinoTsx).toContain("event.key === 'f'");
    const dinoCss = readSource('styles/PortalDinoHorizon.module.css');

    expect(dinoTsx).toContain('data-dino-duck-pad=""');
    expect(dinoTsx).toContain('data-dino-jump-pad=""');
    expect(dinoTsx).toContain('styles.mobilePadGlyph');
    expect(dinoTsx).toContain('styles.mobilePadSvg');
    expect(dinoTsx).toContain('styles.mobilePadCopy');
    expect(dinoTsx).toContain('再来一局');
    expect(dinoTsx).not.toMatch(/mobileControlPad[\s\S]*?>\s*[↓↑]\s*</);
    expect(dinoCss).toContain('touch-action: none;');
    expect(dinoCss).toContain(".mobileControlPadPrimary[data-active='true']");
    expect(dinoCss).toContain('translate3d(0, 3px, 0)');
    expect(dinoCss).toContain('position: fixed;');
    expect(dinoCss).toContain('dinoDeckPopIn');
    expect(dinoTsx).toContain('dataset.dinoManual');
    expect(dinoTsx).toContain("mode === 'manual' && bodyHost");
    expect(portalCss).toContain("data-dino-focus='true'");
    expect(portalCss).toContain('position: fixed;');
    expect(headerCss).toContain("data-dino-focus='true'");
    expect(globalsCss).toContain("data-dino-focus='true'");
    expect(globalsCss).toContain("html[data-dino-manual='true'] .mobile-bottom-nav");
    expect(globalsCss).toContain('position: fixed !important;');
  });

  it('hides the StudyHub Bot on mobile viewports (<= 768px)', () => {
    const bot = readSource('components/FloatingSidebar.tsx');
    const globalsCss = readSource('styles/globals.css');

    expect(bot).toContain('window.innerWidth <= 768');
    expect(bot).toContain('if (hideOnMobile) return null;');
    expect(globalsCss).toContain('display: none !important;');
    expect(globalsCss).toContain('.floating-sidebar *');
  });

  it('applies natural Apple inertial overshoot to portal columns, advanced filter popover, and left-to-right staggered nav buttons', () => {
    const portalCss = readSource('styles/HomePortal.module.css');
    const filterTsx = readSource('components/home/HomeFilterCard.tsx');
    const headerCss = readSource('styles/AnimateHeader.module.css');

    expect(portalCss).toContain('cubic-bezier(0.18, 1.24, 0.32, 1)');
    expect(portalCss).not.toContain('@keyframes portalColumnSpring');
    expect(filterTsx).toContain('stiffness: 360');
    expect(filterTsx).toContain('damping: 25');
    expect(headerCss).toContain('cubic-bezier(0.18, 1.24, 0.32, 1)');
    expect(headerCss).not.toContain('@keyframes navButtonApplePop');
    expect(headerCss).toContain('transition-delay: 335ms');
  });

  it('renders a centered single-card login page without the left introductory card', () => {
    const loginTsx = readSource('pages/login.tsx');
    const globalsCss = readSource('styles/globals.css');
    const botTsx = readSource('components/FloatingSidebar.tsx');

    expect(loginTsx).not.toContain('login-aside');
    expect(loginTsx).not.toContain('让知识流动起来');
    expect(loginTsx).toContain('<h1>{mode === \'login\' ? \'欢迎回来\' : \'创建新账号\'}</h1>');
    expect(globalsCss).toContain('max-width: 600px;');
    expect(globalsCss).not.toContain('repeat(2, 540px)');
    expect(botTsx).not.toContain("router.pathname === '/login'");
    expect(botTsx).toContain('.login-card__header');
  });
  it('stages dropped quick-upload files across navigation and balances Dino ducking obstacles cleanly', () => {
    clearQuickUploadFiles();
    const fakeFiles = [{ name: '高数期末复习.pdf' } as File, { name: '答案解析.pdf' } as File];
    expect(stageQuickUploadFiles(fakeFiles).map((f) => f.name)).toEqual([
      '高数期末复习.pdf',
      '答案解析.pdf',
    ]);
    expect(peekQuickUploadFiles().map((f) => f.name)).toEqual([
      '高数期末复习.pdf',
      '答案解析.pdf',
    ]);
    expect(consumeQuickUploadFiles().map((f) => f.name)).toEqual([
      '高数期末复习.pdf',
      '答案解析.pdf',
    ]);
    expect(peekQuickUploadFiles()).toEqual([]);

    const uploadTsx = readSource('pages/upload.tsx');
    expect(uploadTsx).toContain('consumeQuickUploadFiles');
    expect(uploadTsx).toContain("router.query.quick === '1'");

    const dinoTsx = readSource('components/home/PortalDinoHorizon.tsx');
    expect(dinoTsx).toContain('manualScore >= 6');
    expect(dinoTsx).toContain('consecutiveAirCount < 2');
    expect(dinoTsx).toContain('DUCK_DOMINANT_AIR_HEIGHTS');
  });
});
