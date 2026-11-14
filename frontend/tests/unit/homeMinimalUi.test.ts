import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const readSource = (relativePath: string) =>
  readFileSync(join(process.cwd(), relativePath), 'utf8');

const minimalVariantSource = () => {
  const card = readSource('components/MaterialCard.tsx');
  return card.slice(card.indexOf("if (variant === 'minimal')"), card.indexOf("if (variant === 'list')"));
};

describe('brand wordmark', () => {
  it('shows only "StudyHub" in the splash, the navbar and the footer brand', () => {
    const splash = readSource('components/OpeningSplash.tsx');
    const navbar = readSource('components/NavBar.tsx');
    const app = readSource('pages/_app.tsx');
    const footerBrand = app.slice(app.indexOf('footerStyles.brandRow'), app.indexOf('footerStyles.brandDesc'));

    expect(splash).not.toContain('学汇');
    expect(navbar).not.toContain('学汇');
    expect(footerBrand).toContain('StudyHub');
    expect(footerBrand).not.toContain('学汇');
  });

  // Owner request (2026-11-14): the wordmark stands large over the search box, so it has its
  // own face (Outfit); Jost stays for the numerals.
  it('sets the wordmark in the wordmark font in all four places', () => {
    for (const file of [
      'styles/OpeningSplash.module.css',
      'styles/AnimateHeader.module.css',
      'styles/SiteFooter.module.css',
      'styles/HomePortal.module.css',
    ]) {
      expect(readSource(file)).toContain('font-family: var(--font-wordmark), var(--font-stack);');
    }
    const app = readSource('pages/_app.tsx');
    expect(app).toContain('brandFont.variable');
    expect(app).toContain('wordmarkFont.variable');
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
  it('sets the logo and the wordmark over the search box, as the landing place of the splash', () => {
    const portal = readSource('components/home/HomePortal.tsx');
    const splash = readSource('components/OpeningSplash.tsx');
    const lockup = portal.indexOf('data-splash-target=""');

    expect(lockup).toBeGreaterThan(-1);
    expect(portal.indexOf('<BrandLogo', lockup)).toBeLessThan(portal.indexOf('styles.search'));
    expect(portal.indexOf('styles.wordmark', lockup)).toBeLessThan(portal.indexOf('styles.search'));
    expect(splash).toContain('[data-splash-target]');
  });

  it('shows three columns under the search box, five rows in view, with the user count first', () => {
    const portal = readSource('components/home/HomePortal.tsx');

    expect(portal).toContain('export const PORTAL_ROW_COUNT = 5;');
    expect(portal).toContain('count > PORTAL_ROW_COUNT ?');
    for (const title of ['近期热门', '热门学科']) {
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

  it('offers the about page and the upload page under the search box', () => {
    const form = readSource('components/home/HomeFilterCard.tsx');
    const actions = form.slice(form.indexOf('minStyles.searchActions'));

    expect(actions).toContain('href="/join"');
    expect(actions).toContain('关于我们');
    expect(actions).toContain('href="/upload"');
    expect(actions).toContain('我要投稿');
    expect(actions.indexOf('关于我们')).toBeLessThan(actions.indexOf('我要投稿'));
  });

  it('closes the first screen with the QQ group, the contributors, the ICP record and a scroll cue', () => {
    const portal = readSource('components/home/HomePortal.tsx');
    const strip = portal.slice(portal.indexOf('styles.strip}'));

    expect(strip).toContain('官方 QQ 群：');
    expect(strip).toContain('核心贡献者：');
    expect(strip).toContain('浙ICP备2025212695号');
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

  it('fills the viewport under the navbar, and leaves the phone to its own layout', () => {
    const css = readSource('styles/HomePortal.module.css');
    const start = css.indexOf('.portal {');
    const rule = css.slice(start, css.indexOf('}', start));

    expect(rule).toContain('min-height: calc(100svh - 64px);');
    expect(css.slice(css.lastIndexOf('@media (max-width: 768px)'))).toContain('.portal {\n    display: none;');
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
});

// Owner request (2026-11-14): StudyHub bot rests left of the search box, some way from it, and
// does not move when the page scrolls.
describe('StudyHub bot default place', () => {
  it('rests left of the search box and ignores the page scroll', () => {
    const bot = readSource('components/FloatingSidebar.tsx');

    expect(bot).toContain("const POS_STORAGE_KEY = 'floating-sidebar-pos-v2';");
    expect(bot).toContain('const SEARCH_ANCHOR_GAP = 56;');
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
    const start = css.indexOf('@media (min-width: 769px) {\n  .container.page-grid.home-page[data-revealed');
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

    expect(source).toContain('const HOME_REVEAL_DISTANCE = 120;');
    expect(start).toBeGreaterThan(-1);
    expect(source).toContain('window.scrollY / HOME_REVEAL_DISTANCE');
    expect(source).toContain("setProperty('--home-reveal'");
    expect(source.indexOf("revealContent('rise');", source.indexOf('const onScroll'))).toBeGreaterThan(-1);
    expect(source.indexOf("revealContent('rise');", source.indexOf('const onScroll'))).toBeLessThan(start);
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

    expect(start).toBeGreaterThan(-1);
    expect(rule).toContain('var(--home-reveal');
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

    expect(hero).toContain('heroRect.top >= NAVBAR_HEIGHT');
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

  it('opens a white surface over a black backdrop and blends the lockup by difference', () => {
    const source = css();

    expect(cssRule(source, '.backdrop {')).toContain('background: #09090b;');
    expect(cssRule(source, '.wipe {')).toContain('background: #ffffff;');
    expect(cssRule(source, '.wipe {')).toContain('clip-path: circle(');
    expect(cssRule(source, '.overlayDocking .wipe {')).toMatch(/clip-path: circle\(\d+vmax at 50% 50%\);/);
    expect(cssRule(source, '.stage {')).toContain('mix-blend-mode: difference;');
    expect(cssRule(source, '.overlay {')).toContain('isolation: isolate;');
  });

  it('has the same travel time in the stylesheet and in the component', () => {
    const cssTravel = css().match(/--splash-travel: (\d+)ms;/);

    expect(cssTravel).not.toBeNull();
    expect(Number(cssTravel![1])).toBe(constant('DOCK_TRAVEL_MS'));
  });

  it('shows each letter as an outline that fills from its foot, and inverts the ink logo', () => {
    const source = css();
    const outline = cssRule(source, '.letterOutline {');

    expect(outline).toContain('-webkit-text-stroke:');
    expect(outline).toContain('color: transparent;');
    expect(cssRule(source, '.letterFill {')).toContain('clip-path: inset(');
    expect(source).toContain('@keyframes splashLetterFill');
    expect(cssRule(source, '.logoImg {')).toContain('filter: invert(1);');
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
  const css = () => readSource('styles/HomePortal.module.css');
  const rule = (selector: string) => {
    const source = css();
    const start = source.indexOf(selector);
    expect(start, `missing ${selector}`).toBeGreaterThan(-1);
    return source.slice(start, source.indexOf('}', start));
  };

  it('sets the user count and the figures in the wordmark font', () => {
    expect(rule('.overviewLead strong {')).toContain('font-family: var(--font-wordmark)');
    expect(rule('.overviewRows dd {')).toContain('font-family: var(--font-wordmark)');
  });

  it('gives each index row the height of a rank row, with a dotted leader', () => {
    expect(rule('.overviewRows > div {')).toContain('height: 34px;');
    expect(rule('\n.row {')).toContain('height: 34px;');
    expect(rule('.overviewRows > div::before {')).toContain('border-bottom: 1px dotted');
  });
});
