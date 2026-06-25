const DEFAULT_BASE_URL = 'http://127.0.0.1:3300';
const DEFAULT_PATHS = ['/', '/materials', '/requests', '/more', '/upload', '/column', '/market', '/join', '/login'];

const baseUrl = process.env.STUDYHUB_PREWARM_BASE_URL || DEFAULT_BASE_URL;
const paths = (process.env.STUDYHUB_PREWARM_PATHS || DEFAULT_PATHS.join(','))
  .split(',')
  .map((path) => path.trim())
  .filter(Boolean);
const detailLinkLimit = Math.max(0, Number.parseInt(process.env.STUDYHUB_PREWARM_DETAIL_LINK_LIMIT || '8', 10) || 0);
const maxAttempts = Math.max(1, Number.parseInt(process.env.STUDYHUB_PREWARM_ATTEMPTS || '12', 10) || 12);
const retryDelayMs = Math.max(100, Number.parseInt(process.env.STUDYHUB_PREWARM_RETRY_DELAY_MS || '1000', 10) || 1000);
const requestTimeoutMs = Math.max(500, Number.parseInt(process.env.STUDYHUB_PREWARM_TIMEOUT_MS || '2500', 10) || 2500);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const buildUrl = (path) => new URL(path, baseUrl).toString();

const fetchWithTimeout = async (url) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    const response = await fetch(url, {
      headers: {
        Accept: 'text/html,application/xhtml+xml',
        'User-Agent': 'studyhub-prewarm/1.0',
      },
      signal: controller.signal,
    });
    return response;
  } finally {
    clearTimeout(timeout);
  }
};

const waitForServer = async () => {
  const url = buildUrl('/');
  let lastError = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetchWithTimeout(url);
      if (response.ok) {
        return true;
      }
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await sleep(retryDelayMs);
  }
  console.warn(`[prewarm] server was not ready: ${lastError instanceof Error ? lastError.message : String(lastError)}`);
  return false;
};

const normalizeInternalPath = (href) => {
  if (!href || href.startsWith('#') || href.startsWith('javascript:')) {
    return null;
  }
  try {
    const parsed = new URL(href, baseUrl);
    const base = new URL(baseUrl);
    if (parsed.origin !== base.origin) {
      return null;
    }
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return null;
  }
};

const extractDetailLinks = (html) => {
  const links = new Set();
  const pattern = /href=["']([^"']+)["']/g;
  let match = pattern.exec(html);
  while (match && links.size < detailLinkLimit) {
    const path = normalizeInternalPath(match[1]);
    if (path && (/^\/materials\/\d+-.+/.test(path) || /^\/market\/\d+-.+/.test(path))) {
      links.add(path);
    }
    match = pattern.exec(html);
  }
  const pathLikeHtml = html
    .replace(/\\u0026/g, '&')
    .replace(/%2F/gi, '/')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'");
  const pathPattern = /\/(?:materials|market)\/\d+-[^"'<>\s\\]+/g;
  match = pathPattern.exec(pathLikeHtml);
  while (match && links.size < detailLinkLimit) {
    const path = normalizeInternalPath(match[0]);
    if (path) {
      links.add(path);
    }
    match = pathPattern.exec(pathLikeHtml);
  }
  return Array.from(links);
};

const prewarmPath = async (path, options = {}) => {
  const url = buildUrl(path);
  const startedAt = Date.now();
  try {
    const response = await fetchWithTimeout(url);
    const elapsedMs = Date.now() - startedAt;
    if (!response.ok) {
      console.warn(`[prewarm] ${path} returned HTTP ${response.status} in ${elapsedMs}ms`);
      return;
    }
    console.log(`[prewarm] ${path} ${elapsedMs}ms`);
    if (options.readBody) {
      return await response.text();
    }
  } catch (error) {
    console.warn(`[prewarm] ${path} failed: ${error instanceof Error ? error.message : String(error)}`);
  }
  return '';
};

const main = async () => {
  const ready = await waitForServer();
  if (!ready) {
    return;
  }
  const discoveredDetailLinks = new Set();
  for (const path of paths) {
    const shouldReadLinks = detailLinkLimit > 0 && (path === '/materials' || path === '/market');
    const html = await prewarmPath(path, { readBody: shouldReadLinks });
    if (shouldReadLinks && html) {
      extractDetailLinks(html).forEach((link) => discoveredDetailLinks.add(link));
    }
  }
  for (const path of discoveredDetailLinks) {
    await prewarmPath(path);
  }
};

main().catch((error) => {
  console.warn(`[prewarm] failed: ${error instanceof Error ? error.message : String(error)}`);
});
