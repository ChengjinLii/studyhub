const DEFAULT_BASE_URL = 'http://127.0.0.1:3300';
const DEFAULT_PATHS = ['/', '/materials', '/requests', '/more', '/upload', '/column', '/market', '/join', '/login'];

const baseUrl = process.env.STUDYHUB_PREWARM_BASE_URL || DEFAULT_BASE_URL;
const paths = (process.env.STUDYHUB_PREWARM_PATHS || DEFAULT_PATHS.join(','))
  .split(',')
  .map((path) => path.trim())
  .filter(Boolean);
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

const prewarmPath = async (path) => {
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
  } catch (error) {
    console.warn(`[prewarm] ${path} failed: ${error instanceof Error ? error.message : String(error)}`);
  }
};

const main = async () => {
  const ready = await waitForServer();
  if (!ready) {
    return;
  }
  for (const path of paths) {
    await prewarmPath(path);
  }
};

main().catch((error) => {
  console.warn(`[prewarm] failed: ${error instanceof Error ? error.message : String(error)}`);
});
