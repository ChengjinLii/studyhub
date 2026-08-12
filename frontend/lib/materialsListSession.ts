import { MobileMaterialFilterState } from '../components/mobile/MobileFilterDrawer';
import { MaterialListItem, PaginationMeta } from '../types/material';

export type MaterialsMobileView = 'compact' | 'detail';

export interface MaterialsListSessionSnapshot {
  version: 1;
  savedAt: number;
  pendingRestore: boolean;
  filters: MobileMaterialFilterState;
  materials: MaterialListItem[];
  meta: PaginationMeta;
  availableTags: string[];
  mobileView: MaterialsMobileView;
  scrollY: number;
}

export const MATERIALS_LIST_SESSION_KEY = 'studyhub:materials-list:v1';
const MAX_SNAPSHOT_AGE_MS = 30 * 60 * 1000;

export const writeMaterialsListSession = (
  storage: Pick<Storage, 'setItem'>,
  snapshot: Omit<MaterialsListSessionSnapshot, 'version' | 'savedAt'>
) => {
  try {
    storage.setItem(
      MATERIALS_LIST_SESSION_KEY,
      JSON.stringify({ ...snapshot, version: 1, savedAt: Date.now() } satisfies MaterialsListSessionSnapshot)
    );
    return true;
  } catch {
    return false;
  }
};

export const readMaterialsListSession = (
  storage: Pick<Storage, 'getItem' | 'removeItem'>,
  now = Date.now()
): MaterialsListSessionSnapshot | null => {
  try {
    const raw = storage.getItem(MATERIALS_LIST_SESSION_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<MaterialsListSessionSnapshot>;
    const valid =
      value.version === 1 &&
      typeof value.savedAt === 'number' &&
      now - value.savedAt <= MAX_SNAPSHOT_AGE_MS &&
      value.pendingRestore === true &&
      typeof value.filters === 'object' &&
      value.filters !== null &&
      Array.isArray(value.materials) &&
      typeof value.meta === 'object' &&
      value.meta !== null &&
      Array.isArray(value.availableTags) &&
      (value.mobileView === 'compact' || value.mobileView === 'detail') &&
      typeof value.scrollY === 'number' &&
      value.scrollY >= 0;
    if (!valid) {
      storage.removeItem(MATERIALS_LIST_SESSION_KEY);
      return null;
    }
    return value as MaterialsListSessionSnapshot;
  } catch {
    storage.removeItem(MATERIALS_LIST_SESSION_KEY);
    return null;
  }
};
