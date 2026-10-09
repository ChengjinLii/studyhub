import { useEffect, useRef } from 'react';
import { useRouter } from 'next/router';
import { MaterialBrowseSnapshot, MaterialBrowseState, readBrowseSnapshot, validateBrowseSnapshot, writeBrowseSnapshot } from './materialBrowseSession';

const REGIONS = {
  'home-library': '#materials-list',
  library: '.mobile-library-list',
  recommended: '[aria-label="移动端为你推荐"]',
  latest: '[aria-label="移动端最新资料"]',
} as const;

// Only the homepage uses this cache; no global provider or detail-page changes are needed.
const cache: { current: MaterialBrowseSnapshot | null } = { current: null };

function visibleMaterialCard(id: number, region?: keyof typeof REGIONS): Element | undefined {
  const prefix = region ? `${REGIONS[region]} ` : '';
  return Array.from(document.querySelectorAll(`${prefix}[data-material-id="${id}"]`)).find((card) => {
    const bounds = card.getBoundingClientRect();
    return bounds.width > 0 && bounds.height > 0;
  });
}

function restoreBrowseScroll(snapshot: MaterialBrowseSnapshot) {
  let frame = 0;
  let stopped = false;
  const started = performance.now();
  const root = document.documentElement;
  const previousScrollBehavior = root.style.scrollBehavior;
  root.style.scrollBehavior = 'auto';
  const stop = () => {
    if (stopped) return;
    stopped = true;
    cancelAnimationFrame(frame);
    root.style.scrollBehavior = previousScrollBehavior;
    window.removeEventListener('wheel', stop);
    window.removeEventListener('touchstart', stop);
    window.removeEventListener('pointerdown', stop);
    window.removeEventListener('keydown', stop);
  };
  const restore = () => {
    if (stopped) return;
    const card = snapshot.anchor ? visibleMaterialCard(snapshot.anchor.id, snapshot.anchor.region) : null;
    const top = card && snapshot.anchor ? window.scrollY + card.getBoundingClientRect().top - snapshot.anchor.top : snapshot.scrollY;
    window.scrollTo({ top, left: 0, behavior: 'auto' });
    // Dynamic home sections can mount after the first paint; keep the card anchored briefly.
    if (performance.now() - started < 1200) frame = requestAnimationFrame(restore);
    else stop();
  };
  ['wheel', 'touchstart', 'pointerdown', 'keydown'].forEach((event) => window.addEventListener(event, stop, { passive: true }));
  frame = requestAnimationFrame(restore);
  return stop;
}

export function useMaterialBrowseReturn({ source, scope, state, onRestore }: {
  source: '/' | '/materials';
  scope: string;
  state: MaterialBrowseState;
  onRestore: (state: MaterialBrowseState) => void;
}) {
  const router = useRouter();
  const latest = useRef({ state, onRestore });
  latest.current = { state, onRestore };

  useEffect(() => {
    const snapshot = validateBrowseSnapshot(cache.current, scope) || readBrowseSnapshot(window.sessionStorage, scope);
    let stopScroll: (() => void) | undefined;
    if (snapshot && snapshot.source === source && snapshot.url === router.asPath) {
      latest.current.onRestore(snapshot.state);
      cache.current = { ...snapshot, pendingRestore: false };
      writeBrowseSnapshot(window.sessionStorage, cache.current);
      stopScroll = restoreBrowseScroll(snapshot);
    }
    let clickedCard: Element | null = null;
    const recordClickedCard = (event: MouseEvent) => {
      clickedCard = event.target instanceof Element ? event.target.closest('[data-material-id]') : null;
    };
    const saveBeforeDetail = (url: string) => {
      const detailPath = url.split(/[?#]/)[0];
      const idMatch = detailPath.match(/^\/materials\/(\d+)(?:[-_][^/?#]*)?$/);
      if (!idMatch) return;
      const id = Number(idMatch[1]);
      const card = clickedCard?.getAttribute('data-material-id') === String(id) ? clickedCard : visibleMaterialCard(id);
      const region = card ? (Object.keys(REGIONS) as Array<keyof typeof REGIONS>).find((key) => card.closest(REGIONS[key])) : undefined;
      const next: MaterialBrowseSnapshot = {
        version: 1,
        savedAt: Date.now(),
        scope,
        source,
        url: router.asPath,
        detailPath,
        historyIndex: typeof window.history.state?.idx === 'number' ? window.history.state.idx : null,
        pendingRestore: true,
        scrollY: window.scrollY,
        anchor: card ? { id, top: card.getBoundingClientRect().top, ...(region ? { region } : {}) } : null,
        state: latest.current.state,
      };
      cache.current = next;
      writeBrowseSnapshot(window.sessionStorage, next);
    };
    document.addEventListener('click', recordClickedCard, true);
    router.events.on('routeChangeStart', saveBeforeDetail);
    return () => {
      stopScroll?.();
      document.removeEventListener('click', recordClickedCard, true);
      router.events.off('routeChangeStart', saveBeforeDetail);
    };
    // Restore only when the page mounts, not when its shallow filter URL changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, scope, cache, router.events]);
}
