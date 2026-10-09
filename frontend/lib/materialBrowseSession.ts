import type { MaterialListItem, PaginationMeta } from '../types/material';
import type { MaterialBrowseMode } from './useMaterialSubjects';
import type { SessionUser } from '../types/user';

export interface MaterialBrowseState {
  filters: Record<string, string>;
  appliedFilters?: Record<string, string>;
  materials: MaterialListItem[];
  meta: PaginationMeta;
  availableTags: string[];
  mode: MaterialBrowseMode;
  subjectId: string | null;
  subjectPage: number;
  selectedIds?: number[];
  showAdvanced?: boolean;
}

export interface MaterialBrowseSnapshot {
  version: 1;
  savedAt: number;
  scope: string;
  source: '/' | '/materials';
  url: string;
  detailPath: string;
  historyIndex: number | null;
  pendingRestore: boolean;
  scrollY: number;
  anchor: { id: number; top: number; region?: 'home-library' | 'library' | 'recommended' | 'latest' } | null;
  state: MaterialBrowseState;
}

export const MATERIAL_BROWSE_SESSION_KEY = 'studyhub:material-browse:v1';

export const materialBrowseScope = (user: SessionUser | null) => user ? `${user.id}:${user.roleMask}` : 'anonymous';

export function validateBrowseSnapshot(value: unknown, scope: string, now = Date.now()): MaterialBrowseSnapshot | null {
  const snapshot = value as Partial<MaterialBrowseSnapshot> | null;
  if (!snapshot || snapshot.version !== 1 || snapshot.scope !== scope || !snapshot.pendingRestore) return null;
  if (typeof snapshot.savedAt !== 'number' || now - snapshot.savedAt > 30 * 60 * 1000 || snapshot.savedAt > now) return null;
  if (snapshot.source !== '/' && snapshot.source !== '/materials') return null;
  if (typeof snapshot.url !== 'string' || snapshot.url.split(/[?#]/)[0] !== snapshot.source) return null;
  if (typeof snapshot.detailPath !== 'string' || !/^\/materials\/\d+(?:[-_][^/?#]*)?$/.test(snapshot.detailPath)) return null;
  if (!Number.isFinite(snapshot.scrollY) || snapshot.scrollY! < 0) return null;
  const state = snapshot.state;
  if (!state || !Array.isArray(state.materials) || !Array.isArray(state.availableTags) || !state.meta || !state.filters) return null;
  if (Object.values(state.filters).some((value) => typeof value !== 'string')) return null;
  if (state.mode !== 'materials' && state.mode !== 'subjects') return null;
  if (state.subjectId !== null && typeof state.subjectId !== 'string') return null;
  if (!Number.isInteger(state.subjectPage) || state.subjectPage < 1) return null;
  if (snapshot.anchor && (!Number.isInteger(snapshot.anchor.id) || !Number.isFinite(snapshot.anchor.top))) return null;
  if (snapshot.anchor?.region && !['home-library', 'library', 'recommended', 'latest'].includes(snapshot.anchor.region)) return null;
  return snapshot as MaterialBrowseSnapshot;
}

export function readBrowseSnapshot(storage: Pick<Storage, 'getItem'>, scope: string): MaterialBrowseSnapshot | null {
  try {
    const raw = storage.getItem(MATERIAL_BROWSE_SESSION_KEY);
    return raw ? validateBrowseSnapshot(JSON.parse(raw), scope) : null;
  } catch {
    return null;
  }
}

export function writeBrowseSnapshot(storage: Pick<Storage, 'setItem'>, snapshot: MaterialBrowseSnapshot): void {
  try {
    storage.setItem(MATERIAL_BROWSE_SESSION_KEY, JSON.stringify(snapshot));
  } catch {
    // The in-memory copy still works if sessionStorage is unavailable or full.
  }
}
